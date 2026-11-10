"""Administration & Mehrmandantenfähigkeit (Abschnitt 4.9, FD-901..FD-905)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Role, audit, get_current_user, require_roles
from ..db import get_db
from ..deps import SchoolDep
from ..models import (
    Abwesenheit, AboToken, AuditLog, Gegenstand, Klasse, Lehrkraft, Notification, PlanOperation,
    Planversion, Pruefungstermin, Ressourcenpool, Raum, Schule, Schuljahr, Semester, SolverRun, Stunde,
    Unterrichtsveranstaltung, User, Vertretung,
)
from ..schemas import UserIn, UserOut

router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN_ROLES = [Role.ADMIN, Role.SYSADMIN]


@router.post("/benutzer", response_model=UserOut, dependencies=[Depends(require_roles(*ADMIN_ROLES))])
def create_user(body: UserIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    school_id = body.school_id if user.role == Role.SYSADMIN.value else user.school_id
    if not school_id:
        raise HTTPException(400, "school_id erforderlich")
    existing = db.scalar(select(User).where(User.school_id == school_id, User.email == body.email))
    if existing:
        raise HTTPException(409, "Benutzer mit dieser E-Mail existiert bereits im Mandanten")
    u = User(school_id=school_id, email=body.email, name=body.name, role=body.role,
             lehrkraft_id=body.lehrkraft_id, klasse_id=body.klasse_id)
    db.add(u)
    audit(db, user, "benutzer_anlegen", "benutzer", {"email": body.email, "role": body.role})
    db.commit()
    db.refresh(u)
    return u


@router.get("/benutzer", response_model=list[UserOut])
def list_users(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
               user: User = Depends(require_roles(*ADMIN_ROLES))):
    q = select(User)
    q = q.where(User.school_id == school_id) if user.role != Role.SYSADMIN.value else q
    return db.scalars(q).all()


@router.patch("/benutzer/{uid}/rolle", response_model=UserOut,
              dependencies=[Depends(require_roles(*ADMIN_ROLES))])
def set_role(uid: int, rolle: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Benutzer nicht gefunden")
    if user.role != Role.SYSADMIN.value and u.school_id != user.school_id:
        raise HTTPException(403, "Fremder Mandant")
    u.role = rolle
    audit(db, user, "rolle_geaendert", "benutzer", {"uid": uid, "rolle": rolle})
    db.commit()
    db.refresh(u)
    return u


@router.get("/audit")
def get_audit(limit: int = 200, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
              user: User = Depends(require_roles(*ADMIN_ROLES))):
    """FD-904: Audit-Log aller sicherheitsrelevanten Operationen."""
    q = select(AuditLog).where(AuditLog.school_id == school_id).order_by(AuditLog.id.desc()).limit(limit)
    return [{"id": a.id, "user_id": a.user_id, "aktion": a.aktion, "objekt": a.objekt,
             "details": a.details, "zeitpunkt": a.zeitpunkt, "ip": a.ip}
            for a in db.scalars(q).all()]


@router.get("/mandant-export")
def mandant_export(school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
                   user: User = Depends(require_roles(Role.ADMIN, Role.SYSADMIN, Role.SCHULLEITUNG))):
    """FD-905: Datenexport des gesamten Mandanten (Offboarding, DSGVO)."""
    schule = db.get(Schule, school_id)
    if not schule:
        raise HTTPException(404, "Mandant nicht gefunden")
    dump = {"schule": {"id": schule.id, "name": schule.name, "schulart": schule.schulart,
                       "config": schule.config},
            "schuljahre": [{"id": s.id, "bezeichnung": s.bezeichnung, "start": str(s.start), "ende": str(s.ende)}
                           for s in db.scalars(select(Schuljahr).where(Schuljahr.school_id == school_id))],
            "klassen": [{"id": k.id, "name": k.name} for k in db.scalars(select(Klasse).where(Klasse.school_id == school_id))],
            "lehrkraefte": [{"id": t.id, "email": t.email, "nachname": t.nachname}
                            for t in db.scalars(select(Lehrkraft).where(Lehrkraft.school_id == school_id))],
            "raeume": [{"id": r.id, "name": r.name} for r in db.scalars(select(Raum).where(Raum.school_id == school_id))],
            "planversionen": [{"id": v.id, "name": v.name, "status": v.status, "score": v.score}
                              for v in db.scalars(select(Planversion).where(Planversion.school_id == school_id))]}
    audit(db, user, "mandant_export", "schule", {"school_id": school_id})
    return dump
