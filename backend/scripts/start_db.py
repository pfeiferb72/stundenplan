"""Startet eine lokale PostgreSQL-Instanz (eingebettet via pgserver, EU-lokal) und schreibt backend/.env.

Produktiv wird stattdessen ein verwalteter PostgreSQL-Cluster (Kubernetes) per SPPS_DATABASE_URL angebunden.
"""
import os
import sys
from pathlib import Path

import pgserver

ROOT = Path(__file__).resolve().parent.parent.parent
PGDATA = ROOT / ".pgdata"


def main():
    PGDATA.mkdir(exist_ok=True)
    server = pgserver.get_server(str(PGDATA))
    uri = server.get_uri("postgres")
    # SQLAlchemy-kompatible URL
    sa_url = uri.replace("postgresql://", "postgresql+psycopg://")
    env_path = ROOT / "backend" / ".env"
    env_path.write_text(
        f"SPPS_DATABASE_URL={sa_url}\n"
        f"SPPS_JWT_SECRET=dev-secret-{os.urandom(8).hex()}\n"
        f"SPPS_DEV_AUTH=true\n"
    )
    print(f"PostgreSQL läuft. SQLAlchemy-URL:\n  {sa_url}")
    print(f"Geschrieben nach: {env_path}")
    # Verbindung testen
    import psycopg
    with psycopg.connect(uri) as conn:
        ver = conn.execute("select version()").fetchone()[0]
    print(f"Verbindung OK: {ver[:60]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
