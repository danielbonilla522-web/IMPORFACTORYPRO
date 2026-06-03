"""
Routing por host para separar UI IMPORSHOP del ERP legacy.

CONTRATO (ver docs/IMPORSHOP_SEPARATION.md):
  - Si el request viene de imporshop.imporchina.com Y existe una variante
    bajo `frontend/templates/imporshop/<template>`, se sirve esa variante.
  - Sino, se sirve el template ERP legacy intacto.
  - El ERP queda CONGELADO: nunca se modifica desde este flujo.

Uso en main.py:
    from routing.host_resolver import render_for_host
    return render_for_host(templates, request, "clientes/index.html", {})

Es drop-in replacement de:
    return templates.TemplateResponse("clientes/index.html", {"request": request})

2026-05-14 multi-tenant: agregado resolve_tenant() que mapea host →
TenantContext via tabla subdominio_empresa. Permite agregar empresa N
(MX, CO, BR, white-label) sin deploy de codigo.
"""
from pathlib import Path
from functools import lru_cache
from typing import Optional
from fastapi import Request
from fastapi.templating import Jinja2Templates

# /home/ubuntu/sistema/backend/app/routing/host_resolver.py
#   parents[0] = routing
#   parents[1] = app
#   parents[2] = backend
#   parents[3] = sistema  -> aquí está frontend/templates
TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "templates"


# ════════════════════════════════════════════════════════════
# Tenant resolution (multi-tenant SaaS)
# ════════════════════════════════════════════════════════════

# Hosts que sirven la UI IMPORSHOP (NO el ERP legacy).
# Se popula al boot desde subdominio_empresa. Refrescable via _refresh_tenant_cache().
_IMPORSHOP_HOSTS_CACHE: set[str] = set()
_TENANT_CACHE: dict[str, "TenantContext"] = {}


def get_request_host(request: Request) -> str:
    """Source of truth del host de la request (X-Forwarded-Host > Host).

    Apache vhosts setean RequestHeader set X-Forwarded-Host. Si hay multiple
    proxies en cadena, el header puede venir como CSV ("host1, host2"). Tomamos
    el primer elemento (mas externo, el que recibio Apache del browser).

    Anti-spoof esta garantizado por iptables: solo Apache (127.0.0.1) puede
    llegar a uvicorn:8000 (DROP 0.0.0.0/0:8000).
    """
    fwd_raw = request.headers.get("x-forwarded-host", "").strip().lower()
    # Split CSV — multiple proxy chain, tomar el primero
    fwd_host = fwd_raw.split(",")[0].strip() if fwd_raw else ""
    host_raw = request.headers.get("host", "").strip().lower()
    host = host_raw.split(",")[0].strip() if host_raw else ""
    # Prioridad: X-Forwarded-Host (Apache lo setea), fallback Host directo
    return fwd_host or host or ""


def is_imporshop_host(request: Request) -> bool:
    """¿Este request viene de un subdominio registrado como IMPORSHOP?

    2026-05-14: ahora usa cache de hosts cargados desde subdominio_empresa
    en lugar de startswith("imporshop.") hardcoded. Eso permite agregar
    imporshopmx.imporchina.com, imporshopco.imporchina.com, etc.

    Fallback: si el cache no esta inicializado (boot), usar el patron legacy
    para no romper la primera request.
    """
    host = get_request_host(request)
    if not host:
        return False
    if _IMPORSHOP_HOSTS_CACHE:
        return host in _IMPORSHOP_HOSTS_CACHE
    # Fallback legacy si el cache aun no esta populado
    return host.startswith("imporshop")


def resolve_tenant(host: str) -> Optional["TenantContext"]:
    """Mapea un host -> TenantContext via cache poblado desde subdominio_empresa.

    Returns None si el host no esta registrado. El middleware decide si retornar
    404 o aplicar logica de fallback (ej. erp.imporchina.com no es tenant WMS,
    pero es valido para el ERP legacy).
    """
    if not host:
        return None
    return _TENANT_CACHE.get(host.lower())


def _refresh_tenant_cache(rows: list[dict]) -> None:
    """Llamado al boot (main.py @app.on_event('startup')) y al cambio de la tabla.

    Args:
        rows: lista de dicts con keys host, empresa_id, pais, moneda, locale,
              activa, impuesto_pct, impuesto_nombre, timezone.
    """
    from routing.tenant import TenantContext  # local import: rompe ciclo
    new_tenants: dict[str, TenantContext] = {}
    new_imporshop: set[str] = set()
    for r in rows:
        if not int(r.get("activa", 0) or 0):
            continue
        host = (r.get("host") or "").strip().lower()
        if not host:
            continue
        new_tenants[host] = TenantContext(
            empresa_id=int(r["empresa_id"]),
            host=host,
            pais=str(r.get("pais") or "EC"),
            moneda=str(r.get("moneda") or "USD"),
            locale=str(r.get("locale") or "es-EC"),
            impuesto_pct=float(r.get("impuesto_pct") or 0),
            impuesto_nombre=str(r.get("impuesto_nombre") or "IVA"),
            timezone=str(r.get("timezone") or "America/Guayaquil"),
            activa=True,
        )
        new_imporshop.add(host)
    _TENANT_CACHE.clear()
    _TENANT_CACHE.update(new_tenants)
    _IMPORSHOP_HOSTS_CACHE.clear()
    _IMPORSHOP_HOSTS_CACHE.update(new_imporshop)


