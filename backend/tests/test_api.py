"""Integrationstests der REST-API (QS-103): Auth, Stammdaten, Plan, Solver, Vertretung,
Veröffentlichung, Exporte, Prüfungen, Admin – inkl. RBAC (FD-901) und Mandantenschutz (FD-902)."""
import time


def login(client, email):
    r = client.post("/api/auth/dev-login", json={"email": email})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- Auth / RBAC ---

def test_dev_login_und_me(client, seeded):
    h = login(client, "planer@schule.at")
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 200
    assert r.json()["role"] == "planer"
    assert r.json()["school_id"] == seeded["school_id"]


def test_rbac_lehrkraft_darf_nicht_loeschen(client, seeded):
    h = login(client, "huber@schule.at")
    r = client.delete(f"/api/stammdaten/klassen/{seeded['klassen']['1AH']}", headers=h)
    assert r.status_code == 403


def test_mandantenschutz(client, db, seeded):
    from app.models import Schule, User
    andere = Schule(name="Andere Schule", schulart="VS")
    db.add(andere)
    db.flush()
    db.add(User(school_id=andere.id, email="fremd@schule.at", name="Fremd", role="planer"))
    db.commit()
    h = login(client, "planer@schule.at")
    r = client.get("/api/stammdaten/klassen", headers=h, params={"school_id": andere.id})
    assert r.status_code == 403
    r2 = client.get("/api/stammdaten/klassen", headers=h)
    assert r2.status_code == 200


# --- Stammdaten ---

