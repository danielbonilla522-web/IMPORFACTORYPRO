#!/usr/bin/env python3
"""
IMPORFACTORY — Generación batch de blogs (Sprint 37).

Publica N blogs/día repartidos entre danytraveloficial.com y blog.imporfactory.com
(contenido único por dominio), los sincroniza a blog_articulos (para que el tracking
de visitas/clicks y el dashboard de embudo los vean), y notifica al grupo de WhatsApp
"project manager" vía Jeff (cola whatsapp_queue del ERP).

Uso:
  cron_blog_batch.py --count 20            # 10 danytravel + 10 imporfactory
  cron_blog_batch.py --count 6 --dry-run   # preview sin escribir ni notificar

Corre con el venv de premium. Lanza generate_post.py con el venv de sistema.
Cron sugerido (arranque gradual): /etc/cron.d/blog-batch
  0 13 * * * ubuntu <premium_venv> <este_script> --count 20 >> /var/log/blog_batch.log 2>&1
2026-06-07.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Cargar .env de premium ──
ENV = "/home/ubuntu/imporfactory-premium/backend/.env"
for _l in open(ENV):
    _l = _l.strip()
    if not _l or _l.startswith("#") or "=" not in _l:
        continue
    _k, _v = _l.split("=", 1)
    _v = _v.strip()
    if len(_v) >= 2 and _v[0] in ("\"", "'") and _v[-1] == _v[0]:
        _v = _v[1:-1]
    os.environ.setdefault(_k.strip(), _v)

sys.path.insert(0, "/home/ubuntu/imporfactory-premium/backend")
from sqlalchemy import text  # noqa: E402
from app.core.database import AsyncSessionLocal, ErpAsyncSessionLocal  # noqa: E402

GENERATE_POST = "/home/ubuntu/blog-danytravel/generate_post.py"
GEN_VENV = "/home/ubuntu/sistema/backend/venv/bin/python"
META = {
    "danytravel": "/home/ubuntu/blog-danytravel/posts_meta.json",
    "imporfactory": "/home/ubuntu/blog-danytravel/posts_meta_imporfactory.json",
    "club": "/home/ubuntu/blog-danytravel/posts_meta_club.json",
}
SITE = {
    "danytravel": "https://danytraveloficial.com",
    "imporfactory": "https://blog.imporfactory.com",
    "club": "https://clubdeimportadoresoficial.com",
}
CAT_TO_BLOG_CAT_ID = {
    "importaciones": 1, "ecommerce": 2, "dropshipping": 12,
    "negocios": 13, "marketing": 14,
}


def log(m: str):
    print(f"[blog-batch {datetime.utcnow():%H:%M:%S}] {m}", flush=True)


def generar(dominio: str, count: int, dry: bool) -> bool:
    """Lanza generate_post.py para un dominio. Devuelve True si OK."""
    cmd = [GEN_VENV, GENERATE_POST, "--count", str(count), "--dominio", dominio]
    if dry:
        cmd.append("--dry-run")
    log(f"generando {count} -> {dominio}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            log(f"  ERR {dominio}: {(r.stderr or r.stdout)[-300:]}")
            return False
        log(f"  OK {dominio}: {(r.stdout or '').strip().splitlines()[-1] if r.stdout.strip() else 'sin salida'}")
        return True
    except Exception as e:
        log(f"  EXC {dominio}: {e}")
        return False


async def sync_meta(db, dominio: str) -> int:
    """Sincroniza posts del meta del dominio a blog_articulos con target_dominio."""
    mf = Path(META[dominio])
    if not mf.exists():
        return 0
    posts = json.load(mf.open()).get("posts", [])
    existing = set((await db.execute(text(
        "SELECT seo_canonical_url FROM blog_articulos WHERE empresa_id = 5"
    ))).scalars().all())
    nuevos = 0
    for p in posts:
        canonical = f"{SITE[dominio]}/blog/posts/{p['slug']}.html"
        if canonical in existing:
            continue
        slug_clean = p["slug"][9:] if len(p["slug"]) > 9 and p["slug"][:8].isdigit() else p["slug"]
        cat_id = CAT_TO_BLOG_CAT_ID.get(p.get("categoria"), 13)
        try:
            pub_dt = datetime.fromisoformat(p["published_iso"].replace("Z", "+00:00"))
        except Exception:
            pub_dt = datetime.utcnow()
        wc = int(p.get("word_count", 1500))
        try:
            await db.execute(text("""
                INSERT IGNORE INTO blog_articulos
                    (empresa_id, slug, titulo, subtitulo, estado, fecha_publicacion,
                     seo_descripcion, seo_canonical_url, tiempo_lectura_min,
                     categoria_id, target_dominio, generado_con_ai, revisado_humano,
                     autor_nombre_publico)
                VALUES (5, :slug, :titulo, :sub, 'publicado', :pub, :desc, :url,
                        :reading, :cat, :dom, 1, 0, 'Daniel Bonilla')
            """), {
                "slug": slug_clean, "titulo": p["title"],
                "sub": (p.get("meta_description") or "")[:300],
                "pub": pub_dt, "desc": (p.get("meta_description") or "")[:300],
                "url": canonical, "reading": max(1, wc // 200),
                "cat": cat_id, "dom": dominio,
            })
            nuevos += 1
        except Exception as e:
            log(f"  SYNC_ERR {slug_clean[:40]}: {e}")
    await db.commit()
    return nuevos


async def notificar_jeff(total: int, n_dany: int, n_impor: int):
    """Encola mensaje al grupo 'project manager' vía whatsapp_queue del ERP."""
    jid = os.environ.get("JID_PROJECT_MANAGER", "").strip()
    if not jid:
        log("JID_PROJECT_MANAGER no configurado — se omite notificación Jeff")
        return False
    msg = (
        f"📰 *Blogs publicados hoy*: {total} nuevos\n"
        f"• danytraveloficial.com/blog → {n_dany}\n"
        f"• blog.imporfactory.com/blog → {n_impor}\n\n"
        f"Métricas (visitas, clicks CTA y embudo) en impor.imporchina.com/blog"
    )
    telefono = jid.split("@")[0]
    try:
        async with ErpAsyncSessionLocal() as db:
            await db.execute(text("""
                INSERT INTO whatsapp_queue
                    (empresa_id, telefono, jid, mensaje, wacli_store, scheduled_at,
                     estado, trigger_origen)
                VALUES (5, :tel, :jid, :msg, '/home/ubuntu/.wacli', NOW(),
                        'PENDIENTE', 'blog_batch')
            """), {"tel": telefono, "jid": jid, "msg": msg})
            await db.commit()
        log(f"Jeff notificado al grupo {jid}")
        return True
    except Exception as e:
        log(f"Jeff notify ERR: {e}")
        return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20, help="Total de blogs (se reparte 50/50 entre dominios)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--solo-dominio", choices=["danytravel", "imporfactory", "club"], help="Generar solo un dominio")
    args = ap.parse_args()

    if args.solo_dominio:
        plan = {args.solo_dominio: args.count}
    else:
        n_dany = args.count // 2 + args.count % 2
        n_impor = args.count // 2
        plan = {"danytravel": n_dany, "imporfactory": n_impor}

    log(f"INICIO batch count={args.count} plan={plan} dry={args.dry_run}")

    for dom, n in plan.items():
        if n > 0:
            generar(dom, n, args.dry_run)

    if args.dry_run:
        log("DRY-RUN: no se sincroniza ni notifica.")
        return

    # Sync a blog_articulos (para tracking/embudo) y contar nuevos por dominio
    async with AsyncSessionLocal() as db:
        n_dany = await sync_meta(db, "danytravel") if plan.get("danytravel") else 0
        n_impor = await sync_meta(db, "imporfactory") if plan.get("imporfactory") else 0
    total = n_dany + n_impor
    log(f"sync blog_articulos: danytravel={n_dany} imporfactory={n_impor} total={total}")

    if total > 0:
        await notificar_jeff(total, n_dany, n_impor)
    log("FIN batch")


if __name__ == "__main__":
    asyncio.run(main())
