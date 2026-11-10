"""SPPS – Stundenplanplanungssystem für Schulen. FastAPI-Anwendung mit OpenAPI (TU-10)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import Base, engine
from .routers import admin, auth, plan, pruefungen, publish, stammdaten, veranstaltungen, vertretung


def create_app() -> FastAPI:
    app = FastAPI(
        title="SPPS – Stundenplanplanungssystem",
        version="1.0.0",
        description=(
            "REST-API des Stundenplanplanungssystems für Schulen (Pflichtenheft v1.0). "
            "Mandantenfähig (je Schule), RBAC, OIDC-Authentifizierung, asynchroner Constraint-Solver, "
            "Vertretungsplanung, Veröffentlichungsworkflow, Exporte (iCal/CSV/HTML/PDF)."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(stammdaten.router, prefix="/api")
    app.include_router(veranstaltungen.router, prefix="/api")
    app.include_router(plan.router, prefix="/api")
    app.include_router(vertretung.router, prefix="/api")
    app.include_router(pruefungen.router, prefix="/api")
    app.include_router(publish.router, prefix="/api")
    app.include_router(publish.router_export, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "spps", "version": "1.0.0"}

    @app.post("/api/init-db", tags=["dev"])
    def init_db():
        """Entwicklung: Datenbankschema anlegen (Produktion: Migrationen, NF-404)."""
        Base.metadata.create_all(bind=engine)
        return {"ok": True}

    return app


app = create_app()
