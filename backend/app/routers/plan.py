"""Planerstellung: Planversionen, Stunden, Echtzeit-Validierung (FD-301), Undo/Redo (FD-307),
Diff/Varianten (FD-306), Score (FD-305), Konfliktübersicht (FD-209), Solver-Läufe (FD-302..304)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Role, audit, get_current_user, require_roles
from ..db import get_db
from ..deps import SchoolDep
from ..jobs import request_cancel, start_solver_job
from ..models import (
    PlanOperation, Planversion, SolverRun, Stunde, User, Unterrichtsveranstaltung,
)
from ..schemas import (
    PlanversionIn, PlanversionOut, ScoreOut, SolverRunIn, SolverRunOut, StundeIn, StundeMoveIn, StundeOut,
    ValidateOut,
)
from ..solver import engine
from ..solver.loader import load_context

router = APIRouter(prefix="/plan", tags=["plan"])
SOLVER_ROUTER_PREFIX = "/solver"
PLANER_ROLES = [Role.PLANER, Role.ADMIN, Role.SYSADMIN]


def _get_version(db: Session, school_id: int, vid: int) -> Planversion:
    v = db.get(Planversion, vid)
    if not v or v.school_id != school_id:
        raise HTTPException(404, "Planversion nicht gefunden")
    return v


def _assign_from_version(db: Session, ctx, version: Planversion) -> dict[str, engine.Placement]:
    block_by_veranstaltung: dict[int, list[engine.Block]] = {}
    for b in ctx.blocks:
        block_by_veranstaltung.setdefault(b.veranstaltung_id, []).append(b)
    used: dict[int, int] = {}
    assign: dict[str, engine.Placement] = {}
    for s in db.scalars(select(Stunde).where(Stunde.planversion_id == version.id)).all():
        blist = block_by_veranstaltung.get(s.veranstaltung_id, [])
        idx = used.get(s.veranstaltung_id, 0)
        if idx < len(blist):
            b = blist[idx]
            b.laenge = s.laenge
            assign[b.key] = engine.Placement(s.wochentag, s.slot, s.raum_id, s.lehrkraft_id)
            used[s.veranstaltung_id] = idx + 1
    return assign


def _log_op(db: Session, version: Planversion, typ: str, payload: dict, undo: dict, user: User | None):
    seq = (db.scalar(select(func.max(PlanOperation.seq)).where(
        PlanOperation.planversion_id == version.id)) or 0) + 1
    db.add(PlanOperation(planversion_id=version.id, seq=seq, typ=typ, payload=payload,
                         undo_payload=undo, user_id=user.id if user else None))


# --- Planversionen (FD-306) ---

@router.post("/versionen", response_model=PlanversionOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_version(body: PlanversionIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    v = Planversion(school_id=school_id, name=body.name, schuljahr_id=body.schuljahr_id,
                    basis_version_id=body.basis_version_id, created_by=user.id)
    db.add(v)
    db.commit()
    # Basis-Version kopieren (FD-310 Übernahme der Zuweisungen)
    if body.basis_version_id:
        basis = _get_version(db, school_id, body.basis_version_id)
        for s in db.scalars(select(Stunde).where(Stunde.planversion_id == basis.id)).all():
            db.add(Stunde(planversion_id=v.id, veranstaltung_id=s.veranstaltung_id, wochentag=s.wochentag,
                          slot=s.slot, laenge=s.laenge, raum_id=s.raum_id, lehrkraft_id=s.lehrkraft_id,
                          zustand=s.zustand, fixiert=s.fixiert))
        db.commit()
    db.refresh(v)
    audit(db, user, "planversion_anlegen", "planversion", {"id": v.id, "name": v.name})
    return v


@router.get("/versionen", response_model=list[PlanversionOut])
def list_versionen(schuljahr_id: int | None = None, school_id: int = Depends(SchoolDep),
                   db: Session = Depends(get_db)):
    q = select(Planversion).where(Planversion.school_id == school_id)
    if schuljahr_id:
        q = q.where(Planversion.schuljahr_id == schuljahr_id)
    return db.scalars(q.order_by(Planversion.id.desc())).all()


@router.get("/versionen/{vid}", response_model=PlanversionOut)
def get_version(vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    return _get_version(db, school_id, vid)


@router.delete("/versionen/{vid}", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def delete_version(vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    v = _get_version(db, school_id, vid)
    if v.status == "veroeffentlicht":
        raise HTTPException(400, "Veröffentlichte Version darf nicht gelöscht werden")
    audit(db, user, "planversion_geloescht", "planversion", {"id": vid})
    db.query(Stunde).filter(Stunde.planversion_id == vid).delete()
    db.query(PlanOperation).filter(PlanOperation.planversion_id == vid).delete()
    db.delete(v)
    db.commit()
    return {"ok": True}


# --- Stunden (FD-301) ---

@router.get("/versionen/{vid}/stunden", response_model=list[StundeOut])
def list_stunden(vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    v = _get_version(db, school_id, vid)
    return db.scalars(select(Stunde).where(Stunde.planversion_id == v.id)).all()


@router.post("/versionen/{vid}/stunden", response_model=StundeOut,
             dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_stunde(vid: int, body: StundeIn, school_id: int = Depends(SchoolDep),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    v = _get_version(db, school_id, vid)
    ctx, _ = load_context(db, school_id, v.schuljahr_id, v)
    assign = _assign_from_version(db, ctx, v)
    ver = db.get(Unterrichtsveranstaltung, body.veranstaltung_id)
    if not ver or ver.school_id != school_id:
        raise HTTPException(404, "Veranstaltung nicht gefunden")
    # temporärer Block für die neue Stunde
    block = engine.Block(key=f"neu:{body.veranstaltung_id}:{len(assign)}",
                         veranstaltung_id=ver.id, klasse_id=ver.klasse_id, schuelerzahl=25,
                         stammraum_id=None, gegenstand_code="?", benoetigt_fachraum=False,
                         benoetigte_ausstattung=[], kopplungsgruppe=ver.kopplungsgruppe,
                         laenge=body.laenge, fix_lehrkraft_id=ver.lehrkraft_id, fixiert=False)
    # echte Stammdaten für Validierung
    from ..models import Gegenstand, Klasse
    g = db.get(Gegenstand, ver.gegenstand_id)
    k = db.get(Klasse, ver.klasse_id)
    if g:
        block.gegenstand_code = g.code
        block.benoetigt_fachraum = g.benoetigt_fachraum
        block.benoetigte_ausstattung = g.benoetigte_ausstattung or []
    if k:
        block.schuelerzahl = k.schuelerzahl
        block.stammraum_id = k.stammraum_id
    ctx.blocks.append(block)
    p = engine.Placement(body.wochentag, body.slot, body.raum_id, body.lehrkraft_id)
    check = engine.validate_move(ctx, assign, block.key, p)
    if not check["zulaessig"]:
        raise HTTPException(409, detail={"message": "Harte Restriktion verletzt – Platzierung blockiert (FD-204)",
                                          **check})
    s = Stunde(planversion_id=v.id, veranstaltung_id=body.veranstaltung_id, wochentag=body.wochentag,
               slot=body.slot, laenge=body.laenge, raum_id=body.raum_id, lehrkraft_id=body.lehrkraft_id,
               zustand=body.zustand, fixiert=body.fixiert)
    db.add(s)
    db.flush()
    _log_op(db, v, "stunde_anlegen", {"stunde_id": s.id}, {"stunde_id": s.id}, user)
    db.commit()
    db.refresh(s)
    return s


@router.patch("/versionen/{vid}/stunden/{sid}", response_model=StundeOut,
              dependencies=[Depends(require_roles(*PLANER_ROLES))])
def move_stunde(vid: int, sid: int, body: StundeMoveIn, school_id: int = Depends(SchoolDep),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """FD-301: Drag-and-Drop-Platzierung mit Echtzeit-Validierung; FD-307: transaktional mit Undo."""
    v = _get_version(db, school_id, vid)
    s = db.get(Stunde, sid)
    if not s or s.planversion_id != v.id:
        raise HTTPException(404, "Stunde nicht gefunden")
    if s.fixiert:
        raise HTTPException(409, "Stunde ist fixiert und darf nicht verschoben werden (FD-303)")
    old = {"wochentag": s.wochentag, "slot": s.slot, "raum_id": s.raum_id,
           "lehrkraft_id": s.lehrkraft_id, "fixiert": s.fixiert}
    new = {k: (val if val is not None else old[k]) for k, val in body.model_dump().items()}

    ctx, _ = load_context(db, school_id, v.schuljahr_id, v)
    assign = _assign_from_version(db, ctx, v)
    block_key = None
    for key, p in assign.items():
        if p.day == s.wochentag and p.slot == s.slot and p.raum_id == s.raum_id and p.lehrkraft_id == s.lehrkraft_id:
            block_key = key
    if block_key is None:
        # Stunde nicht im Context (z. B. manuell angelegt) -> Block synthetisieren
        ver = db.get(Unterrichtsveranstaltung, s.veranstaltung_id)
        from ..models import Gegenstand, Klasse
        g = db.get(Gegenstand, ver.gegenstand_id) if ver else None
        k = db.get(Klasse, ver.klasse_id) if ver else None
        block = engine.Block(key=f"stunde:{s.id}", veranstaltung_id=s.veranstaltung_id,
                             klasse_id=ver.klasse_id if ver else 0,
                             schuelerzahl=k.schuelerzahl if k else 25,
                             stammraum_id=k.stammraum_id if k else None,
                             gegenstand_code=g.code if g else "?",
                             benoetigt_fachraum=g.benoetigt_fachraum if g else False,
                             benoetigte_ausstattung=g.benoetigte_ausstattung or [] if g else [],
                             kopplungsgruppe=ver.kopplungsgruppe if ver else None,
                             laenge=s.laenge, fix_lehrkraft_id=ver.lehrkraft_id if ver else None,
                             fixiert=s.fixiert)
        ctx.blocks.append(block)
        block_key = block.key
        assign[block_key] = engine.Placement(s.wochentag, s.slot, s.raum_id, s.lehrkraft_id)
    p = engine.Placement(new["wochentag"], new["slot"], new["raum_id"], new["lehrkraft_id"])
    check = engine.validate_move(ctx, assign, block_key, p)
    if not check["zulaessig"]:
        raise HTTPException(409, detail={"message": "Harte Restriktion verletzt – Platzierung blockiert (FD-204)",
                                          **check})
    s.wochentag, s.slot, s.raum_id, s.lehrkraft_id, s.fixiert = (
        new["wochentag"], new["slot"], new["raum_id"], new["lehrkraft_id"], new["fixiert"])
    _log_op(db, v, "stunde_verschieben", {"stunde_id": sid, "neu": new}, {"stunde_id": sid, "alt": old}, user)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/versionen/{vid}/stunden/{sid}", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def delete_stunde(vid: int, sid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    v = _get_version(db, school_id, vid)
    s = db.get(Stunde, sid)
    if not s or s.planversion_id != v.id:
        raise HTTPException(404, "Stunde nicht gefunden")
    payload = {"stunde_id": sid, "daten": {k: getattr(s, k) for k in
                ("veranstaltung_id", "wochentag", "slot", "laenge", "raum_id", "lehrkraft_id", "zustand", "fixiert")}}
    db.delete(s)
    _log_op(db, v, "stunde_geloescht", payload, payload, user)
    db.commit()
    return {"ok": True}


# --- Validierung / Score / Konflikte (FD-209, FD-305) ---

@router.get("/versionen/{vid}/validate", response_model=ValidateOut)
def validate_version(vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    v = _get_version(db, school_id, vid)
    ctx, _ = load_context(db, school_id, v.schuljahr_id, v)
    assign = _assign_from_version(db, ctx, v)
    total, hard, soft = engine.score(ctx, assign)
    return ValidateOut(harte_verletzungen=hard, weiche_verletzungen=soft, score=total)


@router.get("/versionen/{vid}/score", response_model=ScoreOut)
def score_version(vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    v = _get_version(db, school_id, vid)
    ctx, _ = load_context(db, school_id, v.schuljahr_id, v)
    assign = _assign_from_version(db, ctx, v)
    total, hard, soft = engine.score(ctx, assign)
    v.score = total if not hard else total
    db.commit()
    return ScoreOut(score=total, harte_verletzungen=len(hard), weiche_verletzungen=soft)


@router.get("/versionen/{vid}/diff/{other_vid}")
def diff_versionen(vid: int, other_vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    """FD-306: Vergleichsansicht zweier Planversionen."""
    v1 = _get_version(db, school_id, vid)
    v2 = _get_version(db, school_id, other_vid)

    def stunden_map(v):
        return {s.id: s for s in db.scalars(select(Stunde).where(Stunde.planversion_id == v.id)).all()}
    m1, m2 = stunden_map(v1), stunden_map(v2)

    def key(s):
        return (s.veranstaltung_id, s.wochentag, s.slot)
    k1 = {key(s): s for s in m1.values()}
    k2 = {key(s): s for s in m2.values()}
    geaendert, nur_v1, nur_v2 = [], [], []
    for k, s in k1.items():
        if k in k2:
            o = k2[k]
            if (o.raum_id, o.lehrkraft_id) != (s.raum_id, s.lehrkraft_id):
                geaendert.append({"veranstaltung_id": s.veranstaltung_id, "wochentag": s.wochentag, "slot": s.slot,
                                  "von": {"raum_id": s.raum_id, "lehrkraft_id": s.lehrkraft_id},
                                  "nach": {"raum_id": o.raum_id, "lehrkraft_id": o.lehrkraft_id}})
        else:
            nur_v1.append({"veranstaltung_id": s.veranstaltung_id, "wochentag": s.wochentag, "slot": s.slot})
    for k, s in k2.items():
        if k not in k1:
            nur_v2.append({"veranstaltung_id": s.veranstaltung_id, "wochentag": s.wochentag, "slot": s.slot})
    return {"version_a": vid, "version_b": other_vid, "geaendert": geaendert,
            "nur_in_a": nur_v1, "nur_in_b": nur_v2}


# --- Undo/Redo (FD-307) ---

@router.post("/versionen/{vid}/undo", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def undo(vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    v = _get_version(db, school_id, vid)
    op = db.scalar(select(PlanOperation).where(PlanOperation.planversion_id == v.id)
                   .order_by(PlanOperation.seq.desc()).limit(1))
    if not op:
        raise HTTPException(404, "Keine rückgängig zu machende Operation")
    _apply_undo(db, op)
    audit(db, user, "plan_undo", "planversion", {"version": vid, "op": op.typ})
    db.commit()
    return {"ok": True, "op": op.typ, "seq": op.seq}


def _apply_undo(db: Session, op: PlanOperation):
    u = op.undo_payload
    if op.typ == "stunde_verschieben":
        s = db.get(Stunde, u["stunde_id"])
        if s:
            for k, val in u["alt"].items():
                setattr(s, k, val)
    elif op.typ == "stunde_anlegen":
        s = db.get(Stunde, u["stunde_id"])
        if s:
            db.delete(s)
    elif op.typ == "stunde_geloescht":
        d = u["daten"]
        db.add(Stunde(planversion_id=op.planversion_id, **d))
    db.delete(op)


# --- Solver (FD-302..FD-304, NF-102) ---

@router.post("/solver/runs", response_model=SolverRunOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def start_solver(body: SolverRunIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    run = SolverRun(school_id=school_id, schuljahr_id=body.schuljahr_id, ziel_version_id=body.ziel_version_id,
                    zeitbudget_s=body.zeitbudget_s, fixierungen=body.fixierungen,
                    teilloesung=body.teilloesung, seed=body.seed)
    db.add(run)
    db.commit()
    db.refresh(run)
    audit(db, user, "solver_gestartet", "solver_run", {"id": run.id, "budget": body.zeitbudget_s})
    start_solver_job(run)
    return run


@router.get("/solver/runs", response_model=list[SolverRunOut])
def list_runs(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    return db.scalars(select(SolverRun).where(SolverRun.school_id == school_id)
                      .order_by(SolverRun.id.desc())).all()


@router.get("/solver/runs/{rid}", response_model=SolverRunOut)
def get_run(rid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    r = db.get(SolverRun, rid)
    if not r or r.school_id != school_id:
        raise HTTPException(404, "Solver-Lauf nicht gefunden")
    return r


@router.post("/solver/runs/{rid}/abort", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def abort_run(rid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    r = db.get(SolverRun, rid)
    if not r or r.school_id != school_id:
        raise HTTPException(404, "Solver-Lauf nicht gefunden")
    if r.status not in ("pending", "running"):
        raise HTTPException(409, "Lauf ist nicht aktiv")
    request_cancel(rid)
    audit(db, user, "solver_abgebrochen", "solver_run", {"id": rid})
    return {"ok": True}
