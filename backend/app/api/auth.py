"""
IMPORFACTORY Premium — Login propio.

Valida credenciales contra la tabla `usuarios` del ERP (grupo_impor, bcrypt $2b$)
y emite un JWT firmado con el SECRET del PROPIO proceso premium, en cookie
`access_token`. Así el token que emitimos es exactamente el que get_current_user
valida (mismo SECRET) — sin depender del SSO del ERP ni de cookies cross-dominio.

POST /api/auth/login   {email, password}  -> set-cookie access_token + {ok, user}
POST /api/auth/logout                      -> borra cookie
GET  /api/auth/me                          -> {user} | 401

2026-06-07.
"""
from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db_erp
from core.security import create_access_token, get_current_user
from models.models import Usuario


router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "access_token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 días


class LoginPayload(BaseModel):
    email: str
    password: str


def _verify(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password[:72].encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


@router.post("/login")
async def login(payload: LoginPayload, response: Response, db: AsyncSession = Depends(get_db_erp)):
    email = (payload.email or "").strip().lower()
    if not email or not payload.password:
        raise HTTPException(400, "Email y contraseña requeridos")

    row = (await db.execute(text("""
        SELECT id, nombre, email, password_hash, activo, avatar_url
        FROM usuarios WHERE LOWER(email) = :email LIMIT 1
    """), {"email": email})).mappings().first()

    # Anti-timing: verifica siempre contra algún hash
    dummy = "$2b$12$KIXn9Q6vQ2yYwJ8LJ4lqBuRK2HxgLqTzz4xxV6Hqj0F1f9XtK1q.S"
    target = row["password_hash"] if row else dummy
    ok = _verify(payload.password, target)

    if not row or not ok:
        raise HTTPException(401, "Email o contraseña incorrectos")
    if row.get("activo") == 0:
        raise HTTPException(403, "Usuario inactivo")

    token = create_access_token({
        "sub": str(row["id"]),
        "email": row["email"],
        "nombre": row["nombre"],
    })

    response.set_cookie(
        key=COOKIE_NAME, value=token,
        max_age=COOKIE_MAX_AGE, httponly=True, secure=True,
        samesite="lax", path="/",
    )
    # Actualizar last_login (best-effort)
    try:
        await db.execute(text("UPDATE usuarios SET last_login = NOW() WHERE id = :id"), {"id": row["id"]})
        await db.commit()
    except Exception:
        pass

    return {"ok": True, "user": {"id": row["id"], "nombre": row["nombre"],
                                 "email": row["email"], "avatar_url": row.get("avatar_url")}}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: Usuario = Depends(get_current_user), db: AsyncSession = Depends(get_db_erp)):
    row = (await db.execute(text("""
        SELECT id, nombre, email, avatar_url FROM usuarios WHERE id = :id LIMIT 1
    """), {"id": user.id})).mappings().first()
    if not row:
        return {"id": user.id, "email": getattr(user, "email", None)}
    return dict(row)
