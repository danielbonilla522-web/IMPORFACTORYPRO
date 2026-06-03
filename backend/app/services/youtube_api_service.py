"""
IMPORFACTORY Premium — Wrapper YouTube Data API v3.

OAuth user-managed con refresh token. Credenciales en empresa_config(empresa_id=5):
  YOUTUBE_OAUTH_CLIENT_ID, YOUTUBE_OAUTH_CLIENT_SECRET,
  YOUTUBE_ACCESS_TOKEN, YOUTUBE_REFRESH_TOKEN, YOUTUBE_EXPIRES_AT,
  YOUTUBE_CHANNEL_ID.

2026-05-27 Sprint 6.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
REDIRECT_URI = "https://impor.imporchina.com/api/imporfactory/youtube/5/oauth/callback"


async def _get_config(db: AsyncSession, empresa_id: int = 5) -> dict:
    rows = (await db.execute(text("""
        SELECT clave, valor FROM empresa_config
        WHERE empresa_id = :emp AND clave LIKE 'YOUTUBE_%'
    """), {"emp": empresa_id})).mappings().all()
    return {r["clave"]: r["valor"] for r in rows}


async def _save_config(db: AsyncSession, empresa_id: int, clave: str, valor: str):
    await db.execute(text("""
        INSERT INTO empresa_config (empresa_id, clave, valor)
        VALUES (:emp, :clave, :valor)
        ON DUPLICATE KEY UPDATE valor = VALUES(valor), updated_at = NOW()
    """), {"emp": empresa_id, "clave": clave, "valor": valor})
    await db.commit()


def _build_oauth_flow(client_id: str, client_secret: str):
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=OAUTH_SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    return flow


async def get_authorize_url(db: AsyncSession, empresa_id: int = 5) -> str:
    cfg = await _get_config(db, empresa_id)
    client_id = cfg.get("YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = cfg.get("YOUTUBE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Configurar YOUTUBE_OAUTH_CLIENT_ID y YOUTUBE_OAUTH_CLIENT_SECRET "
                          "en empresa_config(empresa_id=5) antes de conectar YouTube.")
    flow = _build_oauth_flow(client_id, client_secret)
    url, _state = flow.authorization_url(access_type="offline", prompt="consent",
                                           include_granted_scopes="true")
    return url


async def handle_callback(db: AsyncSession, code: str, empresa_id: int = 5) -> dict:
    cfg = await _get_config(db, empresa_id)
    client_id = cfg.get("YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = cfg.get("YOUTUBE_OAUTH_CLIENT_SECRET")
    flow = _build_oauth_flow(client_id, client_secret)
    flow.fetch_token(code=code)
    creds = flow.credentials

    await _save_config(db, empresa_id, "YOUTUBE_ACCESS_TOKEN", creds.token)
    if creds.refresh_token:
        await _save_config(db, empresa_id, "YOUTUBE_REFRESH_TOKEN", creds.refresh_token)
    expires = (creds.expiry or datetime.utcnow() + timedelta(hours=1)).isoformat()
    await _save_config(db, empresa_id, "YOUTUBE_EXPIRES_AT", expires)

    return {"ok": True, "expires_at": expires}


async def _get_credentials(db: AsyncSession, empresa_id: int = 5):
    """Carga credenciales y refresca si vencidas."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest

    cfg = await _get_config(db, empresa_id)
    access = cfg.get("YOUTUBE_ACCESS_TOKEN")
    refresh = cfg.get("YOUTUBE_REFRESH_TOKEN")
    client_id = cfg.get("YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = cfg.get("YOUTUBE_OAUTH_CLIENT_SECRET")

    if not refresh or not client_id or not client_secret:
        raise RuntimeError("YouTube OAuth no configurado. Conectar en /configuracion primero.")

    creds = Credentials(
        token=access,
        refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=OAUTH_SCOPES,
    )

    if not creds.valid:
        creds.refresh(GoogleRequest())
        await _save_config(db, empresa_id, "YOUTUBE_ACCESS_TOKEN", creds.token)
        if creds.expiry:
            await _save_config(db, empresa_id, "YOUTUBE_EXPIRES_AT", creds.expiry.isoformat())

    return creds


async def list_videos_from_yt(db: AsyncSession, max_results: int = 50, empresa_id: int = 5) -> list[dict]:
    """Lista videos del canal autenticado."""
    creds = await _get_credentials(db, empresa_id)
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", credentials=creds)

    # Obtener uploads playlist
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    items_resp = yt.playlistItems().list(
        part="snippet,contentDetails", playlistId=uploads_id, maxResults=max_results,
    ).execute()

    video_ids = [it["contentDetails"]["videoId"] for it in items_resp.get("items", [])]
    if not video_ids:
        return []

    details = yt.videos().list(part="snippet,statistics,status,contentDetails",
                                  id=",".join(video_ids)).execute()
    return details.get("items", [])


async def sync_videos_to_db(db: AsyncSession, empresa_id: int = 5) -> int:
    """Sincroniza videos remotos a blog_videos_youtube."""
    items = await list_videos_from_yt(db, max_results=50, empresa_id=empresa_id)
    n = 0
    for it in items:
        s = it["snippet"]
        stats = it.get("statistics", {})
        status_priv = it.get("status", {}).get("privacyStatus", "publicado")
        estado_map = {"public": "publicado", "unlisted": "no_listado", "private": "privado"}
        estado = estado_map.get(status_priv, "publicado")
        await db.execute(text("""
            INSERT INTO blog_videos_youtube
                (empresa_id, video_id_yt, youtube_channel_id, titulo, descripcion,
                 thumbnail_url, estado, fecha_publicacion, views, likes, comments,
                 tags_yt, last_stats_sync)
            VALUES
                (:emp, :vid, :ch, :tit, :desc, :th, :est, :pub, :v, :l, :c, :tags, NOW())
            ON DUPLICATE KEY UPDATE
                titulo = VALUES(titulo),
                descripcion = VALUES(descripcion),
                thumbnail_url = VALUES(thumbnail_url),
                estado = VALUES(estado),
                views = VALUES(views),
                likes = VALUES(likes),
                comments = VALUES(comments),
                tags_yt = VALUES(tags_yt),
                last_stats_sync = NOW()
        """), {
            "emp": empresa_id, "vid": it["id"], "ch": s.get("channelId"),
            "tit": s.get("title", ""), "desc": s.get("description", ""),
            "th": (s.get("thumbnails", {}).get("maxres") or s.get("thumbnails", {}).get("high") or {}).get("url"),
            "est": estado,
            "pub": s.get("publishedAt", "").replace("T", " ").replace("Z", "")[:19] or None,
            "v": int(stats.get("viewCount", 0)),
            "l": int(stats.get("likeCount", 0)),
            "c": int(stats.get("commentCount", 0)),
            "tags": json.dumps(s.get("tags", [])),
        })
        n += 1
    await db.commit()
    return n
