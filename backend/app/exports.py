"""Exportschnittstellen (TU-60, FD-704): iCalendar, CSV, eingebettbares HTML-Widget, PDF."""
from __future__ import annotations

import csv
import html
import io
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AboToken, Gegenstand, Klasse, Lehrkraft, Planversion, Raum, Schule, Semester, Stunde,
    Unterrichtsveranstaltung,
)

TAGNAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _published_version(db: Session, school_id: int, schuljahr_id: int | None = None) -> Planversion | None:
    q = select(Planversion).where(Planversion.school_id == school_id,
                                  Planversion.status == "veroeffentlicht")
    if schuljahr_id:
        q = q.where(Planversion.schuljahr_id == schuljahr_id)
    return db.scalars(q.order_by(Planversion.veroeffentlicht_at.desc()).limit(1)).first()


def _stunden(db: Session, version: Planversion, art: str, ziel_id: int):
    q = select(Stunde).where(Stunde.planversion_id == version.id)
    if art == "klasse":
        q = q.join(Unterrichtsveranstaltung,
                   Unterrichtsveranstaltung.id == Stunde.veranstaltung_id).where(
            Unterrichtsveranstaltung.klasse_id == ziel_id)
    elif art == "lehrkraft":
        q = q.where(Stunde.lehrkraft_id == ziel_id)
    elif art == "raum":
        q = q.where(Stunde.raum_id == ziel_id)
    return db.scalars(q).all()


def _semester_start(db: Session, version: Planversion) -> date:
    sem = db.scalar(select(Semester).where(Semester.schuljahr_id == version.schuljahr_id))
    return sem.start if sem else date.today()


def _slot_time(cfg: dict, slot: int) -> tuple[str, str]:
    from datetime import datetime as dt
    start = dt.strptime(cfg.get("erster_slot", "08:00"), "%H:%M")
    dauer = cfg.get("slot_dauer_min", 45)
    pausen = {p["nach_slot"]: p["dauer_min"] for p in cfg.get("pausen", [])}
    minutes = slot * dauer + sum(d for s, d in pausen.items() if s < slot)
    s = start + timedelta(minutes=minutes)
    e = s + timedelta(minutes=dauer)
    return s.strftime("%H:%M"), e.strftime("%H:%M")


def build_rows(db: Session, school_id: int, art: str, ziel_id: int,
               version: Planversion | None = None) -> list[dict]:
    version = version or _published_version(db, school_id)
    if not version:
        return []
    schule = db.get(Schule, school_id)
    cfg = dict(Schule.DEFAULT_CONFIG)
    cfg.update(schule.config or {})
    sem_start = _semester_start(db, version)
    rows = []
    for s in _stunden(db, version, art, ziel_id):
        v = db.get(Unterrichtsveranstaltung, s.veranstaltung_id)
        g = db.get(Gegenstand, v.gegenstand_id) if v else None
        r = db.get(Raum, s.raum_id)
        lk = db.get(Lehrkraft, s.lehrkraft_id)
        k = db.get(Klasse, v.klasse_id) if v else None
        # konkretes Datum der ersten Woche (Semesterbeginn + Wochentag)
        datum = sem_start + timedelta(days=s.wochentag)
        t1, t2 = _slot_time(cfg, s.slot)
        rows.append({
            "datum": datum.isoformat(), "wochentag": TAGNAMES[s.wochentag], "slot": s.slot,
            "von": t1, "bis": t2, "fach": g.code if g else "?",
            "fach_name": g.name if g else "?", "klasse": k.name if k else "?",
            "raum": r.name if r else "?", "lehrkraft": f"{lk.nachname} {lk.vorname}" if lk else "?",
            "zustand": s.zustand, "laenge": s.laenge,
        })
    rows.sort(key=lambda r: (r["wochentag"], r["slot"]))
    return rows


