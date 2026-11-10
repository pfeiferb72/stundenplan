"""Entwicklungs-Gesamtstart: eingebettetes PostgreSQL + Schema + Seed + API-Server (ein Prozess).

Aufruf:  PYTHONPATH=. python3 scripts/dev_server.py   →  http://127.0.0.1:8000/docs
Frontend: cd frontend && npm run dev                  →  http://127.0.0.1:5173
"""
import os
import sys
from pathlib import Path

import pgserver

ROOT = Path(__file__).resolve().parent.parent
PGDATA = ROOT.parent / ".pgdata"


def ensure_db() -> str:
    PGDATA.mkdir(exist_ok=True)
    server = pgserver.get_server(str(PGDATA))
    uri = server.get_uri("postgres").replace("postgresql://", "postgresql+psycopg://")
    os.environ.setdefault("SPPS_DATABASE_URL", uri)
    os.environ.setdefault("SPPS_DEV_AUTH", "true")
    os.environ.setdefault("SPPS_JWT_SECRET", "dev-secret")
    (ROOT / ".env").write_text(
        f"SPPS_DATABASE_URL={uri}\nSPPS_DEV_AUTH=true\nSPPS_JWT_SECRET=dev-secret\n")
    return uri


def main():
    uri = ensure_db()
    print(f"[spps] PostgreSQL: {uri}")
    from app.db import Base, SessionLocal, engine
    import app.models  # noqa: F401 – registriert alle Tabellen auf Base.metadata
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    from app.models import Schule
    if not db.query(Schule).first():
        from app.seed import seed_demo
        seed_demo(db)
        print("[spps] Demo-Mandant 'BHAK Musterstadt' geseedet")
    else:
        print("[spps] Datenbank bereits befüllt")
    db.close()

    import uvicorn
    print("[spps] API läuft auf http://127.0.0.1:8000  (OpenAPI: /docs)")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    sys.exit(main())
