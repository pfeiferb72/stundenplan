"""Asynchrone Solver-Läufe (FD-302, NF-102/NF-303): Thread + DB-Jobtabelle, abbrechbar."""
from __future__ import annotations

import threading
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Planversion, SolverRun, SolverStatus, Stunde
from .solver import engine
from .solver.heuristic import solve
from .solver.loader import load_context

_cancel_events: dict[int, threading.Event] = {}
_lock = threading.Lock()


def request_cancel(run_id: int) -> bool:
    with _lock:
        ev = _cancel_events.get(run_id)
    if ev:
        ev.set()
        return True
    return False


def run_solver_job(run_id: int) -> None:
    """Wird in einem Hintergrund-Thread ausgeführt. Schreibt Ergebnis transaktional in eine neue Planversion."""
    db: Session = SessionLocal()
    try:
        run = db.get(SolverRun, run_id)
        if not run:
            return
        run.status = SolverStatus.RUNNING.value
        run.gestartet_am = datetime.utcnow()
        db.commit()

        cancel = threading.Event()
        with _lock:
            _cancel_events[run_id] = cancel

        ctx, initial = load_context(db, run.school_id, run.schuljahr_id,
                                    db.get(Planversion, run.ziel_version_id) if run.ziel_version_id else None)

        fixed_keys = set()
        if run.ziel_version_id:
            stunden = db.scalars(select(Stunde).where(
                Stunde.planversion_id == run.ziel_version_id,
                Stunde.id.in_(run.fixierungen or []),
            )).all()
            # Fixierungen beziehen sich auf Stunden-IDs -> betroffene Blöcke nicht bewegen
            veranstaltung_fix = {s.veranstaltung_id for s in stunden}
            for b in ctx.blocks:
                if b.veranstaltung_id in veranstaltung_fix or b.fixiert:
                    fixed_keys.add(b.key)

        def on_progress(p: float):
            s = SessionLocal()
            try:
                r = s.get(SolverRun, run_id)
                if r:
                    r.progress = round(p, 4)
                    s.commit()
            finally:
                s.close()

        assign, best_pen = solve(
            ctx, cancel, budget_s=run.zeitbudget_s, seed=run.seed,
            initial=initial or None, fixed_keys=fixed_keys, on_progress=on_progress,
        )

        total, hard, soft = engine.score(ctx, assign)

        s = SessionLocal()
        try:
            r = s.get(SolverRun, run_id)
            if cancel.is_set():
                r.status = SolverStatus.ABORTED.value
                r.progress = 1.0
            else:
                # Ergebnis transaktional als neue Planversion speichern (NF-303)
                version = Planversion(
                    school_id=r.school_id, schuljahr_id=r.schuljahr_id,
                    name=f"Solver-Lauf {run_id}", status="entwurf",
                    score=total if not hard else total, basis_version_id=r.ziel_version_id,
                )
                s.add(version)
                s.flush()
                block_by_key = {b.key: b for b in ctx.blocks}
                for key, p in assign.items():
                    b = block_by_key[key]
                    s.add(Stunde(
                        planversion_id=version.id, veranstaltung_id=b.veranstaltung_id,
                        wochentag=p.day, slot=p.slot, laenge=b.laenge,
                        raum_id=p.raum_id, lehrkraft_id=p.lehrkraft_id,
                        fixiert=b.key in fixed_keys,
                    ))
                r.ergebnis_version_id = version.id
                r.ergebnis_score = total
                r.status = SolverStatus.DONE.value
                r.progress = 1.0
            r.beendet_am = datetime.utcnow()
            s.commit()
        finally:
            s.close()
    except Exception as exc:  # Solver-Absturz darf keine Daten verlieren (NF-303)
        s = SessionLocal()
        try:
            r = s.get(SolverRun, run_id)
            if r:
                r.status = SolverStatus.FAILED.value
                r.fehler = str(exc)
                r.beendet_am = datetime.utcnow()
                s.commit()
        finally:
            s.close()
    finally:
        with _lock:
            _cancel_events.pop(run_id, None)
        db.close()


def start_solver_job(run: SolverRun) -> threading.Thread:
    t = threading.Thread(target=run_solver_job, args=(run.id,), daemon=True)
    t.start()
    return t
