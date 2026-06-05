"""
IMPORFACTORY Premium — Router YouTube integration.

Endpoints /api/imporfactory/youtube/{empresa_id}/...
2026-05-27 Sprint 6.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, get_db_erp
from core.security import get_current_user
from models.models import Usuario

from services import youtube_api_service as yt


router = APIRouter(prefix="/api/imporfactory/youtube", tags=["imporfactory-youtube"])


def _ensure_empresa_5(empresa_id: int):
    if empresa_id != 5:
        raise HTTPException(403, "Solo empresa_id=5 (IMPORFACTORY)")


@router.get("/{empresa_id}/oauth/start")
async def oauth_start(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    try:
        url = await yt.get_authorize_url(db, empresa_id)
        return RedirectResponse(url=url)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/{empresa_id}/oauth/callback")
async def oauth_callback(
    empresa_id: int,
    code: str,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    _ensure_empresa_5(empresa_id)
    try:
        result = await yt.handle_callback(db, code, empresa_id)
        return RedirectResponse(url="/videos?youtube_connected=1")
    except Exception as e:
        raise HTTPException(400, f"OAuth callback error: {e}")


@router.get("/{empresa_id}/health")
async def yt_health(
    empresa_id: int,
    db: AsyncSession = Depends(get_db_erp),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    cfg = (await db.execute(text("""
        SELECT clave, LENGTH(valor) AS lvalor FROM empresa_config
        WHERE empresa_id = 5 AND clave LIKE 'YOUTUBE_%'
    """))).mappings().all()
    state = {c["clave"]: bool(c["lvalor"] and c["lvalor"] > 5) for c in cfg}
    return {
        "client_configured": state.get("YOUTUBE_OAUTH_CLIENT_ID", False) and state.get("YOUTUBE_OAUTH_CLIENT_SECRET", False),
        "oauth_connected": state.get("YOUTUBE_REFRESH_TOKEN", False),
        "ready": all([
            state.get("YOUTUBE_OAUTH_CLIENT_ID", False),
            state.get("YOUTUBE_OAUTH_CLIENT_SECRET", False),
            state.get("YOUTUBE_REFRESH_TOKEN", False),
        ]),
    }


@router.get("/{empresa_id}/videos")
async def listar_videos(
    empresa_id: int,
    estado: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    where = "WHERE empresa_id = 5"
    params = {}
    if estado:
        where += " AND estado = :est"
        params["est"] = estado
    rows = (await db.execute(text(f"""
        SELECT id, video_id_yt, titulo, thumbnail_url, estado, fecha_publicacion,
               views, likes, comments, last_stats_sync, duracion_seg, articulo_id
        FROM blog_videos_youtube
        {where}
        ORDER BY fecha_publicacion DESC LIMIT 200
    """), params)).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.post("/{empresa_id}/videos/sync")
async def sync_videos(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    try:
        n = await yt.sync_videos_to_db(db, empresa_id)
        return {"ok": True, "synced": n}
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"YouTube API error: {e}")
