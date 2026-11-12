"""Demo-Mandant für Entwicklung und Tests (Referenzszenario QS-102).

Interne Konsistenz (FD-204): Summe Wochenstunden aller Veranstaltungen == Summe Lehrverpflichtungen.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Gegenstand, Klasse, Lehrkraft, Planversion, Ressourcenpool, Raum, Schule, Schuljahr, Semester,
    Stundentafel, User, Unterrichtsveranstaltung,
)


def seed_demo(db: Session) -> dict:
    schule = Schule(name="BHAK Musterstadt", schulart="BHS")
    db.add(schule)
    db.flush()
    sid = schule.id

    sj = Schuljahr(school_id=sid, bezeichnung="2025/26", start=date(2025, 9, 1), ende=date(2026, 6, 30))
    db.add(sj)
    db.flush()
    db.add(Semester(schuljahr_id=sj.id, bezeichnung="1. Semester", start=date(2025, 9, 1), ende=date(2026, 1, 31)))
    db.add(Semester(schuljahr_id=sj.id, bezeichnung="2. Semester", start=date(2026, 2, 9), ende=date(2026, 6, 30)))

    pool = Ressourcenpool(school_id=sid, name="Sportstätten")
    db.add(pool)
    db.flush()
    raeume = {}
    for name, kap, fach, aust in [
        ("1A-Raum", 30, False, []), ("1B-Raum", 30, False, []),
        ("2A-Raum", 30, False, []), ("2B-Raum", 30, False, []),
        ("EDV-Labor", 30, True, ["PC", "Beamer"]), ("Turnsaal", 60, True, ["Matten"]),
    ]:
        r = Raum(school_id=sid, name=name, kapazitaet=kap, fachraum=fach, ausstattung=aust,
                 ressourcenpool_id=pool.id if name == "Turnsaal" else None)
        db.add(r)
        db.flush()
        raeume[name] = r.id

    gegenstaende = {}
    for code, name, fach, aust in [
        ("D", "Deutsch", False, []), ("E", "Englisch", False, []), ("AM", "Angewandte Mathematik", False, []),
        ("POS", "Programmierung", True, ["PC"]), ("DBI", "Datenbanken", True, ["PC"]),
        ("BWM", "Betriebswirtschaft", False, []), ("SP", "Sport", True, ["Matten"]),
    ]:
        g = Gegenstand(school_id=sid, code=code, name=name, schulart="BHS",
                       benoetigt_fachraum=fach, benoetigte_ausstattung=aust)
        db.add(g)
        db.flush()
        gegenstaende[code] = g.id

    # Summe Soll = 68 == Summe Wochenstunden der 4 Klassen (FD-204 exakt erfüllbar)
    lehrkraefte = {}
    for nachname, vorname, email, soll, quals, freie_tage in [
        ("Huber", "Anna", "huber@schule.at", 20, ["D", "E"], [4]),
        ("Steiner", "Clara", "steiner@schule.at", 4, ["D"], []),
        ("Berger", "Elena", "berger@schule.at", 12, ["BWM", "E"], [0]),
        ("Wagner", "David", "wagner@schule.at", 8, ["DBI", "POS"], []),
        ("Maier", "Ben", "maier@schule.at", 18, ["AM", "POS"], []),
        ("Fuchs", "Felix", "fuchs@schule.at", 6, ["SP"], []),
    ]:
        lk = Lehrkraft(school_id=sid, nachname=nachname, vorname=vorname, email=email,
                       lehrverpflichtung=soll, qualifikationen=quals, unterrichtsfreie_tage=freie_tage)
        db.add(lk)
        db.flush()
        lehrkraefte[email] = lk.id

    klassen = {}
    for name, jahrgang, stamm in [("1AH", 1, "1A-Raum"), ("1BH", 1, "1B-Raum"),
                                  ("2AH", 2, "2A-Raum"), ("2BH", 2, "2B-Raum")]:
        k = Klasse(school_id=sid, schuljahr_id=sj.id, name=name, jahrgang=jahrgang,
                   schuelerzahl=28, stammraum_id=raeume[stamm])
        db.add(k)
        db.flush()
        klassen[name] = k.id

    tafel = [
        (1, "D", 4, "2+1+1"), (1, "E", 3, "2+1"), (1, "AM", 3, "2+1"), (1, "POS", 2, "2"),
        (1, "DBI", 2, "2"), (1, "BWM", 2, "1+1"), (1, "SP", 2, "2"),
        (2, "D", 3, "2+1"), (2, "E", 3, "2+1"), (2, "AM", 2, "2"), (2, "POS", 2, "2"),
        (2, "DBI", 2, "2"), (2, "BWM", 3, "2+1"), (2, "SP", 1, "1"),
    ]
    for jahrgang, code, wh, auf in tafel:
        db.add(Stundentafel(school_id=sid, schulart="BHS", jahrgang=jahrgang,
                            gegenstand_id=gegenstaende[code], wochenstunden=wh, aufteilung=auf))
    db.flush()

    # FD-202: Veranstaltungen aus Stundentafel erzeugen
    for kname, kid in klassen.items():
        k = db.get(Klasse, kid)
        for st in db.scalars(select(Stundentafel).where(
                Stundentafel.school_id == sid, Stundentafel.jahrgang == k.jahrgang)).all():
            db.add(Unterrichtsveranstaltung(
                school_id=sid, schuljahr_id=sj.id, klasse_id=kid, gegenstand_id=st.gegenstand_id,
                wochenstunden=st.wochenstunden, aufteilung=st.aufteilung, rhythmus=st.rhythmus))
    db.flush()

    version = Planversion(school_id=sid, schuljahr_id=sj.id, name="Arbeitsstand 1", status="entwurf")
    db.add(version)
    db.flush()

    users = [
        ("admin@schule.at", "Admin Anita", "admin", None, None),
        ("leitung@schule.at", "Leitung Leo", "schulleitung", None, None),
        ("planer@schule.at", "Planer Pia", "planer", None, None),
        ("huber@schule.at", "Huber Anna", "lehrkraft", lehrkraefte["huber@schule.at"], None),
        ("1ah@schule.at", "Kurator 1AH", "klassenkurator", None, klassen["1AH"]),
    ]
    for email, name, role, lid, kid in users:
        db.add(User(school_id=sid, email=email, name=name, role=role, lehrkraft_id=lid, klasse_id=kid))
    db.commit()
    return {
        "school_id": sid, "schuljahr_id": sj.id, "version_id": version.id,
        "klassen": klassen, "lehrkraefte": lehrkraefte, "raeume": raeume,
        "gegenstaende": gegenstaende,
    }
