"""
IMPORFACTORY Premium — Router de generación AI (Claude + DALL-E) para Blog.

Endpoints /api/imporfactory/blog/{empresa_id}/ai/...
2026-05-27 Sprint 5.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, get_db_erp
from core.security import get_current_user
from models.models import Usuario

from services.claude_ai_service import (
    generate_text,
    generate_outline,
    generate_article,
    generate_seo_meta,
    generate_schema_org,
    optimize_for_llm,
    generate_video_script,
)
from services.openai_images_service import generate_thumbnail


router = APIRouter(prefix="/api/imporfactory/blog", tags=["imporfactory-blog-ai"])


def _ensure_empresa_5(empresa_id: int):
    if empresa_id != 5:
        raise HTTPException(403, "Solo empresa_id=5 (IMPORFACTORY)")


def _safe_call(coro):
    """Wrapper que convierte RuntimeError de API key faltante en HTTPException 400."""
    async def wrapper(*args, **kwargs):
        try:
            return await coro(*args, **kwargs)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    return wrapper


class OutlinePayload(BaseModel):
    articulo_id: Optional[int] = None
    tema: str
    keyword: str
    longitud_palabras: int = 1500


class TextoPayload(BaseModel):
    articulo_id: Optional[int] = None
    outline: str
    keyword: str
    tono: str = "directo"
    longitud_palabras: int = 1500


class MiniaturaPayload(BaseModel):
    articulo_id: Optional[int] = None
    prompt: str
    style: str = "editorial photography, dramatic lighting, cinematic"
    size: str = "1792x1024"
    quality: str = "hd"


class SeoMetaPayload(BaseModel):
    articulo_id: int
    keyword: str


class SchemaOrgPayload(BaseModel):
    articulo_id: int
    tipo: str = "Article"


class OptimizarLlmPayload(BaseModel):
    articulo_id: int


class VideoScriptPayload(BaseModel):
    articulo_id: int
    duracion_target_seg: int = 480


class ReescribirPayload(BaseModel):
    articulo_id: Optional[int] = None
    seccion_md: str
    instruccion: str


@router.post("/{empresa_id}/ai/generar-outline")
async def ai_outline(
    empresa_id: int,
    payload: OutlinePayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    try:
        return await generate_outline(db, payload.tema, payload.keyword,
                                       payload.longitud_palabras, payload.articulo_id)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/{empresa_id}/ai/generar-texto")
async def ai_texto(
    empresa_id: int,
    payload: TextoPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    try:
        return await generate_article(db, payload.outline, payload.keyword,
                                       payload.tono, payload.longitud_palabras, payload.articulo_id)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/{empresa_id}/ai/generar-miniatura")
async def ai_miniatura(
    empresa_id: int,
    payload: MiniaturaPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    try:
        return await generate_thumbnail(db, payload.prompt, articulo_id=payload.articulo_id,
                                         style=payload.style, size=payload.size,
                                         quality=payload.quality, generado_por_id=user.id)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/{empresa_id}/ai/generar-seo-meta")
async def ai_seo_meta(
    empresa_id: int,
    payload: SeoMetaPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    # Cargar contenido del artículo
    row = (await db.execute(text("""
        SELECT contenido_md FROM blog_articulos WHERE id = :id
    """), {"id": payload.articulo_id})).first()
    if not row:
        raise HTTPException(404, "Articulo no encontrado")
    try:
        return await generate_seo_meta(db, payload.articulo_id, row[0] or "", payload.keyword)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/{empresa_id}/ai/generar-schema-org")
async def ai_schema_org(
    empresa_id: int,
    payload: SchemaOrgPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    row = (await db.execute(text("""
        SELECT titulo, contenido_md, autor_nombre_publico FROM blog_articulos WHERE id = :id
    """), {"id": payload.articulo_id})).mappings().first()
    if not row:
        raise HTTPException(404, "Articulo no encontrado")
    try:
        return await generate_schema_org(db, payload.articulo_id, row["titulo"],
                                          row["contenido_md"] or "", payload.tipo,
                                          row["autor_nombre_publico"] or "Equipo IMPORFACTORY")
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/{empresa_id}/ai/optimizar-llm")
async def ai_optimizar_llm(
    empresa_id: int,
    payload: OptimizarLlmPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    row = (await db.execute(text("""
        SELECT contenido_md FROM blog_articulos WHERE id = :id
    """), {"id": payload.articulo_id})).first()
    if not row:
        raise HTTPException(404, "Articulo no encontrado")
    try:
        return await optimize_for_llm(db, payload.articulo_id, row[0] or "")
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/{empresa_id}/ai/generar-script-video")
async def ai_script_video(
    empresa_id: int,
    payload: VideoScriptPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    row = (await db.execute(text("""
        SELECT contenido_md FROM blog_articulos WHERE id = :id
    """), {"id": payload.articulo_id})).first()
    if not row:
        raise HTTPException(404, "Articulo no encontrado")
    try:
        return await generate_video_script(db, payload.articulo_id, row[0] or "",
                                            payload.duracion_target_seg)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/{empresa_id}/ai/reescribir-seccion")
async def ai_reescribir(
    empresa_id: int,
    payload: ReescribirPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    prompt = (f"Reescribe el siguiente bloque de texto siguiendo esta instrucción: '{payload.instruccion}'.\n"
              f"Mantén el contenido y estructura, solo ajusta tono/estilo según indicación.\n\n"
              f"Bloque original:\n{payload.seccion_md}")
    try:
        return await generate_text(db, prompt, articulo_id=payload.articulo_id, tipo="reescribir",
                                    max_tokens=4000, temperature=0.7)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/{empresa_id}/ai/historial/{articulo_id}")
async def historial_ai(
    empresa_id: int,
    articulo_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    rows = (await db.execute(text("""
        SELECT id, tipo, modelo_usado, costo_usd, tokens_input, tokens_output,
               duracion_ms, generado_en, aceptado, prompt
        FROM blog_generaciones_ai
        WHERE articulo_id = :id
        ORDER BY generado_en DESC LIMIT 100
    """), {"id": articulo_id})).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.get("/{empresa_id}/ai/health")
async def ai_health(
    empresa_id: int,
    db: AsyncSession = Depends(get_db_erp),
    user: Usuario = Depends(get_current_user),
):
    """Verifica si las API keys están configuradas (env O empresa_config ERP)."""
    _ensure_empresa_5(empresa_id)
    import os
    # Prioridad 1: variables de entorno (.env del proceso)
    anthropic_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
    openai_ok = bool(os.environ.get("OPENAI_API_KEY"))
    # Prioridad 2: empresa_config (BD ERP grupo_impor)
    if not (anthropic_ok and openai_ok):
        keys = (await db.execute(text("""
            SELECT clave, LENGTH(valor) AS lvalor FROM empresa_config
            WHERE empresa_id = 5 AND clave IN ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY')
        """))).mappings().all()
        available = {k["clave"]: bool(k["lvalor"] and k["lvalor"] > 10) for k in keys}
        anthropic_ok = anthropic_ok or available.get("ANTHROPIC_API_KEY", False)
        openai_ok = openai_ok or available.get("OPENAI_API_KEY", False)
    return {
        "anthropic_configured": anthropic_ok,
        "openai_configured": openai_ok,
        "ready_for_ai": anthropic_ok and openai_ok,
    }
