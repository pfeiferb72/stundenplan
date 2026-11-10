# Umsetzungsdokumentation – SPPS (Pflichtenheft v1.0 → Code)

## Architektur

- **Backend** `backend/app`: FastAPI, Schichtentrennung `routers/` (HTTP) → `solver/` (Domänenlogik,
  DB-frei testbar) → `models.py` (SQLAlchemy, PostgreSQL, mandantenfähig via `school_id`).
- **Solver** läuft asynchron in einem Thread (`jobs.py`), Status/Fortschritt in Tabelle `solver_run`,
  Abbruch über `threading.Event` (`POST /plan/solver/runs/{id}/abort`), Ergebnis transaktional als
  neue `planversion` (NF-303).
- **Restriktions-Engine** `solver/engine.py`: `hard_violations` (FD-204), `soft_violations` (FD-205,
  Gewichte aus Schul-Config), `score` (FD-305), schnelle Single-Pass-Variante `_evaluate` für die
  Solver-Loop, `validate_move` für Echtzeit-Validierung beim Drag & Drop (FD-301).
- **Frontend** `frontend/src/views`: React-SPA, Vite-Devserver mit Proxy `/api → :8000`.

## Anforderungs-Mapping (Auszug, M-Prioritäten)

| ID | Umsetzung |
|---|---|
| TU-10 | FastAPI, OpenAPI unter `/docs` + `/openapi.json` (65 Pfade) |
| TU-20 | React-SPA, komponentenbasiert |
| TU-30 | PostgreSQL, `school_id` auf allen Mandantentabellen |
| TU-40 | Metaheuristik (konstruktiv + SA), asynchron/abbrechbar (`solver/heuristic.py`, `jobs.py`) |
| TU-50 | OIDC (`/api/auth/login|callback`, Authlib) + Dev-Login (`SPPS_DEV_AUTH`) |
| TU-60 | `/api/export/ics|csv|html|pdf`, Widget-JS |
| FD-101…109 | `routers/stammdaten.py`, SMLS-CSV-Import mit Konfliktbericht |
| FD-201…209 | `routers/veranstaltungen.py`, `solver/engine.py` |
| FD-301…307 | `routers/plan.py` (PATCH stunde mit 409 bei harten Verstößen, Undo, Diff, Score) |
| FD-302…305 | `routers/plan.py` Solver-Endpunkte + `jobs.py` |
| FD-501…507 | `routers/vertretung.py` (Kaskade aus Schul-Config, Konto) |
| FD-601/602/604 | `routers/pruefungen.py` (Kollisionsprüfung) |
| FD-701…706 | `routers/publish.py` (Workflow, Ansichten, Aenderungen, Abos) |
| FD-801 | `notification`-Tabelle + Endpunkte, Benachrichtigung bei Veröffentlichung/Vertretung |
| FD-901…905 | `routers/admin.py` (RBAC, Audit-Log, Mandanten-Export) |
| QS-101/102/103 | `tests/test_engine.py`, `tests/test_solver.py`, `tests/test_api.py` |

## Betrieb/Config (Env)

`SPPS_DATABASE_URL`, `SPPS_JWT_SECRET`, `SPPS_DEV_AUTH`, `SPPS_OIDC_*`, `SPPS_CORS_ORIGINS` –
siehe `backend/app/config.py` und `docker-compose.yml`.