def test_stammdaten_crud_und_generierung(client, seeded, auth_headers):
    sid = seeded["school_id"]
    r = client.get("/api/stammdaten/lehrkraefte", headers=auth_headers)
    assert r.status_code == 200 and len(r.json()) == 6
    r = client.get("/api/stammdaten/raeume", headers=auth_headers)
    assert len(r.json()) == 6
    # neue Klasse anlegen
    r = client.post("/api/stammdaten/klassen", headers=auth_headers, json={
        "schuljahr_id": seeded["schuljahr_id"], "name": "3AH", "jahrgang": 3, "schuelerzahl": 24})
    assert r.status_code == 200
    # FD-202: Veranstaltungen generieren (idempotent)
    r = client.post(f"/api/veranstaltungen/generieren/{seeded['schuljahr_id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["erzeugt"] == 0  # Seed hat schon erzeugt
    r = client.get("/api/veranstaltungen", headers=auth_headers,
                   params={"schuljahr_id": seeded["schuljahr_id"]})
    assert len(r.json()) == 4 * 7  # 4 Klassen × 7 Fächer


def test_smls_import_mit_konfliktbericht(client, seeded, auth_headers):
    import io
    csv_data = (
        "typ,nachname,vorname,email,lehrverpflichtung,qualifikationen\n"
        "lehrkraft,Neu,Nadia,neu@schule.at,10,D;E\n"
        "lehrkraft,Huber,Anna,huber@schule.at,21,D;E\n"
        "klasse,9Z,9,30,99999\n"  # ungültige schuljahr_id -> Konflikt
    )
    r = client.post("/api/stammdaten/import/smls", headers=auth_headers,
                    files={"file": ("smls.csv", io.BytesIO(csv_data.encode()), "text/csv")})
    assert r.status_code == 200
    bericht = r.json()
    assert bericht["importiert"] == 1 and bericht["aktualisiert"] == 1
    assert any("ungültig" in k["grund"] for k in bericht["konflikte"])
    r = client.get("/api/stammdaten/lehrkraefte", headers=auth_headers)
    huber = [t for t in r.json() if t["email"] == "huber@schule.at"][0]
    assert huber["lehrverpflichtung"] == 21


# --- Solver (asynchron, abbrechbar) ---

def test_solver_run_async_und_ergebnis(client, seeded, auth_headers):
    r = client.post("/api/plan/solver/runs", headers=auth_headers, json={
        "schuljahr_id": seeded["schuljahr_id"], "zeitbudget_s": 5, "seed": 3})
    assert r.status_code == 200
    run_id = r.json()["id"]
    assert r.json()["status"] in ("pending", "running", "done")
    for _ in range(40):
        r = client.get(f"/api/plan/solver/runs/{run_id}", headers=auth_headers)
        if r.json()["status"] in ("done", "failed", "aborted"):
            break
        time.sleep(0.5)
    run = r.json()
    assert run["status"] == "done", run
    assert run["ergebnis_version_id"]
    # Ergebnis-Version hat 68 Stunden und 0 harte Verletzungen
    r = client.get(f"/api/plan/versionen/{run['ergebnis_version_id']}/validate", headers=auth_headers)
    v = r.json()
    assert v["harte_verletzungen"] == [], v["harte_verletzungen"][:3]
    r = client.get(f"/api/plan/versionen/{run['ergebnis_version_id']}/stunden", headers=auth_headers)
    assert len(r.json()) == 44


def test_solver_abort(client, seeded, auth_headers):
    r = client.post("/api/plan/solver/runs", headers=auth_headers, json={
        "schuljahr_id": seeded["schuljahr_id"], "zeitbudget_s": 60, "seed": 5})
    run_id = r.json()["id"]
    r = client.post(f"/api/plan/solver/runs/{run_id}/abort", headers=auth_headers)
    assert r.status_code == 200
    for _ in range(20):
        r = client.get(f"/api/plan/solver/runs/{run_id}", headers=auth_headers)
        if r.json()["status"] in ("aborted", "done"):
            break
        time.sleep(0.3)
    assert r.json()["status"] == "aborted"


# --- Manuelle Platzierung mit Validierung + Undo (FD-301/FD-307) ---

def test_stunde_anlegen_validierung_und_undo(client, seeded, auth_headers):
    vid = seeded["version_id"]
    r = client.get("/api/veranstaltungen", headers=auth_headers, params={"schuljahr_id": seeded["schuljahr_id"]})
    v0 = r.json()[0]
    kid = seeded["klassen"]["1AH"]
    raum = seeded["raeume"]["1A-Raum"]
    lk = seeded["lehrkraefte"]["huber@schule.at"]
    # gültige Platzierung
    r = client.post(f"/api/plan/versionen/{vid}/stunden", headers=auth_headers, json={
        "veranstaltung_id": v0["id"], "wochentag": 0, "slot": 0, "laenge": 1,
        "raum_id": raum, "lehrkraft_id": lk})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    # kollidierende Platzierung -> 409 (harte Restriktion blockiert)
    r = client.post(f"/api/plan/versionen/{vid}/stunden", headers=auth_headers, json={
        "veranstaltung_id": v0["id"], "wochentag": 0, "slot": 0, "laenge": 1,
        "raum_id": raum, "lehrkraft_id": lk})
    assert r.status_code == 409
    assert "harte_verletzungen" in r.json()["detail"]
    # Undo entfernt die Stunde wieder
    r = client.post(f"/api/plan/versionen/{vid}/undo", headers=auth_headers)
    assert r.status_code == 200
    r = client.get(f"/api/plan/versionen/{vid}/stunden", headers=auth_headers)
    assert all(s["id"] != sid for s in r.json())


# --- Veröffentlichungsworkflow (FD-702/703) ---

def test_veroeffentlichungsworkflow(client, seeded):
    vid = seeded["version_id"]
    h_planer = login(client, "planer@schule.at")
    h_leitung = login(client, "leitung@schule.at")
    # Planer darf nicht direkt veröffentlichen
    r = client.post(f"/api/publish/versionen/{vid}/status", headers=h_planer, params={"ziel": "veroeffentlicht"})
    assert r.status_code == 409
    r = client.post(f"/api/publish/versionen/{vid}/status", headers=h_planer, params={"ziel": "pruefung"})
    assert r.status_code == 200
    # Freigabe nur durch Schulleitung
    r = client.post(f"/api/publish/versionen/{vid}/status", headers=h_planer, params={"ziel": "freigabe"})
    assert r.status_code == 403
    r = client.post(f"/api/publish/versionen/{vid}/status", headers=h_leitung, params={"ziel": "freigabe"})
    assert r.status_code == 200
    r = client.post(f"/api/publish/versionen/{vid}/status", headers=h_leitung, params={"ziel": "veroeffentlicht"})
    assert r.status_code == 200
    assert r.json()["status"] == "veroeffentlicht"
    # Benachrichtigungen wurden erzeugt (FD-801)
    r = client.get("/api/publish/notifications", headers=h_planer)
    assert any(n["typ"] == "plan_veroeffentlicht" for n in r.json())


# --- Ansichten & Exporte (FD-701/704, TU-60) ---

def test_ansicht_und_exporte(client, seeded, auth_headers):
    # Plan veröffentlichen (über Solver-Ergebnis oder direkt Status-Kette)
    vid = seeded["version_id"]
    h_leitung = login(client, "leitung@schule.at")
    for ziel in ["pruefung", "freigabe", "veroeffentlicht"]:
        client.post(f"/api/publish/versionen/{vid}/status", headers=h_leitung, params={"ziel": ziel})
    kid = seeded["klassen"]["1AH"]
    r = client.get("/api/publish/ansicht", headers=auth_headers, params={"art": "klasse", "ziel_id": kid})
    assert r.status_code == 200 and r.json()["status"] == "veroeffentlicht"
    for fmt in ["ics", "csv", "html", "pdf"]:
        r = client.get(f"/api/export/{fmt}", headers=auth_headers, params={"art": "klasse", "ziel_id": kid})
        assert r.status_code == 200, (fmt, r.text[:200])
    assert "BEGIN:VCALENDAR" in client.get(
        "/api/export/ics", headers=auth_headers, params={"art": "klasse", "ziel_id": kid}).text
    # Abo-Token ohne Auth (FD-705)
    r = client.post("/api/publish/abos", headers=auth_headers, params={"art": "klasse", "ziel_id": kid})
    token = r.json()["token"]
    r = client.get("/api/export/ics", params={"art": "klasse", "ziel_id": kid, "token": token})
    assert r.status_code == 200
    r = client.get("/api/export/ics", params={"art": "klasse", "ziel_id": kid, "token": "falsch"})
    assert r.status_code == 403


# --- Vertretungsplanung (FD-501..506) ---

def test_vertretungsworkflow(client, seeded, auth_headers):
    from datetime import date
    # Solver-Ergebnis veröffentlichen, damit es einen Plan gibt
    r = client.post("/api/plan/solver/runs", headers=auth_headers, json={
        "schuljahr_id": seeded["schuljahr_id"], "zeitbudget_s": 5, "seed": 11})
    run_id = r.json()["id"]
    for _ in range(40):
        run = client.get(f"/api/plan/solver/runs/{run_id}", headers=auth_headers).json()
        if run["status"] == "done":
            break
        time.sleep(0.5)
    vid = run["ergebnis_version_id"]
    h_leitung = login(client, "leitung@schule.at")
    for ziel in ["pruefung", "freigabe", "veroeffentlicht"]:
        client.post(f"/api/publish/versionen/{vid}/status", headers=h_leitung, params={"ziel": ziel})
    # Abwesenheit melden (FD-501) – Montag
    datum = date(2025, 9, 1)  # Montag
    lk = seeded["lehrkraefte"]["huber@schule.at"]
    r = client.post("/api/vertretung/abwesenheiten", headers=auth_headers, json={
        "lehrkraft_id": lk, "datum": str(datum), "typ": "krankheit", "grund": "Grippe"})
    assert r.status_code == 200
    aid = r.json()["id"]
    # betroffene Stunden (FD-502)
    r = client.get(f"/api/vertretung/abwesenheiten/{aid}/betroffene", headers=auth_headers)
    assert r.status_code == 200
    n = len(r.json()["stunden"])
    # Vorschläge in einem Schritt (FD-503/505)
    r = client.post(f"/api/vertretung/abwesenheiten/{aid}/vorschlaege", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()["vorschlaege"]) == n
    # Liste + manuelle Anpassung + Veröffentlichung (FD-505/506)
    r = client.get("/api/vertretung/liste", headers=auth_headers, params={"datum": str(datum)})
    assert len(r.json()) == n
    if n:
        v0 = r.json()[0]
        r = client.patch(f"/api/vertretung/{v0['id']}", headers=auth_headers,
                         json={"status": "angepasst", "typ": v0["typ"]})
        assert r.status_code == 200
    r = client.post("/api/vertretung/veroeffentlichen", headers=auth_headers, params={"datum": str(datum)})
    assert r.status_code == 200 and r.json()["veroeffentlicht"] == n
    # Vertretungskonto (FD-507)
    r = client.get("/api/vertretung/konto", headers=auth_headers)
    assert r.status_code == 200
    # Benachrichtigung an Betroffene
    r = client.get("/api/publish/notifications", headers=login(client, "huber@schule.at"))
    assert any(n["typ"] == "vertretung" for n in r.json())


# --- Prüfungen (FD-601/602) ---

def test_pruefungen_kollision(client, seeded, auth_headers):
    from datetime import date
    d = date(2025, 10, 6)
    r = client.post("/api/pruefungen", headers=auth_headers, json={
        "schuljahr_id": seeded["schuljahr_id"], "bezeichnung": "AM-Schularbeit 1AH", "art": "testwoche",
        "datum": str(d), "von_slot": 0, "bis_slot": 1, "raum_id": seeded["raeume"]["1A-Raum"],
        "klasse_id": seeded["klassen"]["1AH"]})
    assert r.status_code == 200
    p1 = r.json()["id"]
    r = client.post("/api/pruefungen", headers=auth_headers, json={
        "schuljahr_id": seeded["schuljahr_id"], "bezeichnung": "POS-Schularbeit 1AH", "art": "testwoche",
        "datum": str(d), "von_slot": 1, "bis_slot": 2, "raum_id": seeded["raeume"]["1A-Raum"],
        "klasse_id": seeded["klassen"]["1AH"]})
    p2 = r.json()["id"]
    r = client.get(f"/api/pruefungen/{p2}/kollision", headers=auth_headers)
    k = r.json()
    assert k["kollisionsfrei"] is False
    assert any(c["art"] in ("raum", "klasse") for c in k["konflikte"])
    r = client.get(f"/api/pruefungen/{p1}/kollision", headers=auth_headers)
    assert r.json()["kollisionsfrei"] is False  # p1 kollidiert mit p2


# --- Admin / Audit / Mandant (FD-901/904/905) ---

def test_admin_audit_und_mandant_export(client, seeded):
    h_admin = login(client, "admin@schule.at")
    r = client.post("/api/admin/benutzer", headers=h_admin, json={
        "email": "neu@schule.at", "name": "Neu Nora", "role": "lehrkraft"})
    assert r.status_code == 200
    r = client.post("/api/admin/benutzer", headers=h_admin, json={
        "email": "neu@schule.at", "name": "Dup", "role": "lehrkraft"})
    assert r.status_code == 409
    r = client.get("/api/admin/audit", headers=h_admin)
    assert r.status_code == 200 and len(r.json()) > 0
    assert any(a["aktion"] == "login_dev" for a in r.json())
    r = client.get("/api/admin/mandant-export", headers=h_admin)
    assert r.status_code == 200
    assert r.json()["schule"]["name"] == "BHAK Musterstadt"
    assert len(r.json()["planversionen"]) >= 1
