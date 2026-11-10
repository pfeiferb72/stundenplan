"""Veröffentlichung & Ansichten (Abschnitt 4.7/4.8, FD-701..706, FD-801) + Exports (TU-60/FD-704)."""
from __future__ import annotations

import secrets
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Role, audit, get_current_user, get_optional_user, require_roles
from ..db import get_db
from ..deps import SchoolDep
from ..exports import build_rows, resolve_abo, to_csv, to_html_widget, to_ics, to_pdf
from ..models import (
    AboToken, Gegenstand, Klasse, Lehrkraft, Notification, Planversion, PlanStatus, Raum, Stunde,
    Unterrichtsveranstaltung, User,
)

router = APIRouter(prefix="/publish", tags=["publish"])
router_export = APIRouter(prefix="/export", tags=["export"])

WORKFLOW = {
    "entwurf": ["pruefung"],
    "pruefung": ["entwurf", "freigabe"],
    "freigabe": ["pruefung", "veroeffentlicht"],
    "veroeffentlicht": [],
}


@router.post("/versionen/{vid}/status", dependencies=[Depends(require_roles(Role.PLANER, Role.ADMIN, Role.SYSADMIN, Role.SCHULLEITUNG))])
def set_status(vid: int, ziel: str, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """FD-702: Entwurf → interne Prüfung → Freigabe durch Schulleitung → Veröffentlichung."""
    v = db.get(Planversion, vid)
    if not v or v.school_id != school_id:
        raise HTTPException(404, "Planversion nicht gefunden")
    if ziel not in WORKFLOW.get(v.status, []):
        raise HTTPException(409, f"Ungültiger Workflow-Schritt {v.status} → {ziel}")
    if ziel == "freigabe" and user.role not in (Role.SCHULLEITUNG.value, Role.ADMIN.value, Role.SYSADMIN.value):
        raise HTTPException(403, "Freigabe erfordert Schulleitung (FD-702)")
    if ziel == "veroeffentlicht":
        if v.status != "freigabe":
            raise HTTPException(409, "Veröffentlichung nur aus Status 'freigabe'")
        if user.role not in (Role.SCHULLEITUNG.value, Role.ADMIN.value, Role.SYSADMIN.value):
            raise HTTPException(403, "Veröffentlichung erfordert Schulleitung (FD-702)")
        # FD-703: nur eine veröffentlichte Version je Schuljahr aktiv
        for other in db.scalars(select(Planversion).where(
                Planversion.school_id == school_id, Planversion.schuljahr_id == v.schuljahr_id,
                Planversion.status == "veroeffentlicht", Planversion.id != v.id)).all():
            other.status = PlanStatus.FREIGABE.value
        v.status = ziel
        v.veroeffentlicht_at = datetime.utcnow()
        v.freigegeben_von = user.id
        # FD-801: In-App-Benachrichtigung an alle Mandanten-User
        for u in db.scalars(select(User).where(User.school_id == school_id, User.aktiv.is_(True))).all():
            db.add(Notification(school_id=school_id, user_id=u.id, typ="plan_veroeffentlicht",
                                titel=f"Neuer Plan veröffentlicht: {v.name}",
                                text=f"Planversion {v.name} wurde freigegeben und veröffentlicht."))
    else:
        v.status = ziel
    audit(db, user, "plan_status", "planversion", {"id": vid, "von": v.status, "nach": ziel})
    db.commit()
    db.refresh(v)
    return v


@router.get("/versionen", response_model=list[dict])
def list_published(schuljahr_id: int | None = None, school_id: int = Depends(SchoolDep),
                   db: Session = Depends(get_db)):
    q = select(Planversion).where(Planversion.school_id == school_id)
    if schuljahr_id:
        q = q.where(Planversion.schuljahr_id == schuljahr_id)
    out = []
    for v in db.scalars(q.order_by(Planversion.id.desc())).all():
        out.append({"id": v.id, "name": v.name, "status": v.status, "score": v.score,
                    "veroeffentlicht_at": v.veroeffentlicht_at})
    return out


def _ansicht(db: Session, school_id: int, art: str, ziel_id: int, version_id: int | None):
    if version_id:
        version = db.get(Planversion, version_id)
        if not version or version.school_id != school_id:
            raise HTTPException(404, "Version nicht gefunden")
    else:
        version = db.scalar(select(Planversion).where(
            Planversion.school_id == school_id, Planversion.status == "veroeffentlicht"
        ).order_by(Planversion.veroeffentlicht_at.desc().nullslast()).limit(1))
        if not version:
            raise HTTPException(404, "Noch kein Plan veröffentlicht")
    q = select(Stunde).where(Stunde.planversion_id == version.id)
    if art == "klasse":
        q = q.join(Unterrichtsveranstaltung).where(Unterrichtsveranstaltung.klasse_id == ziel_id)
    elif art == "lehrkraft":
        q = q.where(Stunde.lehrkraft_id == ziel_id)
    elif art == "raum":
        q = q.where(Stunde.raum_id == ziel_id)
    elif art == "tag":
        q = q.where(Stunde.wochentag == ziel_id)
    else:
        raise HTTPException(400, "art muss klasse|lehrer|raum|tag sein")
    cells = {}
    for s in db.scalars(q).all():
        v = db.get(Unterrichtsveranstaltung, s.veranstaltung_id)
        g = db.get(Gegenstand, v.gegenstand_id) if v else None
        r = db.get(Raum, s.raum_id)
        lk = db.get(Lehrkraft, s.lehrkraft_id)
        k = db.get(Klasse, v.klasse_id) if v else None
        for sl in range(s.slot, s.slot + s.laenge):
            cells.setdefault((s.wochentag, sl), []).append({
                "stunde_id": s.id, "fach": g.code if g else "?",
                "klasse": k.name if k else "?", "raum": r.name if r else "?",
                "lehrkraft": f"{lk.nachname}" if lk else "?", "zustand": s.zustand,
            })
    return {"version_id": version.id, "status": version.status, "art": art, "ziel_id": ziel_id, "zellen": [
        {"wochentag": d, "slot": sl, "eintraege": e} for (d, sl), e in sorted(cells.items())]}


@router.get("/ansicht")
def ansicht(art: str, ziel_id: int, version_id: int | None = None, school_id: int = Depends(SchoolDep),
            db: Session = Depends(get_db)):
    """FD-701: Klassen-/Lehrer-/Raumplan, Tagesübersicht."""
    return _ansicht(db, school_id, art, ziel_id, version_id)


@router.get("/aenderungen/{vid}")
def aenderungen(vid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    """FD-706: Was hat sich seit der letzten Veröffentlichung geändert?"""
    v = db.get(Planversion, vid)
    if not v or v.school_id != school_id:
        raise HTTPException(404, "Version nicht gefunden")
    last_pub = db.scalar(select(Planversion).where(
        Planversion.school_id == school_id, Planversion.schuljahr_id == v.schuljahr_id,
        Planversion.status == "veroeffentlicht", Planversion.id != v.id
    ).order_by(Planversion.veroeffentlicht_at.desc().nullslast()).limit(1))
    if not last_pub:
        return {"basis": None, "hinzugefuegt": [], "entfernt": [], "verschoben": []}
    def keymap(ver):
        return {(s.veranstaltung_id, s.wochentag, s.slot): s for s in db.scalars(
            select(Stunde).where(Stunde.planversion_id == ver.id)).all()}
    a, b = keymap(last_pub), keymap(v)
    hinzu = [k for k in b if k not in a]
    entf = [k for k in a if k not in b]
    return {"basis": last_pub.id,
            "hinzugefuegt": [{"v": k[0], "tag": k[1], "slot": k[2]} for k in hinzu],
            "entfernt": [{"v": k[0], "tag": k[1], "slot": k[2]} for k in entf]}


@router.post("/abos", dependencies=[Depends(require_roles(Role.PLANER, Role.ADMIN, Role.SYSADMIN, Role.SCHULLEITUNG, Role.LEHRKRAFT, Role.KLASSENKURATOR))])
def create_abo(art: str, ziel_id: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """FD-705: Kalender-Abo je Klasse/Lehrkraft."""
    token = secrets.token_urlsafe(32)
    db.add(AboToken(school_id=school_id, token=token, art=art, ziel_id=ziel_id, user_id=user.id))
    db.commit()
    return {"token": token, "ics_url": f"/api/export/ics?token={token}"}


@router.get("/notifications")
def list_notifications(nur_ungelesen: bool = False, school_id: int = Depends(SchoolDep),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(Notification).where(Notification.school_id == school_id, Notification.user_id == user.id)
    if nur_ungelesen:
        q = q.where(Notification.gelesen.is_(False))
    return [{"id": n.id, "typ": n.typ, "titel": n.titel, "text": n.text, "gelesen": n.gelesen,
             "zeitpunkt": n.zeitpunkt} for n in db.scalars(q.order_by(Notification.id.desc())).all()]


@router.post("/notifications/{nid}/gelesen")
def mark_read(nid: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id or n.school_id != school_id:
        raise HTTPException(404, "Notification nicht gefunden")
    n.gelesen = True
    db.commit()
    return {"ok": True}


# --- Exports (TU-60, FD-704) ---

def _resolve(db: Session, token: str | None, art: str, ziel_id: int, user: User | None):
    school_id = None
    if token:
        abo = resolve_abo(db, token)
        if not abo or abo.art != art or abo.ziel_id != ziel_id:
            raise HTTPException(403, "Ungültiges Abo-Token")
        school_id = abo.school_id
    elif user:
        school_id = user.school_id
    else:
        raise HTTPException(401, "Authentifizierung oder token erforderlich")
    return school_id


@router_export.get("/ics")
def export_ics(art: str, ziel_id: int, token: str | None = None, db: Session = Depends(get_db),
               user: User | None = Depends(get_optional_user)):
    school_id = _resolve(db, token, art, ziel_id, user)
    titel = f"{art}-{ziel_id}"
    return PlainTextResponse(to_ics(db, school_id, art, ziel_id, titel),
                             media_type="text/calendar",
                             headers={"Content-Disposition": f"attachment; filename=plan-{art}-{ziel_id}.ics"})


@router_export.get("/csv")
def export_csv(art: str, ziel_id: int, token: str | None = None, db: Session = Depends(get_db),
               user: User | None = Depends(get_optional_user)):
    school_id = _resolve(db, token, art, ziel_id, user)
    return PlainTextResponse(to_csv(db, school_id, art, ziel_id), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=plan-{art}-{ziel_id}.csv"})


@router_export.get("/html")
def export_html(art: str, ziel_id: int, token: str | None = None, db: Session = Depends(get_db),
                user: User | None = Depends(get_optional_user)):
    school_id = _resolve(db, token, art, ziel_id, user)
    return HTMLResponse(to_html_widget(db, school_id, art, ziel_id))


@router_export.get("/widget.js")
def export_widget_js(art: str, ziel_id: int, token: str):
    """Einbettbares Widget als JS-Snippet für Schulwebseite/digitale Tafeln (SS-30)."""
    return PlainTextResponse(
        f'<div id="spps-widget-{art}-{ziel_id}"></div>\n'
        f'<script>fetch("/api/export/html?art={art}&ziel_id={ziel_id}&token={token}")'
        f'.then(r=>r.text()).then(h=>document.getElementById("spps-widget-{art}-{ziel_id}").innerHTML=h);</script>',
        media_type="application/javascript")


@router_export.get("/pdf")
def export_pdf(art: str, ziel_id: int, token: str | None = None, db: Session = Depends(get_db),
               user: User | None = Depends(get_optional_user)):
    school_id = _resolve(db, token, art, ziel_id, user)
    return Response(content=to_pdf(db, school_id, art, ziel_id), media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=plan-{art}-{ziel_id}.pdf"})


@router_export.get("/plan.json")
def export_plan_json(version_id: int, school_id: int = Depends(SchoolDep), db: Session = Depends(get_db)):
    """TU-70: dokumentierte, versionierte API für Drittsysteme."""
    v = db.get(Planversion, version_id)
    if not v or v.school_id != school_id:
        raise HTTPException(404, "Version nicht gefunden")
    stunden = db.scalars(select(Stunde).where(Stunde.planversion_id == v.id)).all()
    out = []
    for s in stunden:
        ver = db.get(Unterrichtsveranstaltung, s.veranstaltung_id)
        g = db.get(Gegenstand, ver.gegenstand_id) if ver else None
        out.append({"stunde_id": s.id, "veranstaltung_id": s.veranstaltung_id,
                    "klasse_id": ver.klasse_id if ver else None,
                    "fach": g.code if g else None, "wochentag": s.wochentag, "slot": s.slot,
                    "laenge": s.laenge, "raum_id": s.raum_id, "lehrkraft_id": s.lehrkraft_id,
                    "zustand": s.zustand})
    return {"planversion_id": v.id, "status": v.status, "score": v.score, "stunden": out}
