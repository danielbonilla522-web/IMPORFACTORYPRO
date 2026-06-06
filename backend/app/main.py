"""IMPORFACTORY Premium — main.py FINAL.

uvicorn :8001 — sirve impor.imporchina.com vía Apache proxy.

Sprints 1-17 IMPORFACTORY Premium consolidados aquí en repo separado:
- /clases (S4), /blog (S5+11), /blog/editor (S5+13), /finanzas (S3),
  /mensajeria (S7), /videos (S6), /dashboard (S1), / (landing S1)
- Generación AI Claude + Gemini + DALL-E (S5+8)
- Blog static HTML push a danytraveloficial.com + blog.imporfactory.com (S9+15)
- Tracker visitas público (S11)
- CTA Club + sección destacada home (S12+16)

Refactor 2026-06-03: separado del ERP. BD propia (imporfactory_premium).
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Hack para que los routers legacy puedan hacer `from core.security import ...`
APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Side-effect: registrar modelos (aunque shared, no afecta porque tabla es propia)
from models import imporfactory_premium as _imporfactory_premium_model  # noqa: F401

# Routers IMPORFACTORY
from api import reto
from api import facturacion
from api import imporfactory_clases
from api import imporfactory_blog
from api import imporfactory_blog_ai
from api import imporfactory_blog_gemini
from api import imporfactory_youtube
from api import imporfactory_finanzas
from api import imporfactory_mensajeria
from api import imporfactory_admin
from api import cobranzas_tv


# ────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"
UPLOADS_DIR = BASE_DIR / "uploads"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[IMPORFACTORY-PREMIUM] START puerto={os.getenv('PORT', '8001')}")
    print(f"  BD propia: {os.getenv('DB_NAME')}")
    print(f"  BD ERP ref: {os.getenv('ERP_DB_NAME')}")
    print(f"  Routers: 7 (clases, blog, blog_ai, blog_gemini, youtube, finanzas, mensajeria)")
    yield
    print("[IMPORFACTORY-PREMIUM] STOP")


app = FastAPI(
    title="IMPORFACTORY Premium",
    description="Sistema de gestión IMPORFACTORY — repo + proceso + BD separados",
    version="1.0.0",
    lifespan=lifespan,
)

# ────────────────────────────────────────
# Static mounts
# ────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# /uploads/blog/* público (miniaturas + fotos_base Daniel)
_uploads_blog = UPLOADS_DIR / "blog"
_uploads_blog.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/blog", StaticFiles(directory=str(_uploads_blog)), name="uploads-blog")


# ────────────────────────────────────────
# Helpers
# ────────────────────────────────────────

def _no_cache_html(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def render_premium(request: Request, template_name: str, ctx: dict | None = None):
    """Render template imporfactory_premium/{template_name}."""
    ctx = ctx or {}
    ctx["request"] = request
    return templates.TemplateResponse(request, f"imporfactory_premium/{template_name}", ctx)


# ────────────────────────────────────────
# Routers (incluye públicos /api/blog/public/* sin auth)
# ────────────────────────────────────────
app.include_router(reto.router)
app.include_router(facturacion.router)
app.include_router(imporfactory_clases.router)
app.include_router(imporfactory_blog.router)
app.include_router(imporfactory_blog.public_router)
app.include_router(imporfactory_blog_ai.router)
app.include_router(imporfactory_blog_gemini.router)
app.include_router(imporfactory_youtube.router)
app.include_router(imporfactory_finanzas.router)
app.include_router(imporfactory_mensajeria.router)
app.include_router(imporfactory_admin.router)
app.include_router(cobranzas_tv.router)


# ────────────────────────────────────────
# Páginas web (HTML)
# ────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "service": "imporfactory-premium",
        "version": "1.0.0",
        "db_propia": os.getenv("DB_NAME"),
        "db_erp_ref": os.getenv("ERP_DB_NAME"),
        "routers": 7,
    }


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return _no_cache_html(render_premium(request, "landing/index.html"))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return _no_cache_html(render_premium(request, "dashboard/index.html", {"active_item": "dashboard"}))


@app.get("/finanzas", response_class=HTMLResponse)
async def finanzas(request: Request):
    return _no_cache_html(render_premium(request, "finanzas/dashboard.html", {"active_item": "finanzas"}))


@app.get("/clases", response_class=HTMLResponse)
async def clases(request: Request):
    return _no_cache_html(render_premium(request, "clases/lista.html", {"active_item": "clases"}))


@app.get("/blog", response_class=HTMLResponse)
async def blog(request: Request):
    return _no_cache_html(render_premium(request, "blog/articulos.html", {"active_item": "blog"}))


@app.get("/blog/editor", response_class=HTMLResponse)
@app.get("/blog/editor/{articulo_id}", response_class=HTMLResponse)
async def blog_editor(request: Request, articulo_id: int | None = None):
    return _no_cache_html(render_premium(request, "blog/editor.html",
                                          {"active_item": "blog", "articulo_id": articulo_id}))


@app.get("/mensajeria", response_class=HTMLResponse)
async def mensajeria(request: Request):
    return _no_cache_html(render_premium(request, "mensajeria/cola.html", {"active_item": "mensajeria"}))


@app.get("/videos", response_class=HTMLResponse)
async def videos(request: Request):
    return _no_cache_html(render_premium(request, "videos/index.html", {"active_item": "videos"}))


@app.get("/alumnos", response_class=HTMLResponse)
async def alumnos_page(request: Request):
    return _no_cache_html(render_premium(request, "alumnos/index.html", {"active_item": "alumnos"}))


@app.get("/cursos", response_class=HTMLResponse)
async def cursos_page(request: Request):
    return _no_cache_html(render_premium(request, "cursos/index.html", {"active_item": "cursos"}))


@app.get("/agendamiento", response_class=HTMLResponse)
async def agendamiento_page(request: Request):
    return _no_cache_html(render_premium(request, "agendamiento/index.html", {"active_item": "agendamiento"}))


@app.get("/configuracion", response_class=HTMLResponse)
async def configuracion_page(request: Request):
    return _no_cache_html(render_premium(request, "configuracion/index.html", {"active_item": "configuracion"}))


@app.get("/admin/formularios", response_class=HTMLResponse)
async def admin_formularios_page(request: Request):
    return _no_cache_html(render_premium(request, "admin/formularios.html", {"active_item": "admin_formularios"}))


@app.get("/proyeccion", response_class=HTMLResponse)
async def proyeccion_page(request: Request):
    return _no_cache_html(render_premium(request, "proyeccion/index.html", {
        "active_item": "proyeccion",
        "tv_key": os.environ.get("TV_COBRANZAS_KEY", ""),
    }))


@app.get("/tv/cobranzas", response_class=HTMLResponse)
async def tv_cobranzas(request: Request, key: str = ""):
    """Tablero TV de cobranzas — PÚBLICO protegido por clave (la tele lo abre sin login)."""
    expected = os.environ.get("TV_COBRANZAS_KEY", "")
    if not expected or key != expected:
        return HTMLResponse(
            '<body style="background:#0a0e1f;color:#94a3b8;font-family:system-ui;'
            'display:grid;place-items:center;height:100vh;margin:0">'
            '<div style="text-align:center"><div style="font-size:48px">🔒</div>'
            '<h1 style="font-weight:800">Acceso restringido</h1>'
            '<p>Este tablero requiere una clave válida.</p></div></body>',
            status_code=403,
        )
    return _no_cache_html(render_premium(request, "tv/cobranzas.html", {"tv_key": key}))


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Redirige al login del ERP — JWT compartido."""
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=https://erp.imporchina.com/?redirect=https://impor.imporchina.com/dashboard">')



