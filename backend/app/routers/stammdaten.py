"""Stammdatenverwaltung (Abschnitt 4.1, FD-101..FD-109) + Schul-Konfiguration (FD-903)."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Role, audit, get_current_user, require_roles
from ..db import get_db
from ..deps import SchoolDep
from ..models import (
    Gegenstand, Klasse, Lehrkraft, Raum, Ressourcenpool, Schule, Schuljahr, Semester, Stundentafel, User,
)
from ..schemas import (
    ConfigPatch, GegenstandIn, GegenstandOut, KlasseIn, KlasseOut, LehrkraftIn, LehrkraftOut,
    RaumIn, RaumOut, SchuleIn, SchuleOut, SchuljahrIn, SchuljahrOut, SemesterIn, SemesterOut, StundentafelIn,
    StundentafelOut,
)

router = APIRouter(prefix="/stammdaten", tags=["stammdaten"])

PLANER_ROLES = [Role.PLANER, Role.ADMIN, Role.SYSADMIN, Role.VERWALTUNG, Role.SCHULLEITUNG]


# --- Mandant / Schule (FD-902) ---

@router.post("/schulen", response_model=SchuleOut, dependencies=[Depends(require_roles(Role.SYSADMIN))])
def create_schule(body: SchuleIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    cfg = dict(Schule.DEFAULT_CONFIG)
    cfg.update(body.config)
    schule = Schule(name=body.name, schulart=body.schulart, config=cfg)
    db.add(schule)
    audit(db, user, "schule_anlegen", "schule", {"name": body.name})
    db.commit()
    db.refresh(schule)
    return schule


@router.get("/schulen", response_model=list[SchuleOut], dependencies=[Depends(require_roles(Role.SYSADMIN))])
def list_schulen(db: Session = Depends(get_db)):
    return db.scalars(select(Schule)).all()


@router.get("/schule", response_model=SchuleOut)
def get_schule(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    schule = db.get(Schule, school_id)
    if not schule:
        raise HTTPException(404, "Schule nicht gefunden")
    return schule


@router.patch("/schule/config")
def patch_config(body: ConfigPatch, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                 user: User = Depends(require_roles(*PLANER_ROLES))):
    schule = db.get(Schule, school_id)
    cfg = dict(schule.config or {})
    cfg.update(body.config)
    schule.config = cfg
    audit(db, user, "config_geaendert", "schule", {"keys": list(body.config.keys())})
    db.commit()
    return {"config": cfg}


# --- Schuljahre / Semester (FD-101) ---

@router.post("/schuljahre", response_model=SchuljahrOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_schuljahr(body: SchuljahrIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    sj = Schuljahr(school_id=school_id, bezeichnung=body.bezeichnung, start=body.start, ende=body.ende)
    db.add(sj)
    audit(db, user, "schuljahr_anlegen", "schuljahr", {"bezeichnung": body.bezeichnung})
    db.commit()
    db.refresh(sj)
    return sj


@router.get("/schuljahre", response_model=list[SchuljahrOut])
def list_schuljahre(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    return db.scalars(select(Schuljahr).where(Schuljahr.school_id == school_id)).all()


@router.post("/semester", response_model=SemesterOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_semester(body: SemesterIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    sem = Semester(schuljahr_id=body.schuljahr_id, bezeichnung=body.bezeichnung, start=body.start, ende=body.ende)
    db.add(sem)
    db.commit()
    db.refresh(sem)
    return sem


@router.get("/schuljahre/{schuljahr_id}/semester", response_model=list[SemesterOut])
def list_semester(schuljahr_id: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    return db.scalars(select(Semester).where(Semester.schuljahr_id == schuljahr_id)).all()


# --- Klassen (FD-102) ---

@router.post("/klassen", response_model=KlasseOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_klasse(body: KlasseIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    if db.get(Schuljahr, body.schuljahr_id).school_id != school_id:
        raise HTTPException(400, "Schuljahr gehört nicht zu diesem Mandanten")
    k = Klasse(school_id=school_id, **body.model_dump())
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


@router.get("/klassen", response_model=list[KlasseOut])
def list_klassen(schuljahr_id: int | None = None, school_id: int = Depends(SchoolDep),
                 db: Session = Depends(get_db)):
    q = select(Klasse).where(Klasse.school_id == school_id)
    if schuljahr_id:
        q = q.where(Klasse.schuljahr_id == schuljahr_id)
    return db.scalars(q).all()


@router.patch("/klassen/{kid}", response_model=KlasseOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def update_klasse(kid: int, body: KlasseIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    k = db.get(Klasse, kid)
    if not k or k.school_id != school_id:
        raise HTTPException(404, "Klasse nicht gefunden")
    for f, v in body.model_dump().items():
        setattr(k, f, v)
    db.commit()
    db.refresh(k)
    return k


@router.delete("/klassen/{kid}", dependencies=[Depends(require_roles(*PLANER_ROLES))])
def delete_klasse(kid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    k = db.get(Klasse, kid)
    if not k or k.school_id != school_id:
        raise HTTPException(404, "Klasse nicht gefunden")
    audit(db, user, "klasse_geloescht", "klasse", {"id": kid})
    db.delete(k)
    db.commit()
    return {"ok": True}


# --- Gegenstände (FD-104) ---

@router.post("/gegenstaende", response_model=GegenstandOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_gegenstand(body: GegenstandIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    g = Gegenstand(school_id=school_id, **body.model_dump())
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


@router.get("/gegenstaende", response_model=list[GegenstandOut])
def list_gegenstaende(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    return db.scalars(select(Gegenstand).where(Gegenstand.school_id == school_id)).all()


@router.patch("/gegenstaende/{gid}", response_model=GegenstandOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def update_gegenstand(gid: int, body: GegenstandIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    g = db.get(Gegenstand, gid)
    if not g or g.school_id != school_id:
        raise HTTPException(404, "Gegenstand nicht gefunden")
    for f, v in body.model_dump().items():
        setattr(g, f, v)
    db.commit()
    db.refresh(g)
    return g


# --- Lehrkräfte (FD-103) ---

@router.post("/lehrkraefte", response_model=LehrkraftOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_lehrkraft(body: LehrkraftIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    lk = Lehrkraft(school_id=school_id, **body.model_dump())
    db.add(lk)
    db.commit()
    db.refresh(lk)
    return lk


@router.get("/lehrkraefte", response_model=list[LehrkraftOut])
def list_lehrkraefte(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    return db.scalars(select(Lehrkraft).where(Lehrkraft.school_id == school_id)).all()


@router.patch("/lehrkraefte/{lid}", response_model=LehrkraftOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def update_lehrkraft(lid: int, body: LehrkraftIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    lk = db.get(Lehrkraft, lid)
    if not lk or lk.school_id != school_id:
        raise HTTPException(404, "Lehrkraft nicht gefunden")
    for f, v in body.model_dump().items():
        setattr(lk, f, v)
    db.commit()
    db.refresh(lk)
    return lk


# --- Räume / Ressourcen (FD-105) ---

@router.post("/ressourcenpools")
def create_pool(name: str, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                user: User = Depends(require_roles(*PLANER_ROLES))):
    p = Ressourcenpool(school_id=school_id, name=name)
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "name": p.name}


@router.post("/raeume", response_model=RaumOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_raum(body: RaumIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    r = Raum(school_id=school_id, **body.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.get("/raeume", response_model=list[RaumOut])
def list_raeume(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    return db.scalars(select(Raum).where(Raum.school_id == school_id)).all()


@router.patch("/raeume/{rid}", response_model=RaumOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def update_raum(rid: int, body: RaumIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    r = db.get(Raum, rid)
    if not r or r.school_id != school_id:
        raise HTTPException(404, "Raum nicht gefunden")
    for f, v in body.model_dump().items():
        setattr(r, f, v)
    db.commit()
    db.refresh(r)
    return r


# --- Stundentafeln (FD-104/FD-107) ---

@router.post("/stundentafeln", response_model=StundentafelOut, dependencies=[Depends(require_roles(*PLANER_ROLES))])
def create_stundentafel(body: StundentafelIn, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    st = Stundentafel(school_id=school_id, **body.model_dump())
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


@router.get("/stundentafeln", response_model=list[StundentafelOut])
def list_stundentafeln(schulart: str | None = None, jahrgang: int | None = None,
                       school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    q = select(Stundentafel).where(Stundentafel.school_id == school_id)
    if schulart:
        q = q.where(Stundentafel.schulart == schulart)
    if jahrgang:
        q = q.where(Stundentafel.jahrgang == jahrgang)
    return db.scalars(q).all()


# --- SMLS-Import/Export (SS-10, FD-109): CSV mit Konfliktbericht ---

@router.post("/import/smls")
def import_smls(file: UploadFile = File(...), school_id: int = Depends(SchoolDep),
                db: Session = Depends(get_db), user: User = Depends(require_roles(*PLANER_ROLES))):
    """CSV-Import aus dem Schüler-/Lehrerverwaltungssystem. Erwartete Spalten je Entität über 'typ'-Spalte:
    typ=lehrkraft: nachname,vorname,email,lehrverpflichtung,qualifikationen(;-getrennt)
    typ=klasse: name,jahrgang,schuelerzahl,schuljahr_id
    Liefert Abgleichs- und Konfliktbericht (FD-109)."""
    text = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    bericht = {"importiert": 0, "aktualisiert": 0, "konflikte": [], "unbekannte_zeilen": []}
    for i, row in enumerate(reader, start=2):
        typ = (row.get("typ") or "").strip().lower()
        try:
            if typ == "lehrkraft":
                email = (row.get("email") or "").strip()
                existing = db.scalar(select(Lehrkraft).where(
                    Lehrkraft.school_id == school_id, Lehrkraft.email == email))
                quals = [q for q in (row.get("qualifikationen") or "").split(";") if q]
                if existing:
                    existing.nachname = row.get("nachname", existing.nachname)
                    existing.vorname = row.get("vorname", existing.vorname)
                    if row.get("lehrverpflichtung"):
                        existing.lehrverpflichtung = float(row["lehrverpflichtung"])
                    if quals:
                        existing.qualifikationen = quals
                    bericht["aktualisiert"] += 1
                else:
                    db.add(Lehrkraft(
                        school_id=school_id, nachname=row.get("nachname", ""),
                        vorname=row.get("vorname", ""), email=email,
                        lehrverpflichtung=float(row.get("lehrverpflichtung") or 20),
                        qualifikationen=quals))
                    bericht["importiert"] += 1
            elif typ == "klasse":
                name = (row.get("name") or "").strip()
                sj_id = int(row.get("schuljahr_id") or 0)
                sj = db.get(Schuljahr, sj_id)
                if not sj or sj.school_id != school_id:
                    bericht["konflikte"].append({"zeile": i, "grund": f"schuljahr_id {sj_id} ungültig"})
                    continue
                existing = db.scalar(select(Klasse).where(
                    Klasse.school_id == school_id, Klasse.schuljahr_id == sj_id, Klasse.name == name))
                if existing:
                    existing.schuelerzahl = int(row.get("schuelerzahl") or existing.schuelerzahl)
                    existing.jahrgang = int(row.get("jahrgang") or existing.jahrgang)
                    bericht["aktualisiert"] += 1
                else:
                    db.add(Klasse(school_id=school_id, schuljahr_id=sj_id, name=name,
                                  jahrgang=int(row.get("jahrgang") or 1),
                                  schuelerzahl=int(row.get("schuelerzahl") or 25)))
                    bericht["importiert"] += 1
            else:
                bericht["unbekannte_zeilen"].append({"zeile": i, "typ": typ})
        except Exception as exc:
            bericht["konflikte"].append({"zeile": i, "grund": str(exc)})
    audit(db, user, "smls_import", "stammdaten", {"datei": file.filename, "bericht": bericht})
    db.commit()
    return bericht


@router.get("/export/lehrkraefte", response_class=PlainTextResponse)
def export_lehrkraefte(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["typ", "nachname", "vorname", "email", "lehrverpflichtung", "qualifikationen"])
    for lk in db.scalars(select(Lehrkraft).where(Lehrkraft.school_id == school_id)).all():
        w.writerow(["lehrkraft", lk.nachname, lk.vorname, lk.email, lk.lehrverpflichtung,
                    ";".join(lk.qualifikationen or [])])
    return out.getvalue()
