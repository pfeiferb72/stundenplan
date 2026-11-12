"""Authentifizierung: OIDC (TU-50, z. B. Microsoft Entra ID) + Dev-Login für lokale Entwicklung."""
from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import audit, create_token, get_current_user, get_request_ip
from ..config import settings
from ..db import get_db
from ..models import User
from ..schemas import DevLogin, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth = OAuth()
if settings.oidc_issuer:
    _oauth.register(
        name="oidc",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@router.post("/dev-login", response_model=TokenOut)
def dev_login(body: DevLogin, request: Request, db: Session = Depends(get_db)):
    """Nur aktiv, wenn SPPS_DEV_AUTH=true (lokale Entwicklung ohne IdP)."""
    if not settings.dev_auth:
        raise HTTPException(status_code=404, detail="Dev-Login deaktiviert")
    user = db.scalar(select(User).where(User.email == body.email))
    if not user or not user.aktiv:
        raise HTTPException(status_code=401, detail="Unbekannter oder inaktiver Benutzer")
    audit(db, user, "login_dev", "benutzer", {"email": user.email}, get_request_ip(request))
    return TokenOut(access_token=create_token(user), user={
        "id": user.id, "email": user.email, "name": user.name, "role": user.role,
        "school_id": user.school_id, "lehrkraft_id": user.lehrkraft_id, "klasse_id": user.klasse_id,
    })


@router.get("/login")
async def oidc_login(request: Request):
    if not settings.oidc_issuer:
        raise HTTPException(status_code=400, detail="OIDC nicht konfiguriert (SPPS_OIDC_ISSUER fehlt)")
    return await _oauth.oidc.authorize_redirect(request, settings.oidc_redirect_uri)


@router.get("/callback")
async def oidc_callback(request: Request, db: Session = Depends(get_db)):
    if not settings.oidc_issuer:
        raise HTTPException(status_code=400, detail="OIDC nicht konfiguriert")
    token = await _oauth.oidc.authorize_access_token(request)
    userinfo = token.get("userinfo") or await _oauth.oidc.parse_id_token(request, token)
    sub = userinfo.get("sub")
    email = userinfo.get("email")
    if not sub or not email:
        raise HTTPException(status_code=400, detail="OIDC-Token ohne sub/email")
    user = db.scalar(select(User).where(User.oidc_sub == sub))
    if not user:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.oidc_sub = sub
            db.commit()
    if not user:
        raise HTTPException(status_code=403, detail="Kein SPPS-Benutzerkonto für diese Identität (Provisioning durch Admin)")
    if not user.aktiv:
        raise HTTPException(status_code=403, detail="Benutzerkonto deaktiviert")
    audit(db, user, "login_oidc", "benutzer", {"sub": sub}, get_request_ip(request))
    frontend = request.query_params.get("state") or "http://127.0.0.1:5173"
    jwt_token = create_token(user)
    return RedirectResponse(url=f"{frontend}/#/login?token={jwt_token}")


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id, "email": user.email, "name": user.name, "role": user.role,
        "school_id": user.school_id, "lehrkraft_id": user.lehrkraft_id, "klasse_id": user.klasse_id,
    }