async def reload_tenant_cache_from_db(db_session) -> int:
    """Recarga _TENANT_CACHE desde MySQL. Llamar al boot + tras INSERT/UPDATE
    de subdominio_empresa (futuro: admin UI).

    Tambien lee config regional (impuesto_pct, impuesto_nombre, timezone) desde
    empresa_config para enriquecer el TenantContext.

    Returns: numero de tenants cargados.
    """
    from sqlalchemy import text as _txt
    rows_raw = (await db_session.execute(_txt("""
        SELECT s.host, s.empresa_id, s.pais, s.moneda, s.locale, s.activa
        FROM subdominio_empresa s
        WHERE s.activa = 1
    """))).mappings().all()

    # Enriquecer con empresa_config para impuesto/timezone
    config_map: dict[int, dict] = {}
    if rows_raw:
        emp_ids = sorted({int(r["empresa_id"]) for r in rows_raw})
        # IDs son ints de DB → safe para inline (no SQL injection)
        ids_csv = ",".join(str(i) for i in emp_ids)
        cfg_rows = (await db_session.execute(_txt(f"""
            SELECT empresa_id, clave, valor
            FROM empresa_config
            WHERE empresa_id IN ({ids_csv})
              AND clave IN ('IMPUESTO_PCT','IMPUESTO_NOMBRE','TIMEZONE')
        """))).mappings().all()
        for c in cfg_rows:
            eid = int(c["empresa_id"])
            config_map.setdefault(eid, {})[c["clave"]] = c["valor"]

    enriched = []
    for r in rows_raw:
        d = dict(r)
        cfg = config_map.get(int(d["empresa_id"]), {})
        d["impuesto_pct"] = float(cfg.get("IMPUESTO_PCT") or 0)
        d["impuesto_nombre"] = cfg.get("IMPUESTO_NOMBRE") or "IVA"
        d["timezone"] = cfg.get("TIMEZONE") or "America/Guayaquil"
        enriched.append(d)
    _refresh_tenant_cache(enriched)
    return len(enriched)


@lru_cache(maxsize=512)
def _imporshop_variant_exists(shared_template: str) -> bool:
    """Cache: ¿existe la variante imporshop/<template>?

    Re-warm en cada restart de uvicorn (cache vive en memoria del proceso).
    Sin disco I/O después del primer hit por template.
    """
    return (TEMPLATES_DIR / "imporshop" / shared_template).exists()




# ════════════════════════════════════════════════════════════
# IMPORFACTORY Premium (impor.imporchina.com) — 2026-05-27
# Sistema de gestión interno paralelo al ERP legacy, con su propia
# carpeta de templates en frontend/templates/imporfactory_premium/.
# Igual contrato que IMPORSHOP: fallback a shared si la variante no existe.
# TODO(fase-2): migrar a tabla subdominio_empresa con columna template_prefix
# para soportar N tenants premium sin código nuevo.
# ════════════════════════════════════════════════════════════

_IMPORFACTORY_PREMIUM_HOSTS: set[str] = {'impor.imporchina.com'}


def is_imporfactory_premium_host(request: Request) -> bool:
    host = get_request_host(request)
    if not host:
        return False
    return host in _IMPORFACTORY_PREMIUM_HOSTS


@lru_cache(maxsize=512)
def _imporfactory_premium_variant_exists(shared_template: str) -> bool:
    return (TEMPLATES_DIR / 'imporfactory_premium' / shared_template).exists()


def resolve_template(request: Request, shared_template: str) -> str:
    """Decide qué template servir según host y disponibilidad de variante.

    Orden de prioridad:
      1. is_imporshop_host → imporshop/<template>
      2. is_imporfactory_premium_host → imporfactory_premium/<template>
      3. shared (ERP legacy)

    Si la variante específica del tenant no existe, fallback a shared.
    """
    if is_imporshop_host(request):
        if _imporshop_variant_exists(shared_template):
            return f"imporshop/{shared_template}"
        return shared_template
    if is_imporfactory_premium_host(request):
        if _imporfactory_premium_variant_exists(shared_template):
            return f"imporfactory_premium/{shared_template}"
        return shared_template
    return shared_template


def render_for_host(templates: Jinja2Templates, request: Request,
                    shared_template: str, context: dict | None = None):
    """Drop-in replacement de templates.TemplateResponse(...) con routing por host.

    Args:
        templates: instancia Jinja2Templates ya configurada en main.py
        request: FastAPI Request (para headers + Jinja context)
        shared_template: ruta relativa al template legacy (ej "clientes/index.html")
        context: dict adicional para el template (request se inyecta automáticamente)

    Returns:
        TemplateResponse renderizando la variante imporshop/* si aplica,
        sino el shared_template original.

    2026-05-14 multi-tenant: si la request tiene tenant resuelto en
    request.state.tenant (TenantMiddleware), se inyecta en el context Jinja
    como `tenant` para que los templates puedan renderear window.__APP_CONTEXT__.
    """
    ctx = context or {}
    final = resolve_template(request, shared_template)
    ctx.setdefault("request", request)
    ctx["__is_imporshop"] = is_imporshop_host(request)
    ctx["__is_imporfactory_premium"] = is_imporfactory_premium_host(request)
    ctx["__template_used"] = final  # útil para debug: visible en HTML como comment
    # Multi-tenant: pasar tenant al template si existe (no rompe templates legacy)
    tenant = getattr(request.state, "tenant", None) if hasattr(request, "state") else None
    if tenant is not None:
        ctx["tenant"] = tenant
    return templates.TemplateResponse(final, ctx)
