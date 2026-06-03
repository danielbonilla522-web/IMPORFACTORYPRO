"""
IMPORFACTORY Premium — Router AI extendido (Sprint 8).
Agregar al router existente imporfactory_blog_ai.py:
  - GET /fotos-base — listar banco fotos Daniel
  - POST /ai/generar-miniatura-gemini — Gemini 2.5 Flash Image con foto base
  - POST /ai/generar-miniatura-gemini-pura — sin foto base
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.models import Usuario

from services import gemini_images_service as gem


# Este router se importa desde main.py y se suma con app.include_router(imporfactory_blog_gemini.router)
router = APIRouter(prefix="/api/imporfactory/blog", tags=["imporfactory-blog-gemini"])


def _ensure_empresa_5(empresa_id: int):
    if empresa_id != 5:
        raise HTTPException(403, "Solo empresa_id=5 (IMPORFACTORY)")


class GeminiBasePayload(BaseModel):
    articulo_id: Optional[int] = None
    foto_base_id: int
    headline: str
    kicker: Optional[str] = None
    badge: Optional[str] = None
    mood: str = "bodega-productos"
    aspect: str = "16:9"


class GeminiPurePayload(BaseModel):
    articulo_id: Optional[int] = None
    prompt: str
    aspect: str = "16:9"


@router.get("/{empresa_id}/fotos-base")
async def listar_fotos_base(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    fotos = await gem.listar_fotos_base(db)
    return {"items": fotos, "moods": list(gem.MOOD_PRESETS.keys()),
            "moods_desc": gem.MOOD_PRESETS}


@router.post("/{empresa_id}/ai/generar-miniatura-gemini")
async def ai_miniatura_gemini(
    empresa_id: int,
    payload: GeminiBasePayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    # Obtener foto base
    row = (await db.execute(text("""
        SELECT archivo FROM fotos_base_daniel WHERE id = :id AND empresa_id = 5
    """), {"id": payload.foto_base_id})).first()
    if not row:
        raise HTTPException(404, "Foto base no encontrada")
    foto_path = gem.get_path_foto_base(row[0])

    try:
        result = await gem.generate_with_base(
            db, str(foto_path), payload.headline,
            kicker=payload.kicker, badge=payload.badge,
            mood=payload.mood, aspect=payload.aspect,
            articulo_id=payload.articulo_id,
            generado_por_id=user.id,
        )
        await gem.incrementar_uso(db, payload.foto_base_id)
        return result
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Gemini error: {e}")


@router.post("/{empresa_id}/ai/generar-miniatura-gemini-pura")
async def ai_miniatura_gemini_pura(
    empresa_id: int,
    payload: GeminiPurePayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    try:
        return await gem.generate_pure(
            db, payload.prompt, aspect=payload.aspect,
            articulo_id=payload.articulo_id, generado_por_id=user.id,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Gemini error: {e}")