def to_ics(db: Session, school_id: int, art: str, ziel_id: int, titel: str) -> str:
    rows = build_rows(db, school_id, art, ziel_id)
    version = _published_version(db, school_id)
    cfg = dict(Schule.DEFAULT_CONFIG)
    schule = db.get(Schule, school_id)
    cfg.update(schule.config or {})
    sem_start = _semester_start(db, version) if version else date.today()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SPPS//Stundenplan//DE",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{titel}"]
    byday = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    for r in rows:
        d = date.fromisoformat(r["datum"])
        uid = f"{art}-{ziel_id}-{r['wochentag']}-{r['slot']}@spps"
        summary = f"{r['fach']} ({r['klasse']}) – {r['raum']}, {r['lehrkraft']}"
        if r["zustand"] != "geplant":
            summary = f"[{r['zustand'].upper()}] {summary}"
        lines += [
            "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
            f"DTSTART:{d:%Y%m%d}T{r['von'].replace(':', '')}00",
            f"DTEND:{d:%Y%m%d}T{r['bis'].replace(':', '')}00",
            f"SUMMARY:{summary}",
            f"RRULE:FREQ=WEEKLY;BYDAY={byday[TAGNAMES.index(r['wochentag'])]}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def to_csv(db: Session, school_id: int, art: str, ziel_id: int) -> str:
    rows = build_rows(db, school_id, art, ziel_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["datum", "wochentag", "von", "bis", "fach", "fach_name", "klasse", "raum",
                "lehrkraft", "zustand"])
    for r in rows:
        w.writerow([r["datum"], r["wochentag"], r["von"], r["bis"], r["fach"], r["fach_name"],
                    r["klasse"], r["raum"], r["lehrkraft"], r["zustand"]])
    return out.getvalue()


def to_html_widget(db: Session, school_id: int, art: str, ziel_id: int, version: Planversion | None = None) -> str:
    """FD-704: einbettbares HTML-Widget für Schulwebseite / digitale Tafeln."""
    version = version or _published_version(db, school_id)
    rows = build_rows(db, school_id, art, ziel_id, version)
    schule = db.get(Schule, school_id)
    cfg = dict(Schule.DEFAULT_CONFIG)
    cfg.update(schule.config or {})
    ziel = ""
    if art == "klasse":
        ziel = db.get(Klasse, ziel_id).name if db.get(Klasse, ziel_id) else str(ziel_id)
    elif art == "lehrkraft":
        lk = db.get(Lehrkraft, ziel_id)
        ziel = f"{lk.nachname} {lk.vorname}" if lk else str(ziel_id)
    elif art == "raum":
        ziel = db.get(Raum, ziel_id).name if db.get(Raum, ziel_id) else str(ziel_id)
    body_rows = "".join(
        f"<tr><td>{html.escape(r['wochentag'])}</td><td>{r['von']}–{r['bis']}</td>"
        f"<td>{html.escape(r['fach'])}</td><td>{html.escape(r['klasse'])}</td>"
        f"<td>{html.escape(r['raum'])}</td><td>{html.escape(r['lehrkraft'])}</td>"
        f"<td class='zustand-{html.escape(r['zustand'])}'>{html.escape(r['zustand'])}</td></tr>"
        for r in rows)
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SPPS Plan – {html.escape(ziel)}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:1em;color:#111}}
h1{{font-size:1.1em}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:4px 8px;text-align:left;font-size:.9em}}
.zustand-vertreten{{background:#fff3cd}}.zustand-abgesagt{{background:#f8d7da}}
.zustand-frei{{background:#e2e3e5}}.meta{{font-size:.8em;color:#666}}
</style></head><body>
<h1>Stundenplan: {html.escape(ziel)} – {html.escape(schule.name if schule else '')}</h1>
<p class="meta">Stand: {html.escape(str(version.veroeffentlicht_at) if version and version.veroeffentlicht_at else 'Entwurf')}
· SPPS Embed-Widget</p>
<table><thead><tr><th>Tag</th><th>Zeit</th><th>Fach</th><th>Klasse</th><th>Raum</th><th>Lehrkraft</th><th>Status</th></tr></thead>
<tbody>{body_rows}</tbody></table>
</body></html>"""


def to_pdf(db: Session, school_id: int, art: str, ziel_id: int) -> bytes:
    """FD-704: druckoptimiertes PDF (Wochenraster) via reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    version = _published_version(db, school_id)
    schule = db.get(Schule, school_id)
    cfg = dict(Schule.DEFAULT_CONFIG)
    cfg.update(schule.config or {})
    slots = cfg["slots_pro_tag"]
    tage = cfg["tage_pro_woche"]

    # Raster aufbauen
    grid: dict[tuple[int, int], list[str]] = {}
    ver_by_id = {}
    for s in _stunden(db, version, art, ziel_id) if version else []:
        v = db.get(Unterrichtsveranstaltung, s.veranstaltung_id)
        g = db.get(Gegenstand, v.gegenstand_id) if v else None
        r = db.get(Raum, s.raum_id)
        lk = db.get(Lehrkraft, s.lehrkraft_id)
        k = db.get(Klasse, v.klasse_id) if v else None
        label = f"{g.code if g else '?'} {r.name if r else ''}"
        if art == "klasse":
            label += f" / {lk.nachname}" if lk else ""
        else:
            label += f" / {k.name}" if k else ""
        if s.zustand != "geplant":
            label = f"[{s.zustand}] {label}"
        for sl in range(s.slot, s.slot + s.laenge):
            grid.setdefault((s.wochentag, sl), []).append(label)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    w, h = landscape(A4)
    c.setFont("Helvetica-Bold", 14)
    ziel = ""
    if art == "klasse" and db.get(Klasse, ziel_id):
        ziel = db.get(Klasse, ziel_id).name
    elif art == "lehrkraft" and db.get(Lehrkraft, ziel_id):
        lk = db.get(Lehrkraft, ziel_id)
        ziel = f"{lk.nachname} {lk.vorname}"
    elif art == "raum" and db.get(Raum, ziel_id):
        ziel = db.get(Raum, ziel_id).name
    c.drawString(1 * cm, h - 1 * cm, f"Stundenplan {ziel} – {schule.name if schule else ''}")
    c.setFont("Helvetica", 8)
    top = h - 1.8 * cm
    left = 2.2 * cm
    col_w = (w - left - 1 * cm) / tage
    row_h = (top - 1.2 * cm) / slots
    for d in range(tage):
        c.drawString(left + d * col_w + 2, top + 4, TAGNAMES[d])
    for sl in range(slots):
        t1, _ = _slot_time(cfg, sl)
        c.drawString(0.4 * cm, top - (sl + 0.5) * row_h, t1)
        c.setStrokeColor(colors.lightgrey)
        c.line(left, top - (sl + 1) * row_h, w - 1 * cm, top - (sl + 1) * row_h)
    for d in range(tage + 1):
        c.line(left + d * col_w, top - slots * row_h, left + d * col_w, top)
    c.setFont("Helvetica", 6.5)
    for (d, sl), labels in grid.items():
        c.drawString(left + d * col_w + 2, top - (sl + 0.75) * row_h, " / ".join(labels)[:38])
    c.showPage()
    c.save()
    return buf.getvalue()


def resolve_abo(db: Session, token: str) -> AboToken | None:
    return db.scalar(select(AboToken).where(AboToken.token == token))
