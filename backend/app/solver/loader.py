"""Lädt Stammdaten + ggf. bestehende Planversion in einen PlanContext."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Gegenstand, Klasse, Lehrkraft, Planversion, Raum, Schule, Stunde,
    Unterrichtsveranstaltung,
)
from .engine import Block, Placement, PlanContext, RoomInfo, TeacherInfo


def school_config(db: Session, school_id: int) -> dict:
    schule = db.get(Schule, school_id)
    cfg = dict(Schule.DEFAULT_CONFIG)
    if schule and schule.config:
        cfg.update(schule.config)
    return cfg


def load_context(db: Session, school_id: int, schuljahr_id: int,
                 version: Planversion | None = None) -> PlanContext:
    cfg = school_config(db, school_id)

    rooms = {r.id: RoomInfo(r.id, r.name, r.kapazitaet, r.ausstattung or [], r.fachraum)
             for r in db.scalars(select(Raum).where(Raum.school_id == school_id)).all()}
    teachers = {}
    for t in db.scalars(select(Lehrkraft).where(Lehrkraft.school_id == school_id, Lehrkraft.aktiv.is_(True))).all():
        teachers[t.id] = TeacherInfo(
            id=t.id, lehrverpflichtung=t.lehrverpflichtung, max_tagesstunden=t.max_tagesstunden,
            qualifikationen=t.qualifikationen or [], sperrzeiten=t.sperrzeiten or {},
            wunschfenster=t.wunschfenster or {}, unterrichtsfreie_tage=t.unterrichtsfreie_tage or [],
        )
    klassen = {k.id: k for k in db.scalars(
        select(Klasse).where(Klasse.school_id == school_id, Klasse.schuljahr_id == schuljahr_id)).all()}
    gegenstaende = {g.id: g for g in db.scalars(
        select(Gegenstand).where(Gegenstand.school_id == school_id)).all()}

    veranstaltungen = db.scalars(select(Unterrichtsveranstaltung).where(
        Unterrichtsveranstaltung.school_id == school_id,
        Unterrichtsveranstaltung.schuljahr_id == schuljahr_id,
    )).all()

    vdicts = []
    for v in veranstaltungen:
        k = klassen.get(v.klasse_id)
        g = gegenstaende.get(v.gegenstand_id)
        vdicts.append({
            "id": v.id, "klasse_id": v.klasse_id,
            "schuelerzahl": k.schuelerzahl if k else 25,
            "stammraum_id": k.stammraum_id if k else None,
            "gegenstand_code": g.code if g else "?",
            "benoetigt_fachraum": g.benoetigt_fachraum if g else False,
            "benoetigte_ausstattung": g.benoetigte_ausstattung or [] if g else [],
            "kopplungsgruppe": v.kopplungsgruppe,
            "aufteilung": v.aufteilung, "wochenstunden": v.wochenstunden,
            "lehrkraft_id": v.lehrkraft_id, "fixiert": v.fixiert,
        })

    from .engine import expand_blocks
    blocks: list[Block] = expand_blocks(vdicts)

    ctx = PlanContext(
        tage=cfg["tage_pro_woche"], slots=cfg["slots_pro_tag"],
        max_am_stueck=cfg["max_stunden_am_stueck"],
        mittagsgrenze_slot=cfg["mittagsgrenze_slot"],
        gewichte=cfg["gewichte"], blocks=blocks, teachers=teachers, rooms=rooms,
        klassen_stammraum={kid: k.stammraum_id for kid, k in klassen.items()},
    )

    ctx.blocks = blocks

    # bestehende Planversion als Startwert übernehmen (FD-302 Startwert aus aktuellem Plan)
    initial: dict[str, Placement] = {}
    if version is not None:
        stunden = db.scalars(select(Stunde).where(Stunde.planversion_id == version.id)).all()
        block_by_veranstaltung: dict[int, list[Block]] = {}
        for b in blocks:
            block_by_veranstaltung.setdefault(b.veranstaltung_id, []).append(b)
        used: dict[int, int] = {}
        for s in stunden:
            blist = block_by_veranstaltung.get(s.veranstaltung_id, [])
            idx = used.get(s.veranstaltung_id, 0)
            if idx < len(blist):
                b = blist[idx]
                b.laenge = s.laenge
                initial[b.key] = Placement(s.wochentag, s.slot, s.raum_id, s.lehrkraft_id)
                used[s.veranstaltung_id] = idx + 1
    return ctx, initial
