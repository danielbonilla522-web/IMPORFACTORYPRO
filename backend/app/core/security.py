"""IMPORFACTORY Premium — core/security.py.

JWT decode compartido con ERP (mismo SECRET_KEY). Modo simplificado: el token
viene del login del ERP en erp.imporchina.com. Decodificamos y devolvemos un
objeto stub `CurrentUser` con .id y .email.

Si necesitas datos más completos del usuario (rol, empresa, etc.), hace una
query manual a la BD ERP (`get_db_erp()`).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


SECRET_KEY = os.environ.get("SECRET_KEY", "")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 días


# ────────────────────────────────────────
# Modelo proxy del usuario
# ────────────────────────────────────────

class CurrentUser(BaseModel):
    """Stub del usuario autenticado. Solo .id es garantizado, el resto opcional."""
    id: int
    email: Optional[str] = None
    rol: Optional[str] = None


security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> CurrentUser:
    """Dependencia FastAPI: decodifica JWT del header Authorization: Bearer xxx
    o de cookie 'access_token' (mismo patrón del ERP).
    """
    token = None
    if creds and creds.credentials:
        token = creds.credentials
    else:
        # Fallback: cookie
        token = request.cookies.get("access_token") or request.cookies.get("token")
        if token and token.startswith("Bearer "):
            token = token[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not SECRET_KEY:
        raise HTTPException(500, "SECRET_KEY no configurado en .env")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expirado")
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, f"Token inválido: {e}")

    user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
    if user_id is None:
        raise HTTPException(401, "Token sin user_id")

    try:
        user_id = int(user_id)
    except Exception:
        raise HTTPException(401, "user_id no es int")

    return CurrentUser(
        id=user_id,
        email=payload.get("email"),
        rol=payload.get("rol"),
    )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Helper para tests o login interno (en producción el JWT viene del ERP)."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
