import os
import tempfile

import pgserver
import pytest

_tmp = tempfile.mkdtemp(prefix="spps-test-pg-")
_server = pgserver.get_server(_tmp)
_uri = _server.get_uri("postgres").replace("postgresql://", "postgresql+psycopg://")
os.environ["SPPS_DATABASE_URL"] = _uri
os.environ["SPPS_DEV_AUTH"] = "true"
os.environ["SPPS_JWT_SECRET"] = "test-secret"

from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.seed import seed_demo  # noqa: E402


@pytest.fixture()
def db() -> Session:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def seeded(db) -> dict:
    return seed_demo(db)


@pytest.fixture()
def client(db, seeded):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client, seeded) -> dict:
    r = client.post("/api/auth/dev-login", json={"email": "planer@schule.at"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
