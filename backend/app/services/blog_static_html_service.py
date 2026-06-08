"""
IMPORFACTORY Premium — Wrapper para generar HTML estatico del blog danytravel
desde el editor IMPORFACTORY (Sprint 9).

REUSO TOTAL: importa render_html() y rebuild_index() de /home/ubuntu/blog-danytravel/
generate_post.py (1061 lineas ya probadas en produccion, 44 posts publicados).

Adapta el formato BD (blog_articulos) al dict que render_html espera, escribe
el HTML, y reconstruye indices/categorias/sitemap/feed.

2026-06-03 Sprint 9.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unicodedata
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


GENERATE_POST_PATH = Path("/home/ubuntu/blog-danytravel/generate_post.py")
META_FILE = Path("/home/ubuntu/blog-danytravel/posts_meta.json")
POSTS_DIR = Path("/var/www/danytravel/blog/posts")
BLOG_DIR = Path("/var/www/danytravel/blog")

# Multi-dominio: cada blog tiene su raiz, URL publica, y SITE_URL para schema.org
DOMINIOS = {
    "danytravel": {
        "posts_dir": Path("/var/www/danytravel/blog/posts"),
        "blog_dir": Path("/var/www/danytravel/blog"),
        "site_url": "https://danytraveloficial.com",
        "blog_url": "https://danytraveloficial.com/blog",
    },
    "imporfactory": {
        "posts_dir": Path("/var/www/imporfactory-blog/blog/posts"),
        "blog_dir": Path("/var/www/imporfactory-blog/blog"),
        "site_url": "https://blog.imporfactory.com",
        "blog_url": "https://blog.imporfactory.com/blog",
    },
    "club": {
        "posts_dir": Path("/var/www/club-importadores/blog/posts"),
        "blog_dir": Path("/var/www/club-importadores/blog"),
        "site_url": "https://clubdeimportadoresoficial.com",
        "blog_url": "https://clubdeimportadoresoficial.com/blog",
    },
}


def _load_generator_module():
    """Importa generate_post.py como modulo (one-time, cached)."""
    if "blog_generator" in sys.modules:
        return sys.modules["blog_generator"]
    spec = importlib.util.spec_from_file_location("blog_generator", GENERATE_POST_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["blog_generator"] = mod
    spec.loader.exec_module(mod)
    return mod


def _slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    return re.sub(r"[-\s]+", "-", s)[:80]


def _md_to_sections(md: str) -> list[dict]:
    """Convierte markdown del editor IMPORFACTORY a la estructura sections que render_html espera.

    El editor produce MD con H2/H3. Lo parseamos a la estructura JSON que generate_post.py usa.
    """
    sections = []
    current_section = None
    current_sub = None

    lines = (md or "").split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            # H2
            if current_section:
                sections.append(current_section)
            current_section = {
                "h2": stripped[3:].strip(),
                "paragraphs": [],
                "h3_subsections": [],
            }
            current_sub = None
        elif stripped.startswith("### "):
            # H3 dentro de seccion
            if not current_section:
                current_section = {"h2": "", "paragraphs": [], "h3_subsections": []}
            current_sub = {"h3": stripped[4:].strip(), "paragraphs": []}
            current_section["h3_subsections"].append(current_sub)
        elif stripped.startswith("#"):
            # H1: ignorar, ya viene como title aparte
            continue
        else:
            # Parrafo
            target = current_sub if current_sub else current_section
            if not target:
                current_section = {"h2": "Introduccion", "paragraphs": [], "h3_subsections": []}
                target = current_section
            target.setdefault("paragraphs", []).append(stripped)

    if current_section:
        sections.append(current_section)

    return sections


async def get_articulo_for_render(db: AsyncSession, articulo_id: int) -> dict:
    """Adapta una fila de blog_articulos al formato dict que render_html() espera."""
    row = (await db.execute(text("""
        SELECT a.id, a.slug, a.titulo, a.subtitulo, a.contenido_md, a.miniatura_url,
               a.fecha_publicacion, a.seo_titulo, a.seo_descripcion, a.seo_keywords,
               a.faqs_json, a.tags, a.tiempo_lectura_min, a.autor_nombre_publico,
               c.slug AS categoria_slug
        FROM blog_articulos a
        LEFT JOIN blog_categorias c ON c.id = a.categoria_id
        WHERE a.id = :id
    """), {"id": articulo_id})).mappings().first()
    if not row:
        raise RuntimeError(f"Articulo {articulo_id} no encontrado")

    # Mapping categoria_slug del editor -> categoria_key del generador
    # blog_categorias.slug: importacion-china, ecommerce-cod, dropshipping, etc.
    # generate_post.py CATEGORIAS keys: importaciones, ecommerce, dropshipping, negocios, marketing
    CAT_MAP = {
        "importacion-china": "importaciones",
        "ecommerce-cod": "ecommerce",
        "dropshipping": "dropshipping",
        "casos-exito": "negocios",
        "noticias-comercio": "importaciones",
        "tendencias-producto": "marketing",
    }
    cat_key = CAT_MAP.get(row["categoria_slug"], "negocios")

    seo_keywords = row["seo_keywords"]
    if isinstance(seo_keywords, str):
        try: seo_keywords = json.loads(seo_keywords)
        except: seo_keywords = []
    faqs_json = row["faqs_json"]
    if isinstance(faqs_json, str):
        try: faqs_json = json.loads(faqs_json)
        except: faqs_json = []
    tags = row["tags"]
    if isinstance(tags, str):
        try: tags = json.loads(tags)
        except: tags = []

    md = row["contenido_md"] or ""
    sections = _md_to_sections(md)

    pub_iso = (row["fecha_publicacion"] or datetime.now(timezone.utc)).isoformat() if row["fecha_publicacion"] else datetime.now(timezone.utc).isoformat()

    # Generar fecha-slug compatible con generate_post.py
    pub_dt = row["fecha_publicacion"] or datetime.now(timezone.utc)
    date_prefix = pub_dt.strftime("%Y%m%d")
    full_slug = f"{date_prefix}-{row['slug']}"

    return {
        "slug": full_slug,
        "filename": f"{full_slug}.html",
        "categoria": cat_key,
        "topic": row["titulo"],
        "published_iso": pub_iso,
        "word_count": (len(md.split()) if md else 1500),
        "data": {
            "title_h1": row["titulo"],
            "meta_description": row["seo_descripcion"] or row["subtitulo"] or row["titulo"],
            "lead": row["subtitulo"] or md[:200],
            "tldr_bullets": [],
            "sections": sections,
            "tabla_comparativa": None,
            "faqs": (faqs_json or []) if isinstance(faqs_json, list) else [],
            "conclusion": "Si quieres ir mas profundo en este tema, escribime al WhatsApp o vamos paso a paso en la academia.",
            "tags": tags or (seo_keywords or [])[:10],
            "video_recomendado": None,
            "external_authority_mentions": [],
            "internal_link_hints": [],
        },
        "image_url": row["miniatura_url"],
    }


async def publish_to_danytravel(db: AsyncSession, articulo_id: int, target_dominio: str = "danytravel") -> dict:
    """Genera HTML estatico y lo escribe en /var/www/danytravel/blog/posts/.

    Retorna {url, path, indexes_rebuilt}.
    """
    if not GENERATE_POST_PATH.exists():
        raise RuntimeError(f"generate_post.py no encontrado en {GENERATE_POST_PATH}")

    mod = _load_generator_module()
    post = await get_articulo_for_render(db, articulo_id)

    # Cargar/actualizar posts_meta.json
    meta = mod.load_meta() if hasattr(mod, "load_meta") else {"posts": []}
    if "posts" not in meta:
        meta["posts"] = []

    # Si el slug ya existe, actualizamos; sino agregamos
    existing_idx = None
    for i, p in enumerate(meta["posts"]):
        if p.get("slug") == post["slug"]:
            existing_idx = i
            break
    meta_entry = {
        "slug": post["slug"],
        "filename": post["filename"],
        "categoria": post["categoria"],
        "topic": post["topic"],
        "title": post["data"]["title_h1"],
        "meta_description": post["data"]["meta_description"],
        "published_iso": post["published_iso"],
        "word_count": post["word_count"],
    }
    if existing_idx is not None:
        meta["posts"][existing_idx] = meta_entry
    else:
        meta["posts"].append(meta_entry)

    # Renderizar HTML
    try:
        html = mod.render_html(post, meta)
    except Exception as e:
        raise RuntimeError(f"render_html fallo: {type(e).__name__}: {e}")

    # Escribir archivo
    domconf = DOMINIOS.get(target_dominio, DOMINIOS["danytravel"])
    domconf["posts_dir"].mkdir(parents=True, exist_ok=True)
    out_path = domconf["posts_dir"] / post["filename"]
    out_path.write_text(html, encoding="utf-8")

    # Guardar meta
    if hasattr(mod, "save_meta"):
        mod.save_meta(meta)

    # Reconstruir indices (index.html, categorias, sitemap.xml, feed.xml)
    indexes_rebuilt = False
    if hasattr(mod, "rebuild_index"):
        try:
            mod.rebuild_index(meta)
            indexes_rebuilt = True
        except Exception as e:
            # Logueo pero no fallo — el post ya esta escrito
            print(f"WARN rebuild_index fallo: {e}", file=sys.stderr)

    # Persistir en blog_articulos el path del HTML generado (canonical por dominio)
    public_url = f"{domconf['site_url']}/blog/posts/{post['filename']}"
    await db.execute(text("""
        UPDATE blog_articulos
        SET seo_canonical_url = :url
        WHERE id = :id
    """), {"url": public_url, "id": articulo_id})
    await db.commit()

    return {
        "ok": True,
        "url": public_url,
        "path": str(out_path),
        "indexes_rebuilt": indexes_rebuilt,
        "slug": post["slug"],
        "word_count": post["word_count"],
    }
