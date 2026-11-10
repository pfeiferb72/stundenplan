"""Unterrichtsveranstaltungen (FD-201..FD-203): CRUD + automatische Erzeugung aus Stundentafel (FD-202)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Role, require_roles
from ..db import get_db
from ..deps import SchoolDep
from ..models import Klasse, Stundentafel, Unterrichtsveranstaltung
from ..schemas import VeranstaltungIn, VeranstaltungOut

router = APIRouter(prefix="/veranstaltungen", tags=["veranstaltungen"])
PLANER_ROLES = [Role.PLANER, Role.ADMIN, Role.SYSADMIN, Role.SCHULLEITUNG]


def _check_school(db: Session, school_id: int, klasse_id: int):
    k = db.get(Klasse, klasse_id)
    if not k or k.school_id != school_id:
        raise HTTPException(404, "Klasse nicht gefunden")
    return k


@router.post("", response_model=VeranstaltungOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_v(body: VeranstaltungIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    _check_school(db, school_id, body.klasse_id)
    v = Unterrichtsveranstaltung(school_id=school_id, **body.model_dump())
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@router.get("", response_model=list[VeranstaltungOut])
def list_v(schuljahr_id: int | None = None, klasse_id: int | None = None,
           school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    q = select(Unterrichtsveranstaltung).where(Unterrichtsveranstaltung.school_id == school_id)
    if schuljahr_id:
        q = q.where(Unterrichtsveranstaltung.schuljahr_id == schuljahr_id)
    if klasse_id:
        q = q.where(Unterrichtsveranstaltung.klasse_id == klasse_id)
    return db.scalars(q).all()


@router.patch("/{vid}", response_model=VeranstaltungOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def update_v(vid: int, body: VeranstaltungIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    v = db.get(Unterrichtsveranstaltung, vid)
    if not v or v.school_id != school_id:
        raise HTTPException(404, "Veranstaltung nicht gefunden")
    for f, val in body.model_dump().items():
        setattr(v, f, val)
    db.commit()
    db.refresh(v)
    return v


@router.delete("/{vid}", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def delete_v(vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    v = db.get(Unterrichtsveranstaltung, vid)
    if not v or v.school_id != school_id:
        raise HTTPException(404, "Veranstaltung nicht gefunden")
    db.delete(v)
    db.commit()
    return {"ok": True}


@router.post("/generieren/{schuljahr_id}", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def generiere_aus_stundentafel(schuljahr_id: int, school_id: int = Depends(SchoolDep),
                               db: Session = Depends(get_db)):
    """FD-202: erzeugt Unterrichtsveranstaltungen aus Stundentafel × Klassen des Schuljahrs.
    Bestehende Veranstaltungen des Schuljahrs bleiben erhalten (idempotent je Klasse+Stundentafel-Eintrag)."""
    klassen = db.scalars(select(Klasse).where(
        Klasse.school_id == school_id, Klasse.schuljahr_id == schuljahr_id)).all()
    tafeln = db.scalars(select(Stundentafel).where(Stundentafel.school_id == school_id)).all()
    erzeugt = 0
    for k in klassen:
        for st in tafeln:
            if st.jahrgang != k.jahrgang:
                continue
            exists = db.scalar(select(Unterrichtsveranstaltung).where(
                Unterrichtsveranstaltung.klasse_id == k.id,
                Unterrichtsveranstaltung.gegenstand_id == st.gegenstand_id,
                Unterrichtsveranstaltung.schuljahr_id == schuljahr_id,
                Unterrichtsveranstaltung.teilung_nr == 0,
            ))
            if exists:
                continue
            db.add(Unterrichtsveranstaltung(
                school_id=school_id, schuljahr_id=schuljahr_id, klasse_id=k.id,
                gegenstand_id=st.gegenstand_id, wochenstunden=st.wochenstunden,
                aufteilung=st.aufteilung, rhythmus=st.rhythmus,
            ))
            erzeugt += 1
    db.commit()
    return {"erzeugt": erzeugt, "klassen": len(klassen), "stundentafel_eintraege": len(tafeln)}
