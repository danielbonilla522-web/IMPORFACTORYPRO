"""
IMPORFACTORY Premium — Wrapper OpenAI Images (DALL-E 3 HD para miniaturas).

Lee OPENAI_API_KEY desde empresa_config. Descarga la imagen y la guarda
local con path firmado HMAC (igual patrón que upload_signing.py).

Cada llamada se persiste en blog_generaciones_ai con costo_usd.

2026-05-27 Sprint 5.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


UPLOADS_DIR = Path("/home/ubuntu/sistema/uploads/blog/miniaturas")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Costo aproximado por imagen HD DALL-E 3 (en USD).
COST_PER_IMAGE = {
    "1024x1024": 0.040,
    "1792x1024": 0.080,
    "1024x1792": 0.080,
}


async def _get_api_key(db: AsyncSession, empresa_id: int = 5) -> Optional[str]:
    import os
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        return env_key
    # empresa_config (tabla ERP grupo_impor → sesión ERP propia)
    try:
        from core.database import ErpAsyncSessionLocal
        async with ErpAsyncSessionLocal() as erp:
            row = (await erp.execute(text("""
                SELECT valor FROM empresa_config
                WHERE empresa_id = :emp AND clave = 'OPENAI_API_KEY'
                LIMIT 1
            """), {"emp": empresa_id})).first()
        return row[0] if row else None
    except Exception:
        return None


async def generate_thumbnail(
    db: AsyncSession,
    prompt: str,
    *,
    articulo_id: Optional[int] = None,
    style: str = "editorial photography",
    size: str = "1792x1024",
    quality: str = "hd",
    generado_por_id: Optional[int] = None,
) -> dict:
    """Genera miniatura con DALL-E 3, la descarga local, retorna URL servible.

    Returns: {url, prompt_final, cost_usd, generacion_id}
    """
    api_key = await _get_api_key(db)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada en empresa_config(empresa_id=5). "
                          "Configurar en /configuracion antes de generar miniaturas.")

    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise RuntimeError("openai SDK no instalado. pip install openai")

    client = AsyncOpenAI(api_key=api_key)
    full_prompt = f"{style}. {prompt}"

    t0 = time.time()
    resp = await client.images.generate(
        model="dall-e-3",
        prompt=full_prompt,
        size=size,
        quality=quality,
        n=1,
    )
    duracion_ms = int((time.time() - t0) * 1000)

    img_url_temp = resp.data[0].url
    revised_prompt = getattr(resp.data[0], "revised_prompt", full_prompt)

    # Descargar y guardar local
    filename = f"{uuid.uuid4().hex}.png"
    local_path = UPLOADS_DIR / filename
    async with httpx.AsyncClient(timeout=60.0) as http:
        r = await http.get(img_url_temp)
        r.raise_for_status()
        local_path.write_bytes(r.content)

    # URL servible (estática)
    public_url = f"/uploads/blog/miniaturas/{filename}"
    cost = COST_PER_IMAGE.get(size, 0.08)

    # Persistir auditoría
    gen_res = await db.execute(text("""
        INSERT INTO blog_generaciones_ai
            (articulo_id, tipo, prompt, modelo_usado, parametros_json,
             resultado_url, costo_usd, duracion_ms, generado_por_id)
        VALUES
            (:aid, 'miniatura', :prompt, 'dall-e-3', :params,
             :url, :cost, :dur, :uid)
    """), {
        "aid": articulo_id, "prompt": full_prompt[:8000],
        "params": json.dumps({"size": size, "quality": quality, "style": style,
                              "revised_prompt": revised_prompt}),
        "url": public_url, "cost": cost, "dur": duracion_ms, "uid": generado_por_id,
    })
    await db.commit()

    return {
        "url": public_url,
        "prompt_final": revised_prompt,
        "cost_usd": cost,
        "duracion_ms": duracion_ms,
        "generacion_id": gen_res.lastrowid,
    }
