"""
IMPORFACTORY Premium — Gemini 2.5 Flash Image (nano-banana) para miniaturas estilo Daniel.

Lee GEMINI_API_KEY de os.environ (.env). Soporta:
  - Edición con foto base (preserva la cara de Daniel)
  - Generación pura desde prompt
  - Multi-imagen como referencia visual

Persiste en blog_generaciones_ai con costo_usd (~$0.039 por imagen).

2026-06-03 Sprint 8 (post-Sprint 7).
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


UPLOADS_DIR = Path("/home/ubuntu/sistema/uploads/blog/miniaturas")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

FOTOS_BASE_DIR = Path("/home/ubuntu/sistema/uploads/blog/fotos_base_daniel")
FOTOS_BASE_DIR.mkdir(parents=True, exist_ok=True)

MODEL = "gemini-3.1-flash-image"   # nano-banana
COST_PER_IMAGE = 0.039  # USD aproximado


# ─────────────────────────────────────────────────────────────
# Master prompt template estilo "Daniel cabrón"
# ─────────────────────────────────────────────────────────────

STYLE_DANIEL = """STYLE REQUIREMENTS (mandatory — IMPORFACTORY brand):
- Dark navy + electric cyan color palette (#0B1426 background, #00BFFF accents and glow)
- Cinematic editorial lighting from above-left, dramatic shadows on subject
- Floating blue particles/sparks in the air around subject
- Volumetric depth of field bokeh in background
- High contrast premium magazine cover quality
- Subject's face must remain EXACTLY as in the reference photo — same identity, expression, glasses
- Subject wears dark sweater/shirt (preserve from reference)
- Premium photographic quality, not illustration"""

MOOD_PRESETS = {
    "bodega-productos": "Warehouse interior with shelves full of drones, headphones, gadgets and product boxes. Industrial blue lighting from overhead. Cargo boxes visible.",
    "puerto-contenedores": "International cargo port at dusk. Stacked shipping containers with Chinese flag visible. Cargo trucks and crane silhouettes. Atmospheric blue lighting.",
    "estudio-premium": "Premium studio backdrop with subtle gradient. Production lights from sides. Minimalist setup with floating UI elements.",
    "money-fuego": "Burning dollar bill in subject's hand, real fire and smoke. Background of factory chimneys and industrial machinery. Dramatic chiaroscuro lighting.",
    "alibaba-pantalla": "Phone or laptop screen with Alibaba/1688 interface glowing. Subject looking at device. Dark office with multiple monitors background.",
    "bodega-cajas": "Warehouse loading dock with stacked boxes labeled with Chinese characters. Forklifts blurred in background. Concrete floor with chalk lines.",
    "studio-neon": "Modern podcast studio with neon cyan strips, microphone, acoustic foam walls. Clean minimal setup.",
    "dropi-app": "Phone screen showing Dropi app with notifications popping up. Hands holding device. Soft natural light.",
}


def _get_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY no configurada en backend/.env")
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai SDK no instalado. pip install google-genai")
    return genai.Client(api_key=key)


def _build_prompt(headline: str, kicker: Optional[str], badge: Optional[str],
                  mood: str, aspect: str = "16:9") -> str:
    mood_desc = MOOD_PRESETS.get(mood, mood)  # si no es preset, usar literal
    parts = [
        f"Create a {aspect} YouTube/blog thumbnail using the attached reference photo of the person.",
        "",
        STYLE_DANIEL,
        "",
        "BACKGROUND/SCENE:",
        mood_desc,
        "",
        "TEXT OVERLAY (must be PERFECTLY LEGIBLE in Spanish, no spelling mistakes):",
    ]
    if kicker:
        parts.append(f'- KICKER (top area, small uppercase, cyan #00BFFF, Inter font 700 weight, with thin underline below): "{kicker.upper()}"')
    parts.append(f'- HEADLINE (bottom 1/3, MASSIVE Montserrat Black 900, white, drop shadow): "{headline}"')
    if badge:
        parts.append(f'- BADGE (top-right corner, red/orange accent with white text, small uppercase): "{badge.upper()}"')

    parts.extend([
        "",
        "Make the typography dramatic and dominant — like premium Netflix/YouTube top creators.",
        "Subject is in foreground, sharp focus. Background is atmospheric and contextual.",
        "Output: photorealistic, broadcast quality, ready for thumbnail upload.",
    ])
    return "\n".join(parts)


async def generate_with_base(
    db: AsyncSession,
    foto_base_path: str,
    headline: str,
    *,
    kicker: Optional[str] = None,
    badge: Optional[str] = None,
    mood: str = "bodega-productos",
    aspect: str = "16:9",
    articulo_id: Optional[int] = None,
    generado_por_id: Optional[int] = None,
) -> dict:
    """Edita foto base con Gemini 2.5 Flash Image — preserva cara de Daniel.

    Args:
        foto_base_path: ruta local a la foto base (PNG/JPG)
        headline: texto grande inferior
        kicker: texto pequeño superior (opcional)
        badge: badge esquina (opcional)
        mood: preset clave o descripción literal del fondo
        aspect: "16:9" (YouTube), "1:1" (Instagram), "9:16" (Reels)

    Returns: {url, cost_usd, generacion_id, duracion_ms}
    """
    client = _get_client()

    foto_base = Path(foto_base_path)
    if not foto_base.exists():
        raise RuntimeError(f"Foto base no encontrada: {foto_base_path}")

    prompt = _build_prompt(headline, kicker, badge, mood, aspect)

    # Cargar imagen como bytes
    img_bytes = foto_base.read_bytes()
    mime_type = "image/png" if foto_base.suffix.lower() == ".png" else "image/jpeg"

    t0 = time.time()
    # Usar PIL Image como input para Gemini
    from PIL import Image
    import io
    img_pil = Image.open(io.BytesIO(img_bytes))

    resp = client.models.generate_content(
        model=MODEL,
        contents=[prompt, img_pil],
    )
    duracion_ms = int((time.time() - t0) * 1000)

    # Extraer imagen generada
    out_bytes = None
    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            out_bytes = part.inline_data.data
            break
    if out_bytes is None:
        raise RuntimeError("Gemini no devolvió imagen — respuesta solo texto")

    if isinstance(out_bytes, str):
        out_bytes = base64.b64decode(out_bytes)

    # Guardar local
    filename = f"gemini-{uuid.uuid4().hex}.png"
    out_path = UPLOADS_DIR / filename
    out_path.write_bytes(out_bytes)

    public_url = f"/uploads/blog/miniaturas/{filename}"

    # Persistir auditoría
    gen_res = await db.execute(text("""
        INSERT INTO blog_generaciones_ai
            (articulo_id, tipo, prompt, modelo_usado, parametros_json,
             resultado_url, costo_usd, duracion_ms, generado_por_id)
        VALUES
            (:aid, 'miniatura', :prompt, :model, :params,
             :url, :cost, :dur, :uid)
    """), {
        "aid": articulo_id, "prompt": prompt[:8000], "model": MODEL,
        "params": json.dumps({"mood": mood, "headline": headline, "kicker": kicker,
                              "badge": badge, "aspect": aspect,
                              "foto_base": foto_base.name}),
        "url": public_url, "cost": COST_PER_IMAGE, "dur": duracion_ms, "uid": generado_por_id,
    })
    await db.commit()

    return {
        "url": public_url,
        "cost_usd": COST_PER_IMAGE,
        "duracion_ms": duracion_ms,
        "generacion_id": gen_res.lastrowid,
        "prompt_usado": prompt,
    }


async def generate_pure(
    db: AsyncSession,
    prompt: str,
    *,
    aspect: str = "16:9",
    articulo_id: Optional[int] = None,
    generado_por_id: Optional[int] = None,
) -> dict:
    """Genera imagen desde cero (sin foto base) con Gemini."""
    client = _get_client()
    full_prompt = f"{STYLE_DANIEL}\n\n{prompt}\n\nAspect ratio: {aspect}"

    t0 = time.time()
    resp = client.models.generate_content(model=MODEL, contents=[full_prompt])
    duracion_ms = int((time.time() - t0) * 1000)

    out_bytes = None
    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            out_bytes = part.inline_data.data
            break
    if out_bytes is None:
        raise RuntimeError("Gemini no devolvió imagen")
    if isinstance(out_bytes, str):
        out_bytes = base64.b64decode(out_bytes)

    filename = f"gemini-{uuid.uuid4().hex}.png"
    out_path = UPLOADS_DIR / filename
    out_path.write_bytes(out_bytes)
    public_url = f"/uploads/blog/miniaturas/{filename}"

    gen_res = await db.execute(text("""
        INSERT INTO blog_generaciones_ai
            (articulo_id, tipo, prompt, modelo_usado,
             resultado_url, costo_usd, duracion_ms, generado_por_id)
        VALUES
            (:aid, 'miniatura', :prompt, :model,
             :url, :cost, :dur, :uid)
    """), {
        "aid": articulo_id, "prompt": full_prompt[:8000], "model": MODEL,
        "url": public_url, "cost": COST_PER_IMAGE, "dur": duracion_ms, "uid": generado_por_id,
    })
    await db.commit()

    return {
        "url": public_url,
        "cost_usd": COST_PER_IMAGE,
        "duracion_ms": duracion_ms,
        "generacion_id": gen_res.lastrowid,
    }


# ─────────────────────────────────────────────────────────────
# Banco de fotos base de Daniel
# ─────────────────────────────────────────────────────────────

async def ensure_table(db: AsyncSession):
    """Idempotente: crea tabla fotos_base_daniel si no existe."""
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS fotos_base_daniel (
            id INT AUTO_INCREMENT PRIMARY KEY,
            empresa_id INT NOT NULL DEFAULT 5,
            label VARCHAR(120) NOT NULL,
            descripcion TEXT NULL,
            archivo VARCHAR(220) NOT NULL,
            url VARCHAR(500) NOT NULL,
            tags JSON NULL,
            es_default TINYINT(1) NOT NULL DEFAULT 0,
            usos INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX ix_fbd_empresa (empresa_id),
            UNIQUE KEY uq_fbd_archivo (archivo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Banco de fotos base de Daniel para Gemini editing'
    """))
    await db.commit()


