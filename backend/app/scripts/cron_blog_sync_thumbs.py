#!/usr/bin/env python3
"""Cron auxiliar Blog Dany Travel: sync posts_meta.json -> blog_articulos
+ genera miniatura Gemini para posts sin miniatura.

Corre cada 15 min. Throttle 5 miniaturas por ejecución (max ~$0.20 por corrida).
No regenera HTML — la miniatura se aplicará a posts nuevos cuando Daniel los
edite/republique desde IMPORFACTORY. Para posts existentes solo persiste la
URL en BD (para reuso desde el editor).

2026-06-03 Sprint 10.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/sistema/backend/app")
from dotenv import load_dotenv
load_dotenv("/home/ubuntu/sistema/backend/.env")

from sqlalchemy import text
from core.database import AsyncSessionLocal
from services import gemini_images_service as gem


META_FILE = Path("/home/ubuntu/blog-danytravel/posts_meta.json")
MAX_THUMBS_PER_RUN = 5


import shutil

APACHE_THUMBS_DIR = Path("/var/www/danytravel/img/blog-thumbs")
PUBLIC_THUMBS_BASE = "https://danytraveloficial.com/img/blog-thumbs"
UPLOADS_SOURCE = Path("/home/ubuntu/sistema/uploads/blog/miniaturas")


def publish_thumb_to_apache(local_url: str) -> str:
    """Toma una URL tipo /uploads/blog/miniaturas/x.png o full impor URL,
    copia el archivo a /var/www/danytravel/img/blog-thumbs/, y devuelve
    la URL public (mismo dominio) servida por Apache. Idempotente."""
    if not local_url:
        return local_url
    # Detectar filename
    fname = local_url.rsplit("/", 1)[-1]
    if not fname:
        return local_url
    src_file = UPLOADS_SOURCE / fname
    if not src_file.exists():
        return local_url  # sin archivo origen, dejar URL como esta
    dst = APACHE_THUMBS_DIR / fname
    try:
        if not dst.exists():
            APACHE_THUMBS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst)
    except Exception:
        return local_url
    return f"{PUBLIC_THUMBS_BASE}/{fname}"


# Mapeo categoria -> (foto_base_id, mood_preset, kicker_default)
CAT_TO_THUMB = {
    "importaciones": (2, "puerto-contenedores", "IMPORTACIONES"),
    "ecommerce":     (1, "alibaba-pantalla",   "ECOMMERCE"),
    "dropshipping":  (5, "dropi-app",          "DROPSHIPPING"),
    "negocios":      (7, "bodega-productos",   "NEGOCIOS"),
    "marketing":     (6, "studio-neon",        "MARKETING DIGITAL"),
}

CAT_TO_BLOG_CAT_ID = {
    "importaciones": 1, "ecommerce": 2, "dropshipping": 12,
    "negocios": 13, "marketing": 14,
}


def short_headline(titulo: str, max_chars: int = 65) -> str:
    """Limpia titulo para headline. Gemini ya parte en 2 lineas si es largo."""
    titulo = titulo.replace(":", " —").strip()
    # Quitar prefijos como Como/Cómo si el titulo es muy largo
    if len(titulo) > max_chars:
        for prefix in ["Cómo ", "Como ", "Por qué ", "Por que ", "Qué ", "Que "]:
            if titulo.startswith(prefix):
                titulo = titulo[len(prefix):]
                titulo = titulo[0].upper() + titulo[1:]
                break
    # Cortar en limite duro solo si sigue muy largo (palabra completa)
    if len(titulo) > max_chars:
        cut = titulo[:max_chars].rsplit(" ", 1)[0]
        titulo = cut
    return titulo


async def sync_meta_to_db(db) -> int:
    """Inserta en blog_articulos los posts del meta JSON que falten."""
    if not META_FILE.exists():
        return 0
    posts = json.load(META_FILE.open())["posts"]
    existing = set((await db.execute(text("""
        SELECT seo_canonical_url FROM blog_articulos WHERE empresa_id = 5
    """))).scalars().all())
    nuevos = 0
    for p in posts:
        canonical = f"https://danytraveloficial.com/blog/posts/{p['slug']}.html"
        if canonical in existing:
            continue
        slug_clean = p["slug"][9:] if len(p["slug"]) > 9 and p["slug"][:8].isdigit() else p["slug"]
        cat_id = CAT_TO_BLOG_CAT_ID.get(p.get("categoria"), 13)
        try:
            pub_dt = datetime.fromisoformat(p["published_iso"].replace("Z", "+00:00"))
        except Exception:
            pub_dt = datetime.utcnow()
        word_count = int(p.get("word_count", 1500))
        try:
            await db.execute(text("""
                INSERT IGNORE INTO blog_articulos
                    (empresa_id, slug, titulo, subtitulo, estado, fecha_publicacion,
                     seo_descripcion, seo_canonical_url, tiempo_lectura_min,
                     categoria_id, generado_con_ai, revisado_humano, autor_nombre_publico)
                VALUES (5, :slug, :titulo, :sub, 'publicado', :pub, :desc, :url,
                        :reading, :cat, 1, 1, 'Daniel Bonilla')
            """), {
                "slug": slug_clean, "titulo": p["title"],
                "sub": (p.get("meta_description") or "")[:300],
                "pub": pub_dt, "desc": (p.get("meta_description") or "")[:300],
                "url": canonical, "reading": max(1, word_count // 200),
                "cat": cat_id,
            })
            nuevos += 1
        except Exception as e:
            print(f"SYNC_ERR {slug_clean[:40]}: {e}")
    await db.commit()
    return nuevos


async def generate_pending_thumbnails(db) -> dict:
    """Encuentra posts sin miniatura_url y genera con Gemini hasta MAX_THUMBS_PER_RUN."""
    rows = (await db.execute(text("""
        SELECT a.id, a.titulo, a.seo_canonical_url, c.slug AS cat_slug
        FROM blog_articulos a
        LEFT JOIN blog_categorias c ON c.id = a.categoria_id
        WHERE a.empresa_id = 5
          AND a.estado = 'publicado'
          AND (a.miniatura_url IS NULL OR a.miniatura_url = '')
        ORDER BY a.fecha_publicacion DESC
        LIMIT :n
    """), {"n": MAX_THUMBS_PER_RUN})).mappings().all()

    # Mapear cat_slug del editor -> categoria_key del generator
    GENERATOR_CAT = {
        "importacion-china": "importaciones", "ecommerce-cod": "ecommerce",
        "dropshipping": "dropshipping", "negocios": "negocios",
        "marketing": "marketing", "casos-exito": "negocios",
        "noticias-comercio": "importaciones", "tendencias-producto": "marketing",
    }

    generated = 0
    failed = 0
    total_cost = 0.0
    for r in rows:
        cat_key = GENERATOR_CAT.get(r["cat_slug"] or "", "negocios")
        foto_id, mood, kicker = CAT_TO_THUMB.get(cat_key, CAT_TO_THUMB["negocios"])
        foto_row = (await db.execute(text("""
            SELECT archivo FROM fotos_base_daniel WHERE id = :id
        """), {"id": foto_id})).first()
        if not foto_row:
            failed += 1
            continue
        foto_path = gem.get_path_foto_base(foto_row[0])
        headline = short_headline(r["titulo"])
        try:
            result = await gem.generate_with_base(
                db, str(foto_path), headline,
                kicker=kicker, mood=mood, aspect="16:9",
                articulo_id=r["id"], generado_por_id=1,
            )
            public_url = publish_thumb_to_apache(result["url"])
            await db.execute(text("""
                UPDATE blog_articulos SET miniatura_url = :u, miniatura_alt = :alt
                WHERE id = :id
            """), {"u": public_url, "alt": r["titulo"], "id": r["id"]})
            await gem.incrementar_uso(db, foto_id)
            await db.commit()
            generated += 1
            total_cost += float(result["cost_usd"])
        except Exception as e:
            print(f"THUMB_ERR id={r['id']}: {type(e).__name__}: {str(e)[:120]}")
            failed += 1
    return {"generated": generated, "failed": failed, "cost_usd": round(total_cost, 4)}




# Sprint 14 (2026-06-03): tras generar miniaturas, sincronizar posts_meta.json
# para que el rebuild_index del generador legacy use las miniaturas Gemini
async def sync_thumbs_to_meta_and_rebuild(db):
    import json, subprocess
    from pathlib import Path

    META = Path("/home/ubuntu/blog-danytravel/posts_meta.json")
    POSTS_DIR = Path("/var/www/danytravel/blog/posts")
    PUBLIC_BASE = "https://impor.imporchina.com"

    if not META.exists():
        return 0

    meta = json.load(META.open())
    posts = meta.get("posts", [])

    # Filtrar huerfanos (sin HTML real)
    posts = [p for p in posts if (POSTS_DIR / f"{p['slug']}.html").exists()]

    # Cargar miniaturas desde BD
    rows = (await db.execute(text("""
        SELECT slug, miniatura_url FROM blog_articulos
        WHERE empresa_id = 5 AND miniatura_url IS NOT NULL AND miniatura_url <> ''
    """))).mappings().all()
    thumb_map = {}
    for r in rows:
        u = r["miniatura_url"]
        if u and u.startswith("/"):
            u = PUBLIC_BASE + u
        thumb_map[r["slug"]] = u

    updated = 0
    for p in posts:
        slug_short = p["slug"][9:] if len(p["slug"]) > 9 and p["slug"][:8].isdigit() else p["slug"]
        if slug_short in thumb_map and p.get("image_url") != thumb_map[slug_short]:
            p["image_url"] = thumb_map[slug_short]
            updated += 1

    meta["posts"] = posts
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    # Rebuild index/categorias/sitemap/feed si hubo updates
    if updated > 0:
        try:
            subprocess.run(
                ["/home/ubuntu/sistema/backend/venv/bin/python3",
                 "/home/ubuntu/blog-danytravel/generate_post.py",
                 "--rebuild-index"],
                timeout=90, check=False, capture_output=True,
            )
        except Exception:
            pass
        # Re-inyectar seccion 'Lo ultimo del blog' en la home principal
        try:
            subprocess.run(
                ["sudo", "/home/ubuntu/sistema/backend/venv/bin/python3",
                 "/home/ubuntu/blog-danytravel/inject_blog_home_section.py"],
                timeout=30, check=False, capture_output=True,
            )
        except Exception:
            pass
    return updated


async def main():
    async with AsyncSessionLocal() as db:
        nuevos = await sync_meta_to_db(db)
        thumbs = await generate_pending_thumbnails(db)
        meta_updated = await sync_thumbs_to_meta_and_rebuild(db)
        thumbs["meta_updated"] = meta_updated or 0
    print(f"[blog-sync-thumbs] sync_nuevos={nuevos} thumbs_gen={thumbs['generated']} "
          f"failed={thumbs['failed']} cost=${thumbs['cost_usd']}")


if __name__ == "__main__":
    asyncio.run(main())
