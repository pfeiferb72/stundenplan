"""Vertretungsplanung (Abschnitt 4.5, FD-501..FD-507)."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Role, audit, get_current_user, require_roles
from ..db import get_db
from ..deps import SchoolDep
from ..models import (
    Abwesenheit, Gegenstand, Klasse, Lehrkraft, Notification, Planversion, Stunde,
    Unterrichtsveranstaltung, User, Vertretung, VertretungsTyp,
)
from ..schemas import AbwesenheitIn, AbwesenheitOut, VertretungIn, VertretungOut, VertretungPatch
from ..solver.engine import is_teacher_available
from ..solver.loader import school_config

router = APIRouter(prefix="/vertretung", tags=["vertretung"])
PLANER_ROLES = [Role.PLANER, Role.ADMIN, Role.SYSADMIN, Role.SCHULLEITUNG, Role.VERWALTUNG]


def _published_version(db: Session, school_id: int) -> Planversion:
    v = db.scalar(select(Planversion).where(
        Planversion.school_id == school_id, Planversion.status == "veroeffentlicht"
    ).order_by(Planversion.veroeffentlicht_at.desc().nullslast()).limit(1))
    if not v:
        v = db.scalar(select(Planversion).where(Planversion.school_id == school_id)
                      .order_by(Planversion.id.desc()).limit(1))
    if not v:
        raise HTTPException(409, "Kein Plan vorhanden – zuerst Planversion veröffentlichen")
    return v


@router.post("/abwesenheiten", response_model=AbwesenheitOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_abwesenheit(body: AbwesenheitIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    lk = db.get(Lehrkraft, body.lehrkraft_id)
    if not lk or lk.school_id != school_id:
        raise HTTPException(404, "Lehrkraft nicht gefunden")
    ab = Abwesenheit(school_id=school_id, lehrkraft_id=body.lehrkraft_id, datum=body.datum,
                     typ=body.typ, grund=body.grund, gemeldet_von=user.id)
    db.add(ab)
    audit(db, user, "abwesenheit_gemeldet", "abwesenheit", {"lehrkraft_id": body.lehrkraft_id,
                                                             "datum": str(body.datum), "typ": body.typ})
    db.commit()
    db.refresh(ab)
    return ab


@router.get("/abwesenheiten", response_model=list[AbwesenheitOut])
def list_abwesenheiten(datum: date | None = None, school_id: int = Depends(SchoolDep),
                       db: Session = Depends(get_db)):
    q = select(Abwesenheit).where(Abwesenheit.school_id == school_id)
    if datum:
        q = q.where(Abwesenheit.datum == datum)
    return db.scalars(q.order_by(Abwesenheit.datum)).all()


@router.get("/abwesenheiten/{aid}/betroffene")
def betroffene_stunden(aid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    """FD-502: alle betroffenen Unterrichtsstunden des Abwesenheitstags."""
    ab = db.get(Abwesenheit, aid)
    if not ab or ab.school_id != school_id:
        raise HTTPException(404, "Abwesenheit nicht gefunden")
    version = _published_version(db, school_id)
    tag = ab.datum.weekday()
    stunden = db.scalars(select(Stunde).where(
        Stunde.planversion_id == version.id,
        Stunde.lehrkraft_id == ab.lehrkraft_id, Stunde.wochentag == tag,
        Stunde.zustand == "geplant")).all()
    out = []
    for s in stunden:
        v = db.get(Unterrichtsveranstaltung, s.veranstaltung_id)
        g = db.get(Gegenstand, v.gegenstand_id) if v else None
        k = db.get(Klasse, v.klasse_id) if v else None
        out.append({"stunde_id": s.id, "wochentag": s.wochentag, "slot": s.slot, "laenge": s.laenge,
                    "fach": g.code if g else "?", "klasse": k.name if k else "?",
                    "raum_id": s.raum_id, "veranstaltung_id": s.veranstaltung_id})
    return {"abwesenheit_id": aid, "datum": str(ab.datum), "planversion_id": version.id, "stunden": out}


@router.post("/abwesenheiten/{aid}/vorschlaege", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def vorschlaege(aid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """FD-503/505: Vertretungsvorschläge nach Prioritätenkaskade in einem Schritt."""
    ab = db.get(Abwesenheit, aid)
    if not ab or ab.school_id != school_id:
        raise HTTPException(404, "Abwesenheit nicht gefunden")
    version = _published_version(db, school_id)
    cfg = school_config(db, school_id)
    kaskade = cfg.get("vertretungskaskade", ["fachvertretung", "aufgabenbetreuung", "zusammenlegung", "ausfall"])
    tag = ab.datum.weekday()
    stunden = db.scalars(select(Stunde).where(
        Stunde.planversion_id == version.id, Stunde.lehrkraft_id == ab.lehrkraft_id,
        Stunde.wochentag == tag, Stunde.zustand == "geplant")).all()
    lehrkraefte = {t.id: t for t in db.scalars(select(Lehrkraft).where(
        Lehrkraft.school_id == school_id, Lehrkraft.aktiv.is_(True))).all()}
    # Belegung des Tages aus dem Plan: wer ist wann beschäftigt?
    busy: dict[int, set[int]] = {tid: set() for tid in lehrkraefte}
    for s in db.scalars(select(Stunde).where(Stunde.planversion_id == version.id, Stunde.wochentag == tag)).all():
        for sl in range(s.slot, s.slot + s.laenge):
            busy.setdefault(s.lehrkraft_id, set()).add(sl)
    # Vertretungskonten (FD-507): bisherige Vertretungen im Semester
    konto: dict[int, int] = {}
    for vt in db.scalars(select(Vertretung).where(
            Vertretung.school_id == school_id, Vertretung.vertreter_id.is_not(None),
            Vertretung.status.in_(["angepasst", "veroeffentlicht"]))).all():
        konto[vt.vertreter_id] = konto.get(vt.vertreter_id, 0) + 1

    vorschlaege = []
    for s in stunden:
        v = db.get(Unterrichtsveranstaltung, s.veranstaltung_id)
        g = db.get(Gegenstand, v.gegenstand_id) if v else None
        fach = g.code if g else None
        gewaehlt_typ, gewaehlter = None, None
        for stufe in kaskade:
            if stufe == "fachvertretung" and fach:
                cands = [t for tid, t in lehrkraefte.items()
                         if tid != ab.lehrkraft_id and fach in (t.qualifikationen or [])
                         and all(is_teacher_available(t, tag, sl) for sl in range(s.slot, s.slot + s.laenge))
                         and not any(sl in busy.get(tid, set()) for sl in range(s.slot, s.slot + s.laenge))]
                if cands:
                    cands.sort(key=lambda t: (konto.get(t.id, 0), t.id))
                    gewaehlt_typ, gewaehlter = VertretungsTyp.FACHVERTRETUNG.value, cands[0].id
            elif stufe == "aufgabenbetreuung":
                cands = [t for tid, t in lehrkraefte.items()
                         if tid != ab.lehrkraft_id
                         and all(is_teacher_available(t, tag, sl) for sl in range(s.slot, s.slot + s.laenge))
                         and not any(sl in busy.get(tid, set()) for sl in range(s.slot, s.slot + s.laenge))]
                if cands:
                    cands.sort(key=lambda t: (konto.get(t.id, 0), t.id))
                    gewaehlt_typ, gewaehlter = VertretungsTyp.AUFGABENBETREUUNG.value, cands[0].id
            elif stufe == "zusammenlegung":
                gewaehlt_typ, gewaehlter = VertretungsTyp.ZUSAMMENLEGUNG.value, None
            elif stufe == "ausfall":
                gewaehlt_typ, gewaehlter = VertretungsTyp.AUSFALL.value, None
            if gewaehlt_typ:
                break
        if gewaehlt_typ is None:
            gewaehlt_typ, gewaehlter = VertretungsTyp.AUSFALL.value, None
        vt = Vertretung(school_id=school_id, stunde_id=s.id, abwesenheit_id=ab.id,
                        typ=gewaehlt_typ, vertreter_id=gewaehlter, status="vorschlag")
        db.add(vt)
        db.flush()
        vorschlaege.append({"vertretung_id": vt.id, "stunde_id": s.id, "slot": s.slot,
                            "typ": gewaehlt_typ, "vertreter_id": gewaehlter})
        if gewaehlter:
            for sl in range(s.slot, s.slot + s.laenge):
                busy.setdefault(gewaehlter, set()).add(sl)
    audit(db, user, "vertretungsvorschlaege_erzeugt", "abwesenheit", {"id": aid, "anzahl": len(vorschlaege)})
    db.commit()
    return {"abwesenheit_id": aid, "vorschlaege": vorschlaege}


@router.get("/liste")
def vertretungsliste(datum: date | None = None, school_id: int = Depends(SchoolDep),
                      db: Session = Depends(get_db)):
    q = select(Vertretung).where(Vertretung.school_id == school_id)
    if datum:
        q = q.join(Abwesenheit, Abwesenheit.id == Vertretung.abwesenheit_id).where(Abwesenheit.datum == datum)
    out = []
    for vt in db.scalars(q.order_by(Vertretung.id)).all():
        s = db.get(Stunde, vt.stunde_id)
        v = db.get(Unterrichtsveranstaltung, s.veranstaltung_id) if s else None
        g = db.get(Gegenstand, v.gegenstand_id) if v else None
        k = db.get(Klasse, v.klasse_id) if v else None
        orig = db.get(Lehrkraft, s.lehrkraft_id) if s else None
        ers = db.get(Lehrkraft, vt.vertreter_id) if vt.vertreter_id else None
        ab = db.get(Abwesenheit, vt.abwesenheit_id) if vt.abwesenheit_id else None
        out.append({
            "id": vt.id, "stunde_id": vt.stunde_id, "datum": str(ab.datum) if ab else None,
            "slot": s.slot if s else None, "laenge": s.laenge if s else None,
            "fach": g.code if g else "?", "klasse": k.name if k else "?",
            "original": f"{orig.nachname} {orig.vorname}" if orig else "?",
            "typ": vt.typ,
            "vertreter": f"{ers.nachname} {ers.vorname}" if ers else None,
            "status": vt.status,
        })
    return out


@router.patch("/{vid}", response_model=VertretungOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def patch_vertretung(vid: int, body: VertretungPatch, school_id: int = Depends(SchoolDep),
                     db: Session = Depends(get_db)):
    """FD-505: manuelle Anpassung vor Veröffentlichung."""
    vt = db.get(Vertretung, vid)
    if not vt or vt.school_id != school_id:
        raise HTTPException(404, "Vertretung nicht gefunden")
    if vt.status == "veroeffentlicht":
        raise HTTPException(409, "Bereits veröffentlichte Vertretung ist schreibgeschützt")
    for f, val in body.model_dump().items():
        if val is not None:
            setattr(vt, f, val)
    if body.typ or body.vertreter_id:
        vt.status = "angepasst"
    db.commit()
    db.refresh(vt)
    return vt


@router.post("/veroeffentlichen", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def veroeffentlichen(datum: date, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """FD-506: Vertretungsplan veröffentlichen inkl. Betroffenenbenachrichtigung (FD-801)."""
    q = select(Vertretung).join(Abwesenheit, Abwesenheit.id == Vertretung.abwesenheit_id).where(
        Vertretung.school_id == school_id,
        Vertretung.status.in_(["vorschlag", "angepasst"]),
        Abwesenheit.datum == datum)
    vts = db.scalars(q).all()
    if not vts:
        raise HTTPException(404, "Keine offenen Vertretungsvorschläge für dieses Datum")
    betroffene_user = set()
    for vt in vts:
        vt.status = "veroeffentlicht"
        vt.veroeffentlicht_am = datetime.utcnow()
        s = db.get(Stunde, vt.stunde_id)
        if s:
            s.zustand = "vertreten"
            s.vertretung_id = vt.id
        users = db.scalars(select(User).where(User.school_id == school_id)).all()
        for u in users:
            if (u.lehrkraft_id == s.lehrkraft_id) or (vt.vertreter_id and u.lehrkraft_id == vt.vertreter_id):
                betroffene_user.add(u.id)
                db.add(Notification(
                    school_id=school_id, user_id=u.id, typ="vertretung",
                    titel=f"Vertretungsplan {datum}",
                    text=f"Stunde Slot {s.slot} ({vt.typ}) betroffen." if s else "Vertretung veröffentlicht."))
    audit(db, user, "vertretungsplan_veroeffentlicht", "vertretung", {"datum": str(datum), "anzahl": len(vts)})
    db.commit()
    return {"veroeffentlicht": len(vts), "benachrichtigte_user": len(betroffene_user)}


@router.get("/konto")
def vertretungskonto(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    """FD-507: Vertretungs-/Mehrarbeitskonten je Lehrkraft."""
    konto = {}
    for vt in db.scalars(select(Vertretung).where(
            Vertretung.school_id == school_id, Vertretung.vertreter_id.is_not(None),
            Vertretung.status.in_(["angepasst", "veroeffentlicht"]))).all():
        lk = db.get(Lehrkraft, vt.vertreter_id)
        name = f"{lk.nachname} {lk.vorname}" if lk else str(vt.vertreter_id)
        e = konto.setdefault(name, {"vertretungen": 0, "fachvertretungen": 0, "ausfaelle": 0})
        e["vertretungen"] += 1
        if vt.typ == "fachvertretung":
            e["fachvertretungen"] += 1
    return konto
