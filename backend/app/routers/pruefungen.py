"""Prüfungs- und Terminplanung (Abschnitt 4.6, FD-601/602/604)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Role, require_roles
from ..db import get_db
from ..deps import SchoolDep
from ..models import Pruefungstermin
from ..schemas import PruefungIn, PruefungOut

router = APIRouter(prefix="/pruefungen", tags=["pruefungen"])
PLANER_ROLES = [Role.PLANER, Role.ADMIN, Role.SYSADMIN, Role.SCHULLEITUNG]


@router.post("", response_model=PruefungOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_p(body: PruefungIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    p = Pruefungstermin(school_id=school_id, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("", response_model=list[PruefungOut])
def list_p(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    return db.scalars(select(Pruefungstermin).where(Pruefungstermin.school_id == school_id)).all()


@router.get("/{pid}/kollision")
def kollision(pid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    """FD-602: Kollisionsprüfung Prüfungen × Unterricht × Raum × Aufsicht."""
    p = db.get(Pruefungstermin, pid)
    if not p or p.school_id != school_id:
        raise HTTPException(404, "Prüfungstermin nicht gefunden")
    konflikte = []
    others = db.scalars(select(Pruefungstermin).where(
        Pruefungstermin.school_id == school_id, Pruefungstermin.datum == p.datum,
        Pruefungstermin.id != p.id)).all()
    for o in others:
        overlap = not (o.bis_slot < p.von_slot or o.von_slot > p.bis_slot)
        if not overlap:
            continue
        if p.raum_id and o.raum_id == p.raum_id:
            konflikte.append({"art": "raum", "termin_id": o.id, "raum_id": p.raum_id})
        if p.pruefer_id and o.pruefer_id == p.pruefer_id:
            konflikte.append({"art": "aufsicht", "termin_id": o.id, "pruefer_id": p.pruefer_id})
        if p.klasse_id and o.klasse_id == p.klasse_id:
            konflikte.append({"art": "klasse", "termin_id": o.id, "klasse_id": p.klasse_id})
    p.kollisionsfrei = len(konflikte) == 0
    db.commit()
    return {"pruefung_id": pid, "kollisionsfrei": p.kollisionsfrei, "konflikte": konflikte}


@router.delete("/{pid}", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def delete_p(pid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    p = db.get(Pruefungstermin, pid)
    if not p or p.school_id != school_id:
        raise HTTPException(404, "Prüfungstermin nicht gefunden")
    db.delete(p)
    db.commit()
    return {"ok": True}
