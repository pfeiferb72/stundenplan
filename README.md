# SPPS – Stundenplanplanungssystem für Schulen

Implementierung des Pflichtenhefts v1.0 (Entwurf): assistiertes Planungswerkzeug mit
Stammdaten, Restriktions-Engine, asynchronem Constraint-Solver, Vertretungsplanung,
Veröffentlichungsworkflow und Exports – als mandantenfähige Webapplikation (Backend + Frontend).

## Stack (TU-10…TU-60)

| Komponente | Technologie |
|---|---|
| Backend | Python 3.12, FastAPI (REST + automatische OpenAPI-Spezifikation, 65 Endpunkte, `/docs`) |
| Datenbank | PostgreSQL 16, mandantenfähiges Modell (`school_id` auf allen Mandantentabellen, FD-902) |
| Frontend | React 18 + TypeScript + Vite (SPA, komponentenbasiert, TU-20) |
| Solver | eigene Metaheuristik (konstruktiv + Simulated Annealing), asynchron, abbrechbar, Zeitbudget (TU-40, FD-302/303) |
| Auth | OIDC (Authlib, z. B. Microsoft Entra ID) + Dev-Login/JWT für lokale Entwicklung (TU-50), RBAC (FD-901) |
| Exporte | iCalendar, CSV, PDF (reportlab), einbettbares HTML/JS-Widget (TU-60, FD-704) |

## Schnellstart (lokale Entwicklung)

Empfohlen unter Debian/Ubuntu (PEP 668: kein systemweites `pip install` nötig) mit **uv** —
uv installiert automatisch Python 3.12, für den das eingebettete PostgreSQL (`pgserver`) ein Wheel hat:

```bash
# 0) Repo klonen und hinein wechseln
 git clone https://github.com/pfeiferb72/stundenplan.git
 cd stundenplan

# 1) uv installieren (einmalig) und Python 3.12 + Abhängigkeiten in .venv
 curl -LsSf https://astral.sh/uv/install.sh | sh
 uv venv --python 3.12 .venv
 uv pip install --python .venv/bin/python -r backend/requirements.txt
 cd frontend && npm install && cd ..

# 2) Alles starten: eingebettetes PostgreSQL + API (:8000) + Frontend (:5173)
./scripts/dev.sh
#    oder einzeln:
#    cd backend && PYTHONPATH=. ../.venv/bin/python scripts/dev_server.py   # DB + Seed + API, OpenAPI: http://127.0.0.1:8000/docs
#    cd frontend && npm run dev                                              # http://127.0.0.1:5173 (Proxy /api -> :8000)

# 3) Demo-Login (Dev-Modus): planer@schule.at / leitung@schule.at / huber@schule.at / admin@schule.at
```

**Alternative ohne uv (klassisches venv + System-PostgreSQL):**

```bash
sudo apt install python3-venv python3-full postgresql   # Debian/Ubuntu
 git clone https://github.com/pfeiferb72/stundenplan.git && cd stundenplan
 python3 -m venv .venv && source .venv/bin/activate
 pip install -r backend/requirements.txt
 # eigene DB vorbereiten (als postgres-User):  createdb spps
 export SPPS_DATABASE_URL="postgresql+psycopg://postgres@localhost:5432/spps"
 cd backend && PYTHONPATH=. python scripts/dev_server.py    # API auf :8000, ohne pgserver-Seed: POST /api/init-db
 cd ../frontend && npm install && npm run dev               # :5173
```

Hinweis: `pgserver` (eingebettetes PostgreSQL) benötigt Python ≤ 3.13; mit Python 3.14 bitte die Alternative mit System-PostgreSQL verwenden.

Die lokale PostgreSQL-Instanz läuft eingebettet via `pgserver` (Daten in `.pgdata/`, EU-lokal).
In Produktion wird ein verwalteter PostgreSQL-Cluster per `SPPS_DATABASE_URL` angebunden
(siehe `docker-compose.yml`), OIDC per `SPPS_OIDC_ISSUER`/`SPPS_OIDC_CLIENT_ID`/`SPPS_OIDC_CLIENT_SECRET`.

## Tests (Abschnitt 7 des Pflichtenhefts)

```bash
cd backend && python3 -m pytest        # 31 Tests
```

- `tests/test_engine.py` – QS-101: Unit-Tests der Restriktions-Engine (Doppelbelegung Lehrkraft/Klasse/Raum,
  Raumeignung, Lehrverpflichtung exakt, Sperrzeiten, Kopplungsgruppen, Löcher, Score …)
- `tests/test_solver.py` – QS-102: Solver-Regression auf Referenzszenario (0 harte Verletzungen),
  Abbruchtest, Fixierungen
- `tests/test_api.py` – QS-103: Integrationstests aller API-Module inkl. RBAC (FD-901),
  Mandantenschutz (FD-902), Workflow (FD-702), Vertretung (FD-501…506), Exporte, Audit (FD-904)