async def listar_fotos_base(db: AsyncSession) -> list[dict]:
    await ensure_table(db)
    rows = (await db.execute(text("""
        SELECT id, label, descripcion, archivo, url, tags, es_default, usos, created_at
        FROM fotos_base_daniel
        WHERE empresa_id = 5
        ORDER BY es_default DESC, usos DESC, created_at DESC
    """))).mappings().all()
    return [dict(r) for r in rows]


async def registrar_foto_base(db: AsyncSession, *, archivo: str, label: str,
                                descripcion: Optional[str] = None,
                                tags: Optional[list] = None,
                                es_default: bool = False) -> int:
    await ensure_table(db)
    url = f"/uploads/blog/fotos_base_daniel/{archivo}"
    res = await db.execute(text("""
        INSERT IGNORE INTO fotos_base_daniel
            (empresa_id, label, descripcion, archivo, url, tags, es_default)
        VALUES (5, :label, :desc, :archivo, :url, :tags, :def)
    """), {
        "label": label, "desc": descripcion, "archivo": archivo, "url": url,
        "tags": json.dumps(tags or []), "def": 1 if es_default else 0,
    })
    await db.commit()
    return res.lastrowid


async def incrementar_uso(db: AsyncSession, foto_id: int):
    await db.execute(text("UPDATE fotos_base_daniel SET usos = usos + 1 WHERE id = :id"),
                     {"id": foto_id})
    await db.commit()


def get_path_foto_base(archivo: str) -> Path:
    return FOTOS_BASE_DIR / archivo