# ════════════════════════════════════════════════════════════
# Reto Importador Rentable — PUBLICO (sin auth)
# ════════════════════════════════════════════════════════════

@app.get("/reto-importador-rentable", response_class=HTMLResponse)
@app.get("/reto", response_class=HTMLResponse)
async def reto_form(request: Request):
    return _no_cache_html(render_premium(request, "reto/form.html", {"year": __import__("datetime").datetime.now().year}))


@app.get("/certificado/{folio}", response_class=HTMLResponse)
async def reto_certificado(request: Request, folio: str):
    return _no_cache_html(render_premium(request, "reto/certificado.html"))



@app.get("/facturacion-masiva", response_class=HTMLResponse)
@app.get("/facturacion", response_class=HTMLResponse)
async def facturacion_masiva(request: Request):
    return _no_cache_html(render_premium(request, "facturacion/landing.html"))


@app.get("/formularios", response_class=HTMLResponse)
async def formularios_hub(request: Request):
    return _no_cache_html(render_premium(request, "formularios/hub_publico.html", {"active_item": "formularios"}))


@app.get("/formularios/factura", response_class=HTMLResponse)
async def formularios_factura(request: Request):
    return _no_cache_html(render_premium(request, "formularios/factura_publico.html", {"active_item": "formularios"}))
