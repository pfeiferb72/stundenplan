from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditLog, Role, User

bearer = HTTPBearer(auto_error=False)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "school_id": user.school_id,
        "role": user.role,
        "email": user.email,
        "name": user.name,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.token_ttl_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger oder abgelaufener Token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht authentifiziert")
    claims = decode_token(credentials.credentials)
    user = db.get(User, int(claims["sub"]))
    if not user or not user.aktiv:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Benutzer nicht aktiv")
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """Wie get_current_user, aber None statt 401 – für Endpunkte mit alternativem Token (Abo)."""
    if not credentials:
        return None
    try:
        claims = decode_token(credentials.credentials)
    except HTTPException:
        return None
    return db.get(User, int(claims["sub"]))


def require_roles(*roles: Role):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in [r.value for r in roles]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Berechtigung für diese Aktion")
        return user
    return dep


def audit(db: Session, user: User | None, aktion: str, objekt: str | None = None,
          details: dict | None = None, ip: str | None = None):
    db.add(AuditLog(
        school_id=user.school_id if user else None,
        user_id=user.id if user else None,
        aktion=aktion, objekt=objekt, details=details or {}, ip=ip,
    ))
    db.commit()


def effective_school_id(user: User, school_id: int | None) -> int:
    """Mandantenprüfung: normale Rollen sind auf ihre Schule beschränkt, Sysadmin wählt Mandant frei."""
    if user.role == Role.SYSADMIN.value:
        if school_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="school_id erforderlich für Sysadmin")
        return school_id
    if user.school_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Benutzer ohne Mandant")
    if school_id is not None and school_id != user.school_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff auf fremden Mandanten verweigert")
    return user.school_id


def get_request_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def roles_decorator(roles: list[Role]):
    def wrap(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            return fn(*args, **kwargs)
        return inner
    return wrap
