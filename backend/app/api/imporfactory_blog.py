"""
IMPORFACTORY Premium — Router CRUD de Blog editorial.

Endpoints /api/imporfactory/blog/{empresa_id}/...
+ rutas públicas /api/blog/public/* (sitemap, feed, detalle articulo público).

2026-05-27 Sprint 5.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.models import Usuario


router = APIRouter(prefix="/api/imporfactory/blog", tags=["imporfactory-blog"])
public_router = APIRouter(prefix="/api/blog/public", tags=["imporfactory-blog-public"])


def _ensure_empresa_5(empresa_id: int):
    if empresa_id != 5:
        raise HTTPException(403, "Solo empresa_id=5 (IMPORFACTORY)")


def slugify(s: str) -> str:
    """Genera slug-amigable de un título."""
    s = (s or "").lower()
    s = re.sub(r"[áàä]", "a", s)
    s = re.sub(r"[éèë]", "e", s)
    s = re.sub(r"[íìï]", "i", s)
    s = re.sub(r"[óòö]", "o", s)
    s = re.sub(r"[úùü]", "u", s)
    s = re.sub(r"ñ", "n", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:120] or "articulo"


def md_to_html(md: str) -> str:
    """Convierte markdown a HTML usando markdown library."""
    try:
        import markdown
        return markdown.markdown(md or "", extensions=["fenced_code", "tables", "toc", "nl2br"])
    except Exception:
        return md or ""


def _tiempo_lectura(md: str) -> int:
    palabras = len((md or "").split())
    return max(1, round(palabras / 200))


# ════════════════════════════════════════════════════════════
# CRUD ARTICULOS (admin)
# ════════════════════════════════════════════════════════════

class CrearArticuloPayload(BaseModel):
    titulo: str
    subtitulo: Optional[str] = None
    categoria_id: Optional[int] = None
    contenido_md: Optional[str] = ""


@router.get("/{empresa_id}/articulos")
async def listar_articulos(
    empresa_id: int,
    estado: Optional[str] = None,
    categoria_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    where = "WHERE a.empresa_id = 5"
    params = {"limit": limit}
    if estado:
        where += " AND a.estado = :estado"
        params["estado"] = estado
    if categoria_id:
        where += " AND a.categoria_id = :cat"
        params["cat"] = categoria_id
    if search:
        where += " AND (a.titulo LIKE :s OR a.subtitulo LIKE :s)"
        params["s"] = f"%{search}%"

    rows = (await db.execute(text(f"""
        SELECT a.id, a.slug, a.titulo, a.subtitulo, a.estado, a.fecha_publicacion,
               a.miniatura_url, a.vistas, a.tiempo_lectura_min,
               a.llm_optimization_score, a.generado_con_ai, a.revisado_humano,
               c.nombre AS categoria_nombre, c.slug AS categoria_slug, c.color AS categoria_color
        FROM blog_articulos a
        LEFT JOIN blog_categorias c ON c.id = a.categoria_id
        {where}
        ORDER BY a.updated_at DESC
        LIMIT :limit
    """), params)).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.post("/{empresa_id}/articulos")
async def crear_articulo(
    empresa_id: int,
    payload: CrearArticuloPayload,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    slug = slugify(payload.titulo)
    # Garantizar unicidad
    exists = (await db.execute(text("SELECT id FROM blog_articulos WHERE slug = :s"), {"s": slug})).first()
    if exists:
        slug = f"{slug}-{int(datetime.now().timestamp())}"

    md = payload.contenido_md or ""
    html = md_to_html(md)

    res = await db.execute(text("""
        INSERT INTO blog_articulos
            (empresa_id, slug, titulo, subtitulo, contenido_md, contenido_html,
             autor_id, categoria_id, estado, tiempo_lectura_min)
        VALUES
            (5, :slug, :titulo, :subtitulo, :md, :html,
             :autor, :cat, 'borrador', :tiempo)
    """), {
        "slug": slug, "titulo": payload.titulo, "subtitulo": payload.subtitulo,
        "md": md, "html": html, "autor": user.id,
        "cat": payload.categoria_id, "tiempo": _tiempo_lectura(md),
    })
    await db.commit()
    return {"ok": True, "id": res.lastrowid, "slug": slug}


@router.get("/{empresa_id}/articulos/{articulo_id}")
async def detalle_articulo(
    empresa_id: int,
    articulo_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    row = (await db.execute(text("""
        SELECT a.*, c.nombre AS categoria_nombre, c.color AS categoria_color
        FROM blog_articulos a
        LEFT JOIN blog_categorias c ON c.id = a.categoria_id
        WHERE a.id = :id
    """), {"id": articulo_id})).mappings().first()
    if not row:
        raise HTTPException(404, "Articulo no encontrado")

    # Historial AI generaciones
    gens = (await db.execute(text("""
        SELECT id, tipo, modelo_usado, costo_usd, tokens_input, tokens_output,
               duracion_ms, generado_en, aceptado
        FROM blog_generaciones_ai
        WHERE articulo_id = :id
        ORDER BY generado_en DESC LIMIT 50
    """), {"id": articulo_id})).mappings().all()

    return {**dict(row), "generaciones_ai": [dict(g) for g in gens]}


@router.put("/{empresa_id}/articulos/{articulo_id}")
async def editar_articulo(
    empresa_id: int,
    articulo_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)

    safe = {"titulo", "subtitulo", "contenido_md", "categoria_id", "miniatura_url",
            "miniatura_alt", "seo_titulo", "seo_descripcion", "seo_keywords",
            "seo_canonical_url", "seo_og_image", "schema_org",
            "llm_optimization_score", "tags", "faqs_json", "referencias_json",
            "revisado_humano", "generado_con_ai", "autor_nombre_publico"}
    upd = {k: v for k, v in payload.items() if k in safe}
    if not upd:
        raise HTTPException(400, "Nada que actualizar")

    # Si cambió contenido_md, regenerar html + tiempo_lectura
    if "contenido_md" in upd:
        upd["contenido_html"] = md_to_html(upd["contenido_md"])
        upd["tiempo_lectura_min"] = _tiempo_lectura(upd["contenido_md"])

    # Serialize JSON fields
    import json as _json
    for f in ["seo_keywords", "schema_org", "tags", "faqs_json", "referencias_json"]:
        if f in upd and not isinstance(upd[f], (str, type(None))):
            upd[f] = _json.dumps(upd[f])

    set_clauses = ", ".join([f"{k} = :{k}" for k in upd])
    upd["_id"] = articulo_id
    await db.execute(text(f"UPDATE blog_articulos SET {set_clauses} WHERE id = :_id"), upd)
    await db.commit()
    return {"ok": True}


@router.post("/{empresa_id}/articulos/{articulo_id}/publicar")
async def publicar_articulo(
    empresa_id: int,
    articulo_id: int,
    programar_para: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    fecha = programar_para or datetime.utcnow()
    estado = "programado" if programar_para and programar_para > datetime.utcnow() else "publicado"
    await db.execute(text("""
        UPDATE blog_articulos SET estado = :est, fecha_publicacion = :f
        WHERE id = :id
    """), {"est": estado, "f": fecha, "id": articulo_id})
    await db.commit()
    return {"ok": True, "estado": estado, "fecha": fecha.isoformat()}


@router.post("/{empresa_id}/articulos/{articulo_id}/archivar")
async def archivar_articulo(
    empresa_id: int,
    articulo_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    await db.execute(text("UPDATE blog_articulos SET estado='archivado' WHERE id = :id"), {"id": articulo_id})
    await db.commit()
    return {"ok": True}


@router.get("/{empresa_id}/categorias")
async def listar_categorias(
    empresa_id: int,
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    _ensure_empresa_5(empresa_id)
    rows = (await db.execute(text("""
        SELECT id, slug, nombre, descripcion, icon, color, orden, activo
        FROM blog_categorias WHERE empresa_id = 5 AND activo = 1
        ORDER BY orden, nombre
    """))).mappings().all()
    return {"items": [dict(r) for r in rows]}


# ════════════════════════════════════════════════════════════
# PUBLICO (sin auth) — sitemap.xml, articulos individuales
# ════════════════════════════════════════════════════════════

@public_router.get("/sitemap.xml")
async def sitemap(request: Request, db: AsyncSession = Depends(get_db)):
    """Sitemap XML para Google. Solo artículos publicados."""
    rows = (await db.execute(text("""
        SELECT slug, fecha_publicacion, updated_at FROM blog_articulos
        WHERE empresa_id = 5 AND estado = 'publicado'
        ORDER BY fecha_publicacion DESC LIMIT 5000
    """))).mappings().all()

    base = "https://impor.imporchina.com/blog"
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml.append(f"<url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>")
    for r in rows:
        lastmod = (r.get("updated_at") or r.get("fecha_publicacion") or datetime.utcnow()).isoformat()
        xml.append(f"<url><loc>{base}/{r['slug']}</loc><lastmod>{lastmod}</lastmod><changefreq>weekly</changefreq></url>")
    xml.append("</urlset>")
    return Response("\n".join(xml), media_type="application/xml")


@public_router.get("/articulos")
async def listar_publico(
    categoria_slug: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Listado público paginado (para frontend / RSS)."""
    where = "WHERE a.estado='publicado'"
    params = {"limit": min(limit, 100), "offset": offset}
    if categoria_slug:
        where += " AND c.slug = :cat"
        params["cat"] = categoria_slug

    rows = (await db.execute(text(f"""
        SELECT a.slug, a.titulo, a.subtitulo, a.fecha_publicacion, a.miniatura_url,
               a.tiempo_lectura_min, a.autor_nombre_publico,
               c.nombre AS categoria, c.slug AS categoria_slug
        FROM blog_articulos a
        LEFT JOIN blog_categorias c ON c.id = a.categoria_id
        {where}
        ORDER BY a.fecha_publicacion DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    return {"items": [dict(r) for r in rows]}


@public_router.get("/articulos/{slug}")
async def detalle_publico(slug: str, db: AsyncSession = Depends(get_db)):
    """JSON detalle público de artículo."""
    row = (await db.execute(text("""
        SELECT a.slug, a.titulo, a.subtitulo, a.contenido_md, a.contenido_html,
               a.miniatura_url, a.miniatura_alt, a.autor_nombre_publico,
               a.fecha_publicacion, a.tiempo_lectura_min, a.seo_titulo,
               a.seo_descripcion, a.seo_keywords, a.seo_canonical_url,
               a.seo_og_image, a.schema_org, a.tags, a.faqs_json, a.referencias_json,
               c.nombre AS categoria, c.slug AS categoria_slug, c.color AS categoria_color
        FROM blog_articulos a
        LEFT JOIN blog_categorias c ON c.id = a.categoria_id
        WHERE a.slug = :slug AND a.estado = 'publicado'
    """), {"slug": slug})).mappings().first()
    if not row:
        raise HTTPException(404, "Articulo no encontrado")

    # Incrementar vistas (best-effort, no esperar)
    await db.execute(text("UPDATE blog_articulos SET vistas = vistas + 1 WHERE slug = :s"), {"s": slug})
    await db.commit()

    return dict(row)


# ════════════════════════════════════════════════════════════
# Sprint 9: Publicar HTML estatico al blog Dany Travel
# ════════════════════════════════════════════════════════════

from services import blog_static_html_service as static_html


@router.post("/{empresa_id}/articulos/{articulo_id}/publicar-estatico")
async def publicar_estatico(
    empresa_id: int,
    articulo_id: int,
    target_dominio: str = "danytravel",
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Genera HTML estatico SEO completo. target_dominio: danytravel | imporfactory."""
    _ensure_empresa_5(empresa_id)
    await db.execute(text("""
        UPDATE blog_articulos
        SET estado = CASE WHEN estado='publicado' THEN estado ELSE 'publicado' END,
            fecha_publicacion = COALESCE(fecha_publicacion, NOW())
        WHERE id = :id
    """), {"id": articulo_id})
    await db.commit()

    try:
        result = await static_html.publish_to_danytravel(db, articulo_id, target_dominio)
        return result
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Publicacion estatica fallo: {e}")



# ════════════════════════════════════════════════════════════
# Sprint 11: Tracking de visitas blog (beacon publico)
# ════════════════════════════════════════════════════════════

from fastapi.responses import Response as _Resp


@public_router.post("/track-view/{slug}")
@public_router.get("/track-view/{slug}")
async def track_view(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Beacon publico que cada HTML estatico llama al cargar.
    Incrementa contador en blog_articulos + tabla diaria.
    Responde 204 sin contenido (rapido, no cachable).
    """
    # Buscar articulo por slug (puede venir con o sin prefijo de fecha)
    row = (await db.execute(text("""
        SELECT id FROM blog_articulos
        WHERE empresa_id = 5 AND (slug = :s OR slug = :s2 OR seo_canonical_url LIKE :url)
        LIMIT 1
    """), {"s": slug, "s2": slug[9:] if len(slug) > 9 and slug[:8].isdigit() else slug,
           "url": f"%/{slug}.html"})).first()
    if not row:
        return _Resp(status_code=204)
    articulo_id = row[0]

    # Incremento total + vistas_30d
    await db.execute(text("""
        UPDATE blog_articulos
        SET vistas = vistas + 1, vistas_30d = vistas_30d + 1
        WHERE id = :id
    """), {"id": articulo_id})

    # Upsert visita diaria
    await db.execute(text("""
        INSERT INTO blog_visitas_diarias (articulo_id, fecha, visitas)
        VALUES (:id, CURDATE(), 1)
        ON DUPLICATE KEY UPDATE visitas = visitas + 1
    """), {"id": articulo_id})

    await db.commit()
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate"}
    return _Resp(status_code=204, headers=headers)


# ════════════════════════════════════════════════════════════
# Stats blog para dashboard /blog (auth required)
# ════════════════════════════════════════════════════════════

@router.get("/{empresa_id}/stats")
async def blog_stats(
    empresa_id: int,
    dominio: str = "danytravel",
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """KPIs agregados del blog para dashboard."""
    _ensure_empresa_5(empresa_id)

    # Totales por estado
    estados = (await db.execute(text("""
        SELECT estado, COUNT(*) AS n FROM blog_articulos
        WHERE empresa_id = 5 AND target_dominio = :d
        GROUP BY estado
    """), {"d": dominio})).mappings().all()

    # Vistas totales + del mes
    vistas_total = (await db.execute(text("""
        SELECT COALESCE(SUM(vistas), 0) FROM blog_articulos
        WHERE empresa_id = 5 AND target_dominio = :d
    """), {"d": dominio})).scalar() or 0

    vistas_hoy = (await db.execute(text("""
        SELECT COALESCE(SUM(visitas), 0) FROM blog_visitas_diarias v
        JOIN blog_articulos a ON a.id = v.articulo_id
        WHERE a.empresa_id = 5 AND a.target_dominio = :d AND v.fecha = CURDATE()
    """), {"d": dominio})).scalar() or 0

    vistas_mes = (await db.execute(text("""
        SELECT COALESCE(SUM(visitas), 0) FROM blog_visitas_diarias v
        JOIN blog_articulos a ON a.id = v.articulo_id
        WHERE a.empresa_id = 5 AND a.target_dominio = :d
          AND v.fecha >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    """), {"d": dominio})).scalar() or 0

    miniaturas_status = (await db.execute(text("""
        SELECT
            SUM(CASE WHEN miniatura_url IS NOT NULL AND miniatura_url <> '' THEN 1 ELSE 0 END) AS con_mini,
            COUNT(*) AS total
        FROM blog_articulos
        WHERE empresa_id = 5 AND target_dominio = :d
    """), {"d": dominio})).mappings().first()

    return {
        "dominio": dominio,
        "totales_por_estado": [dict(r) for r in estados],
        "vistas_total": int(vistas_total),
        "vistas_hoy": int(vistas_hoy),
        "vistas_mes": int(vistas_mes),
        "con_miniatura": int(miniaturas_status["con_mini"] or 0),
        "total_articulos": int(miniaturas_status["total"] or 0),
    }


@router.get("/{empresa_id}/stats/timeseries")
async def stats_timeseries(
    empresa_id: int,
    dias: int = 30,
    dominio: str = "danytravel",
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Serie temporal de visitas diarias del blog (para chart)."""
    _ensure_empresa_5(empresa_id)
    rows = (await db.execute(text("""
        SELECT v.fecha, SUM(v.visitas) AS visitas
        FROM blog_visitas_diarias v
        JOIN blog_articulos a ON a.id = v.articulo_id
        WHERE a.empresa_id = 5 AND a.target_dominio = :d
          AND v.fecha >= DATE_SUB(CURDATE(), INTERVAL :n DAY)
        GROUP BY v.fecha
        ORDER BY v.fecha ASC
    """), {"d": dominio, "n": dias})).mappings().all()
    return {
        "series": [{"fecha": r["fecha"].isoformat(), "visitas": int(r["visitas"])} for r in rows]
    }


@router.get("/{empresa_id}/stats/top-posts")
async def top_posts(
    empresa_id: int,
    dias: int = 30,
    limit: int = 10,
    dominio: str = "danytravel",
    db: AsyncSession = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Top N posts mas vistos en los ultimos N dias."""
    _ensure_empresa_5(empresa_id)
    rows = (await db.execute(text("""
        SELECT a.id, a.slug, a.titulo, a.miniatura_url, a.seo_canonical_url,
               a.vistas AS vistas_all, COALESCE(SUM(v.visitas), 0) AS vistas_periodo,
               c.nombre AS categoria, c.color AS categoria_color
        FROM blog_articulos a
        LEFT JOIN blog_visitas_diarias v ON v.articulo_id = a.id
          AND v.fecha >= DATE_SUB(CURDATE(), INTERVAL :n DAY)
        LEFT JOIN blog_categorias c ON c.id = a.categoria_id
        WHERE a.empresa_id = 5 AND a.target_dominio = :d AND a.estado = 'publicado'
        GROUP BY a.id
        ORDER BY vistas_periodo DESC, vistas_all DESC
        LIMIT :limit
    """), {"d": dominio, "n": dias, "limit": limit})).mappings().all()
    return {"items": [dict(r) for r in rows]}