## Projektstruktur

```
spps/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI-App, OpenAPI, CORS
│   │   ├── config.py          # Settings (Env/.env)
│   │   ├── models.py          # SQLAlchemy-Modell (Abschnitt 5 Pflichtenheft), mandantenfähig
│   │   ├── auth.py            # JWT, OIDC-Vorbereitung, RBAC, Audit
│   │   ├── solver/
│   │   │   ├── engine.py      # Restriktions-Engine: harte (FD-204) / weiche (FD-205) Regeln, Score
│   │   │   ├── heuristic.py   # konstruktiv + Simulated Annealing, abbrechbar
│   │   │   └── loader.py      # DB -> PlanContext
│   │   ├── jobs.py            # asynchrone Solver-Läufe (Thread, abbrechbar, transaktional)
│   │   ├── exports.py         # iCal / CSV / HTML-Widget / PDF
│   │   ├── seed.py            # Demo-Mandant (Referenzszenario)
│   │   └── routers/           # auth, stammdaten, veranstaltungen, plan(+solver),
│   │                          # vertretung, pruefungen, publish(+export), admin
│   ├── scripts/dev_server.py  # lokaler Gesamtstart (PG + Seed + API)
│   └── tests/                 # QS-101/102/103
├── frontend/src/views/        # Login, Stammdaten, Planer (DnD-Grid), Vertretung, Pläne & Exporte, Admin
├── scripts/dev.sh
└── docker-compose.yml         # Produktions-Referenz (API + PostgreSQL + Frontend-Build)
```

## Umsetzungsschwerpunkte je Pflichtenheft-Abschnitt

- **4.1 Stammdaten (FD-101…109)**: CRUD für Schuljahre/Semester/Klassen/Lehrkräfte/Gegenstände/Räume/
  Stundentafeln, Zeitraster- und Gewicht-Konfiguration je Schule (FD-903), SMLS-CSV-Import mit
  Konfliktbericht (FD-109/SS-10).
- **4.2 Restriktionen (FD-201…209)**: harte Regeln (Doppelbelegung, Lehrverpflichtung exakt, Raumeignung,
  Tageslast/Stückelung, Verfügbarkeit, Kopplung) + gewichtete weiche Regeln (Löcher, letzte Stunde,
  unterrichtsfreie Tage, Wunschfenster, Stammraum …) mit konsolidierter Konfliktübersicht.
- **4.3 Planerstellung (FD-301…307)**: Drag & Drop mit Echtzeit-Validierung (harte blockieren, 409),
  asynchroner Solver mit Zeitbudget/Fixierungen/Teillösung, Score mit Aufschlüsselung, Planversionen + Diff,
  transaktionales Undo.
- **4.5 Vertretung (FD-501…507)**: Abwesenheit → betroffene Stunden → Kaskaden-Vorschläge
  (Fachvertretung → Betreuung → Zusammenlegung → Ausfall, konfigurierbar), Ein-Schritt-Vorschlag,
  manuelle Anpassung, Veröffentlichung mit Benachrichtigung, Vertretungskonten.
- **4.6 Prüfungen (FD-601/602/604)**: Prüfungstermine mit Kollisionsprüfung (Raum/Aufsicht/Klasse).
- **4.7/4.8 Veröffentlichung (FD-701…706, FD-801)**: Workflow Entwurf→Prüfung→Freigabe→Veröffentlicht
  (Freigabe nur Schulleitung), Ansichten Klasse/Lehrer/Raum/Tag, versionierte Veröffentlichung,
  iCal/CSV/PDF/HTML-Widget, Abo-Tokens, Änderungsanzeige, In-App-Benachrichtigungen.
- **4.9 Administration (FD-901…905)**: RBAC je Mandant, Audit-Log, Mandanten-Export (DSGVO).
- **TU-50**: OIDC-Login/Callout implementiert (`/api/auth/login`, `/api/auth/callback`); Dev-Login lokal.
- **TU-70**: versionierte JSON-API (`/api/export/plan.json`) + OpenAPI unter `/docs`.

## Offene Punkte (aus Abschnitt 11 des Pflichtenhefts, hier als TODOs)

- Konkrete SMLS-Exportformate je Schulart (SS-10) – CSV-Import ist generisch vorbereitet.
- Echte OIDC-IdP-Anbindung testen (aktuell Dev-Login), E-Mail-Versand (SS-60) als Notification-Stub.
- Solver-Benchmark CP-SAT vs. Metaheuristik bei 40 Klassen/80 Lehrkräften (NF-102: hier Metaheuristik,
  asynchron mit Fortschritt/Abbruch; Austausch gegen OR-Tools CP-SAT über `solver/heuristic.py` möglich).
- Alembic-Migrationen für Schema-Evolution (NF-404) – lokal `create_all`, Compose siehe `docker-compose.yml`.
