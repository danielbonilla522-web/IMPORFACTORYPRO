#!/usr/bin/env python3
"""Generador de posts SEO para blog.danytraveloficial.com.

2026-05-14: Daniel pide blog diario con contenido SEO sobre importaciones,
ecommerce y dropshipping. Usa Claude haiku-4-5 con prompts especificos por
categoria. Genera HTML estatico con schema.org Article + JSON-LD + meta OG +
Twitter cards + canonical + breadcrumbs.

Tras generar el post:
- Actualiza index.html del blog (lista paginada de posts)
- Actualiza categorias/{slug}.html
- Actualiza sitemap.xml
- Actualiza feed.xml (RSS 2.0)

Uso:
    python3 generate_post.py                 # genera 1 post (categoria rotativa)
    python3 generate_post.py --categoria importaciones
    python3 generate_post.py --dry-run       # genera pero no escribe
    python3 generate_post.py --rebuild-index # regenera solo index/sitemap (no nuevo post)
"""
import argparse
import json
import os
import random
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: pip install anthropic", file=sys.stderr)
    sys.exit(1)

# ── Config ──
BLOG_DIR = Path("/var/www/danytravel/blog")
POSTS_DIR = BLOG_DIR / "posts"
CATS_DIR = BLOG_DIR / "categorias"
META_FILE = Path("/home/ubuntu/blog-danytravel/posts_meta.json")
LOG_FILE = Path("/home/ubuntu/blog-danytravel/generate.log")
SITE_URL = "https://danytraveloficial.com"
BLOG_URL = f"{SITE_URL}/blog"
WA_NUMBER = "593979120058"
YT_CHANNEL = "https://www.youtube.com/@danytravel4695"

# External links de autoridad por categoria (Google premia outbound a sites de calidad).
# Daniel puede ampliar esta lista en cualquier momento.
AUTHORITY_LINKS = {
    "importaciones": [
        ("Alibaba RFQ official guide", "https://help.alibaba.com/help/searchHelp.htm?source=ali_supplier"),
        ("SRI Ecuador — aranceles y FODINFA", "https://www.sri.gob.ec/"),
        ("Banco Central Ecuador — tipo de cambio", "https://www.bce.fin.ec/"),
        ("ICC — Incoterms 2020 oficial", "https://iccwbo.org/business-solutions/incoterms-rules/"),
        ("IATA — peso volumetrico aereo", "https://www.iata.org/en/programs/cargo/"),
        ("China Customs — reglas de exportacion", "http://english.customs.gov.cn/"),
    ],
    "ecommerce": [
        ("Shopify Learn — guias ecommerce", "https://www.shopify.com/learn"),
        ("Google Analytics 4 — para ecommerce", "https://support.google.com/analytics/answer/9267735"),
        ("Mercado Libre Vendedores", "https://www.mercadolibre.com.ec/vender"),
        ("Stripe Atlas — guia de pagos", "https://stripe.com/atlas/guides"),
        ("Baymard Institute — UX checkout", "https://baymard.com/research"),
    ],
    "dropshipping": [
        ("Dropi Ecuador — plataforma oficial", "https://app.dropi.ec/"),
        ("Meta Business Help — Ads dropshipping", "https://www.facebook.com/business/help"),
        ("TikTok Ads Manager", "https://ads.tiktok.com/business/es"),
        ("Shopify Dropshipping", "https://www.shopify.com/dropshipping"),
    ],
    "negocios": [
        ("SRI Ecuador — RUC y regimenes", "https://www.sri.gob.ec/web/guest/RUC"),
        ("Camara de Comercio de Quito", "https://www.lacamaradequito.com/"),
        ("Superintendencia de Companias Ecuador", "https://www.supercias.gob.ec/"),
        ("Harvard Business Review", "https://hbr.org/"),
    ],
    "marketing": [
        ("Meta Blueprint — cursos gratis", "https://www.facebook.com/business/learn"),
        ("Google Ads Skillshop", "https://skillshop.exceedlms.com/student/catalog"),
        ("Search Engine Land — SEO news", "https://searchengineland.com/"),
        ("HubSpot Marketing Blog", "https://blog.hubspot.com/marketing"),
    ],
}

CATEGORIAS = {
    "importaciones": {
        "label": "Importaciones desde China",
        "emoji": "🚢",
        "topics": [
            "como calcular el costo total de una importacion desde China paso a paso",
            "errores comunes al importar desde Alibaba que te hacen perder dinero",
            "diferencia entre flete maritimo y aereo: cuando conviene cada uno",
            "como negociar con proveedores chinos: 5 tecnicas comprobadas",
            "que es un Trade Assurance y por que protege tu importacion",
            "como elegir el courier correcto: DHL vs FedEx vs UPS vs Aliexpress Standard",
            "incoterms FOB vs CIF vs EXW explicados con ejemplos reales",
            "como calcular el CBM y por que afecta tu costo de flete",
            "checklist: que pedirle al proveedor chino antes de pagar",
            "como evitar productos falsificados o de mala calidad de China",
            "como abrir una cuenta en Alibaba o 1688 desde Ecuador",
            "guia completa de aranceles e impuestos para importar a Ecuador",
            "que es FODINFA y como afecta tu importacion en Ecuador",
            "como funcionan las consolidadoras de carga China-Ecuador",
            "muestra antes de comprar: como evitar perder $5000 en una orden",
            "RFQ en Alibaba: como pedir cotizaciones que valgan la pena",
            "tiempos de produccion + transito: cuanto tarda realmente tu importacion",
            "que tan riesgoso es importar electronicos desde China en 2026",
            "diferencia entre proveedor, fabrica y trading company en China",
            "como pagar a proveedores chinos: T/T vs Trade Assurance vs PayPal",
        ],
    },
    "ecommerce": {
        "label": "Ecommerce y ventas online",
        "emoji": "🛒",
        "topics": [
            "como elegir productos ganadores para vender en Ecuador en 2026",
            "Shopify vs Tiendanube vs Wix: cual elegir segun tu negocio",
            "errores que matan a un ecommerce nuevo en sus primeros 3 meses",
            "como calcular el precio de venta correcto sin perder margen",
            "metodos de pago en Ecuador para tu ecommerce: completar guia",
            "como redactar descripciones de producto que venden",
            "fotos de producto que multiplican tus ventas: tips practicos",
            "tasa de conversion: que es y como mejorarla en tu ecommerce",
            "ecommerce vs marketplace: cual estrategia te conviene mas",
            "como construir confianza en tu ecommerce desde el dia 1",
            "envios en Ecuador: como elegir courier para tu ecommerce",
            "checkout que convierte: 7 elementos imprescindibles",
            "abandono de carrito: causas y como recuperar esas ventas",
            "remarketing efectivo para ecommerce con bajo presupuesto",
            "que es el AOV (ticket promedio) y como aumentarlo",
            "fidelizar clientes: estrategias que cuestan poco y dan mucho",
            "ecommerce B2B vs B2C: diferencias clave y cual elegir",
            "como armar un funnel de ventas para ecommerce paso a paso",
            "Mercado Libre Ecuador: como vender mas y rankear primero",
            "vender por WhatsApp Business: guia completa para ecommerce",
        ],
    },
    "dropshipping": {
        "label": "Dropshipping",
        "emoji": "📦",
        "topics": [
            "que es dropshipping y como empezar con menos de 100 dolares",
            "dropshipping en Ecuador: como funciona y por que esta explotando",
            "diferencia entre dropshipping y marca propia: cual elegir",
            "como elegir un proveedor confiable de dropshipping",
            "dropi Ecuador: que es y por que todos quieren ser dropshippers",
            "errores que cometen los nuevos dropshippers en su primer mes",
            "como calcular ganancias reales en dropshipping (no solo el 'precio')",
            "anuncios de Facebook Ads para dropshipping COD: estrategia ganadora",
            "TikTok Ads vs Meta Ads para dropshipping: cual es mejor en Ecuador",
            "que productos NO debes vender en dropshipping y por que",
            "Cash on Delivery (COD): como manejar la tasa de devolucion",
            "como construir confianza con tu dropshipper proveedor",
            "dropshipping vs ecommerce tradicional: ventajas y desventajas",
            "metricas clave que todo dropshipper debe medir",
            "como escalar de $1000 a $10000 mensuales en dropshipping",
            "tasas de COD en Ecuador: por que importan y como mejorarlas",
            "dropshipping y devoluciones: como minimizarlas",
            "validacion de productos para dropshipping en menos de 7 dias",
            "como tercerizar atencion al cliente para escalar tu dropshipping",
            "dropshipping como fuente de ingresos pasiva: mito o realidad",
        ],
    },
    "negocios": {
        "label": "Negocios y emprendimiento",
        "emoji": "💼",
        "topics": [
            "como armar un plan de negocio en 1 hora (template practico)",
            "diferencia entre flujo de caja y rentabilidad: por que importa",
            "errores financieros que cometen los emprendedores nuevos",
            "como pagarte un sueldo digno desde tu negocio",
            "cuando reinvertir y cuando sacar utilidades de tu negocio",
            "RUC en Ecuador: que regimen elegir como emprendedor",
            "facturacion electronica en Ecuador: lo que todo emprendedor debe saber",
            "como contratar tu primer empleado sin morir en el intento",
            "delegar para escalar: como sacar tareas de tu cabeza",
            "metricas que importan en un negocio en crecimiento",
            "como manejar proveedores e inventario en un negocio en crecimiento",
            "diferencia entre socio, inversionista y empleado: como decidir",
            "branding desde 0: como construir una marca memorable",
            "psicologia del precio: como vender mas caro sin justificar",
            "como salir del operativo y pasar al estrategico",
            "indicadores financieros que todo dueño de negocio debe revisar mensualmente",
            "como tomar decisiones de negocio bajo incertidumbre",
            "kpi's de marketing vs kpi's financieros: como balancear",
            "cuando contratar un contador y cuando hacerlo solo",
            "cultura de empresa: como construirla desde el primer empleado",
        ],
    },
    "marketing": {
        "label": "Marketing digital",
        "emoji": "📱",
        "topics": [
            "Meta Ads para principiantes: como armar tu primera campana",
            "como segmentar audiencias en Facebook Ads sin desperdiciar dinero",
            "metricas de Facebook Ads que SI importan (y las que no)",
            "TikTok Ads vs Reels Ads vs Stories Ads: cuando usar cada uno",
            "como crear hooks en tus videos que retengan al usuario",
            "user generated content (UGC): como conseguirlo y por que vende mas",
            "WhatsApp Business: como armar tu funnel de ventas",
            "email marketing en 2026: sigue funcionando o esta muerto",
            "SEO local en Ecuador: como aparecer en Google Maps",
            "como elegir tu nicho de marketing en menos de 24 horas",
            "psicologia del consumidor: por que compramos lo que compramos",
            "presupuesto de marketing: cuanto invertir como porcentaje de ventas",
            "remarketing: como recuperar visitantes que no compraron",
            "branding personal: como Daniel Bonilla construyo el suyo",
            "como medir ROI de marketing: formula sencilla pero poderosa",
            "Google Ads vs Meta Ads: cuando conviene cada uno",
            "como evitar el burnout en una campana de Black Friday",
            "creator economy: como generar ingresos como creador de contenido",
            "estrategia de contenido evergreen vs viral: balance correcto",
            "como construir una audiencia de 100k seguidores en 2026",
        ],
    },
}


def slugify(text: str) -> str:
    """Convierte texto a slug URL-safe."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:80]


def load_meta() -> dict:
    """Carga el indice de posts ya generados (para evitar duplicados)."""
    if META_FILE.exists():
        with META_FILE.open() as f:
            return json.load(f)
    return {"posts": [], "topics_used": []}


def save_meta(meta: dict) -> None:
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    with META_FILE.open("w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def log(msg: str) -> None:
    """Append linea con timestamp al log."""
    ts = datetime.now(timezone.utc).isoformat()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(msg)


def pick_topic(meta: dict, categoria: str | None = None) -> tuple[str, str]:
    """Elige (categoria, topic) que aun no se haya usado.

    Si todas las topics de una categoria ya se usaron, las recicla en orden inverso
    (asi nunca se agotan, pero priorizamos las nuevas).
    """
    used = set(meta.get("topics_used", []))

    # Si Daniel forzo categoria, solo de esa
    if categoria and categoria in CATEGORIAS:
        cats = [categoria]
    else:
        # Round-robin: la categoria que tenga menos posts hasta ahora gana
        post_count_per_cat = {}
        for p in meta.get("posts", []):
            post_count_per_cat[p["categoria"]] = post_count_per_cat.get(p["categoria"], 0) + 1
        cats = sorted(CATEGORIAS.keys(), key=lambda c: post_count_per_cat.get(c, 0))

    for cat in cats:
        topics = CATEGORIAS[cat]["topics"]
        # Topics no usados primero
        unused = [t for t in topics if t not in used]
        if unused:
            return cat, random.choice(unused)
        # Si no hay unused, el menos reciente
        # (en el caso degenerado donde todas se usaron, recyclamos la mas vieja)
        oldest = topics[0]
        return cat, oldest

    # Defensive default
    cat = "importaciones"
    return cat, CATEGORIAS[cat]["topics"][0]


SYSTEM_PROMPT = """Sos un copywriter SEO experto que escribe para Daniel Bonilla,
CEO de GRUPO IMPOR (Ecuador). Daniel es importador desde China hace 8+ años, dueño de
IMPORCOMEX (importaciones), IMPORFACTORY (academia/cursos), IMPORSHOP (dropshipping).
Canal YouTube: @danytravel4695.

VOZ Y TONO:
- Directo, sin rodeos. Habla "vos" (rioplatense/ecuatoriano informal).
- Mezcla de experto y mentor. Cuenta cosas que aprendio en la cancha.
- Datos concretos, ejemplos reales, montos en USD ($).
- NUNCA suena a guru tipico. Suena a alguien que VIVIO el problema.
- Sin emojis rebuscados. Maximo 1-2 por seccion si suman.

ESTRUCTURA OBLIGATORIA del articulo (output en JSON):
{
  "title_h1": "60-70 chars max, gancho directo, sin clickbait sucio",
  "meta_description": "150-160 chars, primera frase atrapa, segunda explica beneficio",
  "lead": "1 parrafo de 2-3 frases, golpe directo al pain point",
  "tldr_bullets": ["3-5 bullets cortos con los takeaways principales"],
  "sections": [
    {
      "h2": "Subtitulo seccion (max 60 chars)",
      "paragraphs": ["parrafo 1", "parrafo 2", "..."],
      "h3_subsections": [
         {"h3": "subsubtitulo opcional", "paragraphs": ["..."]}
      ]
    }
  ],
  "tabla_comparativa": {
    "title": "Titulo de la tabla (opcional, null si no aplica)",
    "headers": ["Col1", "Col2", "Col3"],
    "rows": [["a","b","c"], ["d","e","f"]]
  },
  "faqs": [
    {"q": "Pregunta exacta tipo Google", "a": "Respuesta directa 2-3 frases"}
  ],
  "conclusion": "Cierre 1-2 parrafos: que hacer ahora, paso siguiente concreto",
  "tags": ["palabra1", "palabra2", "..."],
  "video_recomendado": "Frase de 1 linea sugiriendo ver video en YouTube de Daniel sobre este tema (ej. 'Te dejo este video donde explico paso a paso...'). Sera precedido por un embed del canal @danytravel4695. Si el tema NO se presta para video, retorna null.",
  "external_authority_mentions": ["1-2 frases que se podrian linkear a sites de autoridad sin parecer forzado, ej. 'segun el SRI', 'la guia oficial de Alibaba'"],
  "internal_link_hints": ["topic relacionado 1", "topic relacionado 2"]
}

REGLAS DE SEO:
1. El title_h1 debe contener la keyword principal en los primeros 60 chars.
2. Meta description: incluir keyword + beneficio + CTA implicito.
3. 4-7 secciones H2. Cada H2 con 1-3 H3 si el tema lo requiere.
4. Cada parrafo: maximo 4 oraciones. Frases cortas. Ritmo de lectura web.
5. Incluir AL MENOS 1 lista (ul/ol) en alguna seccion.
6. FAQ minimo 3 preguntas (Google rich results).
7. Tabla comparativa cuando aplique (genera tabla_comparativa null si no).
8. Tags: 5-10 keywords longtail relevantes.
9. Tono ecuatoriano-neutral pero conversacional.
10. NO usar lenguaje generico. NO frases de "en este articulo veremos...".
11. Empezar fuerte. Terminar con accion concreta.

LONGITUD OBJETIVO: 900-1300 palabras totales (no mas, para no truncar).

Output JSON valido. Solo el JSON, nada mas. NO uses markdown code fences.
NO uses backticks. NO uses comillas dobles dentro de strings (usa simples o ').
Las strings de los parrafos deben ser texto plano, sin saltos de linea sin escapar."""


def generar_post_claude(categoria: str, topic: str) -> dict:
    """Llama a Claude haiku para generar el contenido del post."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Fallback: leer de .env del ERP
        env_path = Path("/home/ubuntu/sistema/backend/.env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no encontrada (ni en env ni en /home/ubuntu/sistema/backend/.env)")

    client = anthropic.Anthropic(api_key=api_key)
    cat_label = CATEGORIAS[categoria]["label"]
    user_prompt = f"""Escribi un articulo de blog SEO sobre el siguiente tema.

CATEGORIA: {cat_label}
TEMA EXACTO: {topic}

Audiencia: emprendedores ecuatorianos/latinoamericanos interesados en importar
desde China, vender online o hacer dropshipping. Edad 25-45. Ingresos medios.
Buscan accion concreta, no teoria abstracta.

Generar el JSON del articulo siguiendo el formato del system prompt.
"""

    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    # Defensive: stripear posibles fences markdown
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log(f"ERROR JSON parse: {e}")
        log(f"Raw text length: {len(text)}, last 300 chars: ...{text[-300:]}")
        # Reintento: pedir solo el resto si parece truncado
        # Si el JSON termina en medio de un string, intentar cerrar manualmente
        repaired = _try_repair_json(text)
        if repaired:
            log("JSON reparado en cliente — usando version parcial")
            return repaired
        raise
    return data


def _try_repair_json(text: str) -> dict | None:
    """Intenta reparar JSON truncado: cerrar strings/arrays/objects abiertos."""
    # Cuenta llaves abiertas vs cerradas
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    # Si hay strings sin cerrar (numero impar de "), agregar uno
    candidate = text
    # Si termina en mitad de string, cortar hasta el ultimo " seguro
    if candidate.count('"') % 2 == 1:
        # Encontrar ultima coma + " antes del corte
        last_safe = max(candidate.rfind('",'), candidate.rfind('"\n'))
        if last_safe > 0:
            candidate = candidate[:last_safe + 1]
            open_braces = candidate.count("{") - candidate.count("}")
            open_brackets = candidate.count("[") - candidate.count("]")
    candidate += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
    try:
        return json.loads(candidate)
    except Exception:
        return None


def render_html(post: dict, meta_index: dict) -> str:
    """Renderea el HTML del post con SEO completo: schema.org, OG, Twitter, canonical."""
    cat = post["categoria"]
    cat_info = CATEGORIAS[cat]
    pub_iso = post["published_iso"]
    pub_human = datetime.fromisoformat(pub_iso).strftime("%d de %B, %Y")
    # Spanish month
    months_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    pub_dt = datetime.fromisoformat(pub_iso)
    pub_human = f"{pub_dt.day} de {months_es[pub_dt.month-1]}, {pub_dt.year}"

    canonical = f"{BLOG_URL}/posts/{post['slug']}.html"
    word_count = post.get("word_count", 1500)
    reading_min = max(1, word_count // 220)

    data = post["data"]
    title = data["title_h1"]
    meta_desc = data["meta_description"]
    lead = data["lead"]
    sections = data.get("sections", [])
    tabla = data.get("tabla_comparativa") or {}
    faqs = data.get("faqs", [])
    conclusion = data.get("conclusion", "")
    tags = data.get("tags", [])

    # JSON-LD Article schema
    article_schema = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "headline": title[:110],
        "description": meta_desc,
        "datePublished": pub_iso,
        "dateModified": pub_iso,
        "author": {
            "@type": "Person",
            "name": "Daniel Bonilla",
            "url": SITE_URL,
            "sameAs": ["https://www.instagram.com/danielbonilla.ec", SITE_URL]
        },
        "publisher": {
            "@type": "Organization",
            "name": "Daniel Bonilla — GRUPO IMPOR",
            "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/img/dany_scoth_.png"}
        },
        "keywords": ", ".join(tags),
        "articleSection": cat_info["label"],
        "wordCount": word_count,
        "inLanguage": "es",
    }

    faq_schema = None
    if faqs:
        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in faqs
            ]
        }

    breadcrumb_schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Inicio", "item": SITE_URL},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": BLOG_URL},
            {"@type": "ListItem", "position": 3, "name": cat_info["label"],
             "item": f"{BLOG_URL}/categorias/{cat}.html"},
            {"@type": "ListItem", "position": 4, "name": title, "item": canonical},
        ],
    }

    # Render contenido HTML  /* SEO_S17_PATCH */
    parts = []
    # Hero img dentro del <article> — image SEO + LCP + LLM multimodal
    _hero_img = post.get("image_url") or f"{SITE_URL}/img/dany_scoth_.png"
    parts.append(f'<figure class="post-hero" style="margin:0 0 24px;border-radius:14px;overflow:hidden;aspect-ratio:16/9;background:#000;">')
    parts.append(f'<img src="{_hero_img}" alt="{esc(title)} — Daniel Bonilla GRUPO IMPOR · {esc(cat_info["label"])}" width="1280" height="720" loading="eager" fetchpriority="high" decoding="async" style="width:100%;height:100%;object-fit:cover;display:block;">')
    parts.append(f'</figure>')
    parts.append(f'<header>')
    parts.append(f'<div class="cat">{cat_info["emoji"]} {cat_info["label"]}</div>')
    parts.append(f'<h1>{esc(title)}</h1>')
    parts.append(f'<p class="lead">{esc(lead)}</p>')
    parts.append(f'<div class="meta"><span class="author">✍ Daniel Bonilla</span><span>📅 {pub_human}</span><span>⏱ {reading_min} min de lectura</span></div>')
    parts.append('</header>')

    parts.append('<div class="content">')
    # TLDR bullets si vienen
    tldr = data.get("tldr_bullets") or []
    if tldr:
        parts.append('<div style="background:rgba(0,180,255,.08);border:1px solid var(--neon-border);border-radius:10px;padding:18px 22px;margin-bottom:32px;font-family:var(--font);font-size:15px;">')
        parts.append('<div style="color:var(--neon);font-weight:800;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:10px;">⚡ TL;DR · lo importante</div>')
        parts.append('<ul style="margin:0 0 0 24px;">')
        for t in tldr:
            parts.append(f'<li style="margin-bottom:6px;">{esc(t)}</li>')
        parts.append('</ul></div>')

    # Secciones H2 (defensive: algunas respuestas Claude usan otras keys)
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        h2 = sec.get("h2") or sec.get("heading") or sec.get("title") or sec.get("titulo")
        if not h2:
            continue
        parts.append(f'<h2>{esc(h2)}</h2>')
        # Paragraphs puede venir como list o string
        paras = sec.get("paragraphs") or sec.get("content") or sec.get("body") or []
        if isinstance(paras, str):
            paras = [paras]
        for p in paras:
            if p:
                parts.append(f'<p>{esc(p)}</p>')
        for sub in (sec.get("h3_subsections") or sec.get("subsections") or []):
            if not isinstance(sub, dict):
                continue
            h3 = sub.get("h3") or sub.get("heading") or sub.get("title")
            if not h3:
                continue
            parts.append(f'<h3>{esc(h3)}</h3>')
            sub_paras = sub.get("paragraphs") or sub.get("content") or []
            if isinstance(sub_paras, str):
                sub_paras = [sub_paras]
            for p in sub_paras:
                if p:
                    parts.append(f'<p>{esc(p)}</p>')

    # Tabla comparativa si hay
    if tabla and tabla.get("headers"):
        parts.append(f'<h2>{esc(tabla.get("title") or "Comparativa rapida")}</h2>')
        parts.append('<table>')
        parts.append('<thead><tr>')
        for h in tabla["headers"]:
            parts.append(f'<th>{esc(h)}</th>')
        parts.append('</tr></thead><tbody>')
        for row in tabla.get("rows", []):
            parts.append('<tr>')
            for c in row:
                parts.append(f'<td>{esc(c)}</td>')
            parts.append('</tr>')
        parts.append('</tbody></table>')

    # FAQ (defensive con keys alternativas)
    if faqs:
        parts.append('<h2>Preguntas frecuentes</h2>')
        for f in faqs:
            if not isinstance(f, dict):
                continue
            q = f.get("q") or f.get("question") or f.get("pregunta")
            a = f.get("a") or f.get("answer") or f.get("respuesta")
            if not q or not a:
                continue
            parts.append('<div class="faq-item">')
            parts.append(f'<h4>{esc(q)}</h4>')
            parts.append(f'<p>{esc(a)}</p>')
            parts.append('</div>')

    # Conclusion
    if conclusion:
        parts.append('<h2>Conclusion</h2>')
        for p in conclusion.split("\n\n"):
            if p.strip():
                parts.append(f'<p>{esc(p.strip())}</p>')

    # YouTube channel CTA + embed (suscripcion al canal de Daniel)
    video_rec = data.get("video_recomendado")
    if video_rec:
        parts.append('<div style="background:linear-gradient(135deg,#FF0000,#CC0000);border-radius:14px;padding:24px;margin:36px 0;color:#fff;text-align:center;font-family:var(--font);">')
        parts.append('<div style="font-size:11px;font-weight:800;letter-spacing:2px;text-transform:uppercase;opacity:.85;margin-bottom:8px;">▶ Mi canal de YouTube</div>')
        parts.append(f'<p style="font-size:16px;font-weight:600;margin-bottom:14px;">{esc(video_rec)}</p>')
        parts.append(f'<a href="{YT_CHANNEL}" target="_blank" rel="noopener" style="display:inline-block;background:#fff;color:#CC0000;padding:12px 22px;border-radius:8px;font-weight:800;text-decoration:none;font-size:13px;letter-spacing:.5px;text-transform:uppercase;">▶ Ver mi canal: @danytravel4695</a>')
        parts.append('</div>')

    # Bloque "Recursos y enlaces utiles" — external authority + autoridad SEO
    cat_authority = AUTHORITY_LINKS.get(cat, [])
    if cat_authority:
        # Mezclar para no siempre los mismos primeros
        sample = random.sample(cat_authority, min(3, len(cat_authority)))
        parts.append('<h2>Recursos y enlaces utiles</h2>')
        parts.append('<p>Si queres profundizar, estas son fuentes confiables que uso yo:</p>')
        parts.append('<ul>')
        for label, url in sample:
            parts.append(f'<li><a href="{url}" target="_blank" rel="noopener nofollow">{esc(label)}</a></li>')
        # Always el canal YT como ultimo bullet
        parts.append(f'<li><a href="{YT_CHANNEL}" target="_blank" rel="noopener">▶ Mi canal de YouTube — danytravel4695</a></li>')
        parts.append('</ul>')

    parts.append('</div>')  # /content

    # CTA WA
    cta_msg = f"Hola Daniel, lei tu articulo '{title[:50]}' y quiero hablar"
    cta_url = f"https://wa.me/{WA_NUMBER}?text={url_quote(cta_msg)}"
    # CTA Club de Importadores (taap.it/checkout)
    parts.append('<div class="imf-cta-club" style="margin:48px 0 24px;padding:36px 28px;background:linear-gradient(135deg,#0B1426 0%,#0a1a3a 50%,#001a2e 100%);border-radius:18px;border:1px solid rgba(0,191,255,0.25);box-shadow:0 0 40px rgba(0,191,255,0.15),inset 0 1px 0 rgba(255,255,255,0.05);position:relative;overflow:hidden;color:#fff">\n  <div style="position:absolute;top:-40px;right:-40px;width:200px;height:200px;background:radial-gradient(circle,rgba(0,191,255,0.4) 0%,transparent 70%);pointer-events:none"></div>\n  <div style="position:absolute;bottom:-60px;left:-60px;width:240px;height:240px;background:radial-gradient(circle,rgba(124,92,255,0.25) 0%,transparent 70%);pointer-events:none"></div>\n  <div style="position:relative">\n    <div style="display:inline-block;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#00BFFF;font-weight:700;padding:6px 14px;border:1px solid rgba(0,191,255,0.4);border-radius:999px;background:rgba(0,191,255,0.08);margin-bottom:18px">🔥 CLUB DE IMPORTADORES</div>\n    <h2 style="font-family:Montserrat,Inter,sans-serif;font-size:clamp(24px,3.5vw,34px);font-weight:900;letter-spacing:-0.02em;line-height:1.15;margin:0 0 14px;color:#fff;border:none;padding:0">Aprende a importar de China <span style="background:linear-gradient(90deg,#00BFFF,#33D6FF);-webkit-background-clip:text;background-clip:text;color:transparent">sin perder dinero</span></h2>\n    <p style="font-size:16px;line-height:1.55;color:rgba(255,255,255,0.75);margin:0 0 24px;max-width:580px">Únete al Club de Importadores: el método paso a paso que uso para importar desde China con bajo riesgo + grupo cerrado de emprendedores + acceso a proveedores verificados.</p>\n    <a href="https://taap.it/unirme-club-de-importadores-blog" target="_blank" rel="noopener" style="display:inline-flex;align-items:center;gap:10px;padding:16px 28px;background:linear-gradient(135deg,#00BFFF 0%,#33D6FF 100%);color:#0B1426;font-weight:800;font-size:15px;letter-spacing:0.3px;text-decoration:none;border-radius:12px;box-shadow:0 10px 30px rgba(0,191,255,0.4),0 0 0 1px rgba(255,255,255,0.1) inset;text-transform:uppercase;transition:transform 200ms ease,box-shadow 200ms ease" onmouseover="this.style.transform=\'translateY(-2px)\';this.style.boxShadow=\'0 14px 40px rgba(0,191,255,0.55),0 0 0 1px rgba(255,255,255,0.15) inset\'" onmouseout="this.style.transform=\'\';this.style.boxShadow=\'0 10px 30px rgba(0,191,255,0.4),0 0 0 1px rgba(255,255,255,0.1) inset\'">\n      QUIERO ENTRAR AL CLUB\n      <span style="font-size:18px">→</span>\n    </a>\n    <div style="margin-top:16px;font-size:12px;color:rgba(255,255,255,0.5);display:flex;align-items:center;gap:12px;flex-wrap:wrap">\n      <span>✓ Acceso inmediato</span>\n      <span>✓ Grupo cerrado</span>\n      <span>✓ Garantía 7 días</span>\n    </div>\n  </div>\n</div>')
    parts.append('<div class="end-cta">')
    parts.append('<h3>¿Querés hablar conmigo directamente?</h3>')
    parts.append('<p>Si esto te resono y queres llevarlo a la accion, escribime por WhatsApp.</p>')
    parts.append(f'<a href="{cta_url}" target="_blank" rel="noopener" class="btn">💬 Hablemos por WhatsApp</a>')
    parts.append('</div>')

    # Posts relacionados (mismo categoria, max 3)
    related_posts = [p for p in meta_index.get("posts", []) if p["categoria"] == cat and p["slug"] != post["slug"]][:3]
    if related_posts:
        parts.append('<div class="related"><h3>Articulos relacionados</h3><div class="related-grid">')
        for rp in related_posts:
            parts.append(f'<a href="/blog/posts/{rp["slug"]}.html" class="post-card" style="text-decoration:none;">')
            _img = rp.get("image_url")  # /* THUMB_PATCH */
            if _img:
                parts.append(f'<div class="img-wrap" style="aspect-ratio:16/9;overflow:hidden"><img src="{_img}" alt="{esc(rp["title"])}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block"></div>')
            else:
                parts.append(f'<div class="img-wrap"><div class="img-emoji">{cat_info["emoji"]}</div></div>')
            parts.append(f'<div class="body"><div class="cat">{cat_info["label"]}</div>')
            parts.append(f'<h2>{esc(rp["title"])}</h2></div></a>')
        parts.append('</div></div>')

    article_html = "\n".join(parts)

    # Render template completo
    schemas_json = json.dumps(article_schema, ensure_ascii=False)
    breadcrumb_json = json.dumps(breadcrumb_schema, ensure_ascii=False)
    faq_json_html = ""
    if faq_schema:
        faq_json_html = f'<script type="application/ld+json">{json.dumps(faq_schema, ensure_ascii=False)}</script>'

    keywords = ", ".join(tags) if tags else cat_info["label"]

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} · Blog Daniel Bonilla</title>
<meta name="description" content="{esc(meta_desc)}">
<meta name="keywords" content="{esc(keywords)}">
<meta name="author" content="Daniel Bonilla">
<meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large,max-video-preview:-1">
<link rel="canonical" href="{canonical}">

<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(meta_desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{post.get('image_url') or f'{SITE_URL}/img/dany_scoth_.png'}">
<meta property="og:image:width" content="1280">
<meta property="og:image:height" content="720">
<meta property="og:image:alt" content="{esc(title)}">
<meta property="og:site_name" content="Daniel Bonilla — GRUPO IMPOR">
<meta property="article:published_time" content="{pub_iso}">
<meta property="article:author" content="Daniel Bonilla">
<meta property="article:section" content="{esc(cat_info['label'])}">
{"".join(f'<meta property="article:tag" content="{esc(t)}">' for t in tags)}

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(meta_desc)}">
<meta name="twitter:image" content="{post.get('image_url') or f'{SITE_URL}/img/dany_scoth_.png'}">
<meta name="twitter:image:alt" content="{esc(title)}">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Montserrat:wght@700;800;900&family=Lora:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/blog/assets/blog.css?v=20260514a">
<link rel="alternate" type="application/rss+xml" title="Blog Daniel Bonilla" href="{BLOG_URL}/feed.xml">

<script type="application/ld+json">{schemas_json}</script>
<script type="application/ld+json">{breadcrumb_json}</script>
{faq_json_html}
</head>
<body>

<nav class="nav"><div class="nav-in">
  <a href="/" class="nav-logo">
    <img src="/img/dany_scoth_.png" alt="Daniel Bonilla">
    <div><h1>DANIEL BONILLA</h1><small>BLOG · GRUPO IMPOR</small></div>
  </a>
  <div class="nav-links">
    <a href="/">Inicio</a>
    <a href="/blog/">Blog</a>
    <a href="https://wa.me/{WA_NUMBER}?text=Hola%20Daniel" class="nav-cta" target="_blank" rel="noopener">🚢 QUIERO IMPORTAR</a>
  </div>
</div></nav>

<div class="wrap">
  <article class="article">
    <nav aria-label="Breadcrumb" class="breadcrumb"><a href="/">Inicio</a> › <a href="/blog/">Blog</a> › <a href="/blog/categorias/{cat}.html">{esc(cat_info['label'])}</a> › <span aria-current="page">{esc(title)}</span></nav>
    {article_html}
  </article>
</div>

<footer class="footer">
  <div class="links">
    <a href="/">Sitio principal</a>
    <a href="/blog/">Blog</a>
    <a href="/blog/feed.xml">RSS</a>
    <a href="https://wa.me/{WA_NUMBER}" target="_blank" rel="noopener">WhatsApp</a>
  </div>
  <div>© {datetime.now().year} Daniel Bonilla · GRUPO IMPOR · Ecuador</div>
</footer>

<script>
/* IMPORFACTORY blog view tracker — Sprint 11 (2026-06-03) */
(function(){{
  try{{
    var p = location.pathname.split("/").filter(Boolean);
    var slug = p[p.length-1].replace(/\.html$/i,"");
    if(!slug || slug==="index") return;
    var url = "https://impor.imporchina.com/api/blog/public/track-view/" + encodeURIComponent(slug);
    if(navigator.sendBeacon){{ navigator.sendBeacon(url); }}
    else {{ fetch(url,{{method:"POST",mode:"no-cors",keepalive:true}}).catch(function(){{}}); }}
  }} catch(e){{}}
}})();
</script>
</body></html>
"""
    return html


def esc(s: str) -> str:
    """HTML escape minimo."""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def url_quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


def rebuild_index(meta_index: dict) -> None:
    """Regenera /blog/index.html, /blog/categorias/*.html, /blog/sitemap.xml, /blog/feed.xml"""
    posts = sorted(meta_index.get("posts", []), key=lambda p: p["published_iso"], reverse=True)

    # ── /blog/index.html ──
    cards_html = []
    for p in posts:
        cat = p["categoria"]
        cat_info = CATEGORIAS.get(cat, CATEGORIAS["importaciones"])
        excerpt = p.get("meta_description", "")[:140]
        pub_dt = datetime.fromisoformat(p["published_iso"])
        pub_short = pub_dt.strftime("%d/%m/%Y")
        cards_html.append(f"""    <a href="/blog/posts/{p['slug']}.html" class="post-card">
      {f'<div class="img-wrap" style="aspect-ratio:16/9;overflow:hidden"><img src="{p["image_url"]}" alt="{esc(p["title"])}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block"></div>' if p.get("image_url") else f'<div class="img-wrap"><div class="img-emoji">{cat_info["emoji"]}</div></div>'}
      <div class="body">
        <div class="cat">{cat_info['label']}</div>
        <h2>{esc(p['title'])}</h2>
        <div class="excerpt">{esc(excerpt)}</div>
        <div class="meta"><span>📅 {pub_short}</span><span class="read-more">Leer →</span></div>
      </div>
    </a>""")
    cards_block = "\n".join(cards_html) or '<div style="grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--steel);">Pronto: nuevos articulos cada dia.</div>'

    # Categorias filter bar
    cats_links = ['<a href="/blog/" class="active">Todos</a>']
    for ck, ci in CATEGORIAS.items():
        cats_links.append(f'<a href="/blog/categorias/{ck}.html">{ci["emoji"]} {esc(ci["label"])}</a>')
    cats_bar = "\n".join(cats_links)

    index_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Blog · Daniel Bonilla — Importaciones, Ecommerce, Dropshipping</title>
<meta name="description" content="Blog de Daniel Bonilla, CEO de GRUPO IMPOR. Articulos sobre como importar desde China, ecommerce, dropshipping, marketing digital y emprendimiento. Contenido nuevo cada dia.">
<meta name="keywords" content="importar desde China, ecommerce Ecuador, dropshipping Ecuador, Daniel Bonilla, GRUPO IMPOR, IMPORCOMEX">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{BLOG_URL}/">
<meta property="og:type" content="website">
<meta property="og:title" content="Blog · Daniel Bonilla">
<meta property="og:description" content="Articulos diarios sobre importaciones, ecommerce y dropshipping. Por Daniel Bonilla, CEO Grupo Impor.">
<meta property="og:image" content="{SITE_URL}/img/dany_scoth_.png">
<meta property="og:url" content="{BLOG_URL}/">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Montserrat:wght@700;800;900&family=Lora:ital,wght@0,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/blog/assets/blog.css?v=20260514a">
<link rel="alternate" type="application/rss+xml" title="Blog Daniel Bonilla" href="{BLOG_URL}/feed.xml">
</head>
<body>

<nav class="nav"><div class="nav-in">
  <a href="/" class="nav-logo">
    <img src="/img/dany_scoth_.png" alt="Daniel Bonilla">
    <div><h1>DANIEL BONILLA</h1><small>BLOG · GRUPO IMPOR</small></div>
  </a>
  <div class="nav-links">
    <a href="/">Inicio</a>
    <a href="/blog/">Blog</a>
    <a href="https://wa.me/{WA_NUMBER}?text=Hola%20Daniel" class="nav-cta" target="_blank" rel="noopener">🚢 QUIERO IMPORTAR</a>
  </div>
</div></nav>

<header class="blog-hero">
  <div class="wrap">
    <span class="badge">Blog · Aprendé conmigo</span>
    <h1>Importaciones, Ecommerce y Dropshipping</h1>
    <p>Lo que aprendi en 8+ años importando desde China y construyendo ecommerce en Ecuador. Contenido nuevo cada dia.</p>
  </div>
</header>

<div class="cat-bar wrap-wide">
  {cats_bar}
</div>

<div class="wrap-wide">
  <div class="posts-grid">
{cards_block}
  </div>
</div>

<footer class="footer">
  <div class="links">
    <a href="/">Sitio principal</a>
    <a href="/blog/">Blog</a>
    <a href="/blog/feed.xml">RSS</a>
    <a href="https://wa.me/{WA_NUMBER}" target="_blank" rel="noopener">WhatsApp</a>
  </div>
  <div>© {datetime.now().year} Daniel Bonilla · GRUPO IMPOR · Ecuador</div>
</footer>

<script>
/* IMPORFACTORY blog view tracker — Sprint 11 (2026-06-03) */
(function(){{
  try{{
    var p = location.pathname.split("/").filter(Boolean);
    var slug = p[p.length-1].replace(/\.html$/i,"");
    if(!slug || slug==="index") return;
    var url = "https://impor.imporchina.com/api/blog/public/track-view/" + encodeURIComponent(slug);
    if(navigator.sendBeacon){{ navigator.sendBeacon(url); }}
    else {{ fetch(url,{{method:"POST",mode:"no-cors",keepalive:true}}).catch(function(){{}}); }}
  }} catch(e){{}}
}})();
</script>
</body></html>
"""
    (BLOG_DIR / "index.html").write_text(index_html, encoding="utf-8")
    log(f"Regenerado: index.html con {len(posts)} posts")

    # ── Categorias individuales ──
    for ck, ci in CATEGORIAS.items():
        cat_posts = [p for p in posts if p["categoria"] == ck]
        cat_cards_html = []
        for p in cat_posts:
            excerpt = p.get("meta_description", "")[:140]
            pub_dt = datetime.fromisoformat(p["published_iso"])
            pub_short = pub_dt.strftime("%d/%m/%Y")
            cat_cards_html.append(f"""    <a href="/blog/posts/{p['slug']}.html" class="post-card">
      {f'<div class="img-wrap" style="aspect-ratio:16/9;overflow:hidden"><img src="{p["image_url"]}" alt="{esc(p["title"])}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block"></div>' if p.get("image_url") else f'<div class="img-wrap"><div class="img-emoji">{ci["emoji"]}</div></div>'}
      <div class="body">
        <div class="cat">{ci['label']}</div>
        <h2>{esc(p['title'])}</h2>
        <div class="excerpt">{esc(excerpt)}</div>
        <div class="meta"><span>📅 {pub_short}</span><span class="read-more">Leer →</span></div>
      </div>
    </a>""")
        cat_cards_block = "\n".join(cat_cards_html) or f'<div style="grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--steel);">Pronto: articulos sobre {ci["label"]}.</div>'

        cats_links_act = []
        for ck2, ci2 in CATEGORIAS.items():
            active = "active" if ck2 == ck else ""
            cats_links_act.append(f'<a href="/blog/categorias/{ck2}.html" class="{active}">{ci2["emoji"]} {esc(ci2["label"])}</a>')
        cats_bar_act = '<a href="/blog/">Todos</a>\n' + "\n".join(cats_links_act)

        cat_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(ci['label'])} · Blog Daniel Bonilla</title>
<meta name="description" content="Articulos sobre {esc(ci['label'])} por Daniel Bonilla. Contenido practico para emprendedores latinos.">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{BLOG_URL}/categorias/{ck}.html">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(ci['label'])} · Blog Daniel Bonilla">
<meta property="og:description" content="Articulos sobre {esc(ci['label'])} por Daniel Bonilla">
<meta property="og:image" content="{SITE_URL}/img/dany_scoth_.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Montserrat:wght@700;800;900&family=Lora:ital,wght@0,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/blog/assets/blog.css?v=20260514a">
</head>
<body>

<nav class="nav"><div class="nav-in">
  <a href="/" class="nav-logo">
    <img src="/img/dany_scoth_.png" alt="Daniel Bonilla">
    <div><h1>DANIEL BONILLA</h1><small>BLOG · GRUPO IMPOR</small></div>
  </a>
  <div class="nav-links">
    <a href="/">Inicio</a>
    <a href="/blog/">Blog</a>
    <a href="https://wa.me/{WA_NUMBER}?text=Hola%20Daniel" class="nav-cta" target="_blank" rel="noopener">🚢 QUIERO IMPORTAR</a>
  </div>
</div></nav>

<header class="blog-hero">
  <div class="wrap">
    <span class="badge">{ci['emoji']} CATEGORIA</span>
    <h1>{esc(ci['label'])}</h1>
    <p>{len(cat_posts)} {'articulo' if len(cat_posts)==1 else 'articulos'} en esta categoria.</p>
  </div>
</header>

<div class="cat-bar wrap-wide">
  {cats_bar_act}
</div>

<div class="wrap-wide">
  <div class="posts-grid">
{cat_cards_block}
  </div>
</div>

<footer class="footer">
  <div class="links">
    <a href="/">Sitio principal</a>
    <a href="/blog/">Blog</a>
    <a href="/blog/feed.xml">RSS</a>
    <a href="https://wa.me/{WA_NUMBER}" target="_blank" rel="noopener">WhatsApp</a>
  </div>
  <div>© {datetime.now().year} Daniel Bonilla · GRUPO IMPOR · Ecuador</div>
</footer>

<script>
/* IMPORFACTORY blog view tracker — Sprint 11 (2026-06-03) */
(function(){{
  try{{
    var p = location.pathname.split("/").filter(Boolean);
    var slug = p[p.length-1].replace(/\.html$/i,"");
    if(!slug || slug==="index") return;
    var url = "https://impor.imporchina.com/api/blog/public/track-view/" + encodeURIComponent(slug);
    if(navigator.sendBeacon){{ navigator.sendBeacon(url); }}
    else {{ fetch(url,{{method:"POST",mode:"no-cors",keepalive:true}}).catch(function(){{}}); }}
  }} catch(e){{}}
}})();
</script>
</body></html>
"""
        (CATS_DIR / f"{ck}.html").write_text(cat_html, encoding="utf-8")

    # ── sitemap.xml ──
    sm_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm_lines.append(f'  <url><loc>{SITE_URL}/</loc><priority>1.0</priority></url>')
    sm_lines.append(f'  <url><loc>{BLOG_URL}/</loc><priority>0.9</priority><changefreq>daily</changefreq></url>')
    for ck in CATEGORIAS:
        sm_lines.append(f'  <url><loc>{BLOG_URL}/categorias/{ck}.html</loc><priority>0.7</priority><changefreq>weekly</changefreq></url>')
    for p in posts:
        sm_lines.append(f'  <url><loc>{BLOG_URL}/posts/{p["slug"]}.html</loc>'
                        f'<lastmod>{p["published_iso"][:10]}</lastmod><priority>0.8</priority></url>')
    sm_lines.append('</urlset>')
    (BLOG_DIR / "sitemap.xml").write_text("\n".join(sm_lines), encoding="utf-8")

    # ── feed.xml (RSS 2.0) ──
    feed_items = []
    for p in posts[:20]:
        pub_dt = datetime.fromisoformat(p["published_iso"])
        pub_rfc822 = pub_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        feed_items.append(f"""    <item>
      <title>{esc(p['title'])}</title>
      <link>{BLOG_URL}/posts/{p['slug']}.html</link>
      <guid>{BLOG_URL}/posts/{p['slug']}.html</guid>
      <pubDate>{pub_rfc822}</pubDate>
      <category>{esc(CATEGORIAS[p['categoria']]['label'])}</category>
      <description>{esc(p.get('meta_description',''))}</description>
    </item>""")
    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Blog Daniel Bonilla</title>
    <link>{BLOG_URL}/</link>
    <description>Articulos sobre importaciones desde China, ecommerce y dropshipping. Por Daniel Bonilla.</description>
    <language>es</language>
    <lastBuildDate>{datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>
{chr(10).join(feed_items)}
  </channel>
</rss>
"""
    (BLOG_DIR / "feed.xml").write_text(feed_xml, encoding="utf-8")
    log(f"Regenerado: sitemap.xml + feed.xml + {len(CATEGORIAS)} categoria pages")


def _generate_one(args, meta, override_published=None) -> bool:
    """Genera 1 post. Retorna True si OK."""
    cat, topic = pick_topic(meta, args.categoria)
    log(f"Generando: categoria={cat} topic={topic}")

    try:
        data = generar_post_claude(cat, topic)
    except Exception as e:
        log(f"ERROR generacion Claude: {e}")
        return False

    title = data.get("title_h1", topic)
    slug_base = slugify(title)
    pub_dt = override_published or datetime.now(timezone.utc)
    slug = f"{pub_dt.strftime('%Y%m%d')}-{slug_base}"

    text_blob = json.dumps(data, ensure_ascii=False)
    word_count = len(text_blob.split())

    post = {
        "slug": slug,
        "title": title,
        "categoria": cat,
        "published_iso": pub_dt.isoformat(),
        "word_count": word_count,
        "meta_description": data.get("meta_description", ""),
        "data": data,
    }

    if args.dry_run:
        log(f"[DRY-RUN] {slug}")
        return True

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    CATS_DIR.mkdir(parents=True, exist_ok=True)

    html = render_html(post, meta)
    (POSTS_DIR / f"{slug}.html").write_text(html, encoding="utf-8")

    meta_post = {k: v for k, v in post.items() if k != "data"}
    meta["posts"].append(meta_post)
    meta["topics_used"] = meta.get("topics_used", []) + [topic]
    save_meta(meta)

    log(f"OK: {slug} | cat={cat} | words={word_count} | total={len(meta['posts'])}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--categoria", choices=list(CATEGORIAS.keys()),
                    help="Forzar categoria (default: round-robin)")
    ap.add_argument("--dry-run", action="store_true", help="No escribir archivos")
    ap.add_argument("--rebuild-index", action="store_true",
                    help="Solo regenerar index/sitemap/feed sin nuevo post")
    ap.add_argument("--count", type=int, default=1,
                    help="Cuantos posts generar en esta corrida (default 1)")
    ap.add_argument("--backdate-spread-days", type=int, default=0,
                    help="Si > 0, distribuye los --count posts en este rango de dias hacia atras (para SEO natural).")
    args = ap.parse_args()

    meta = load_meta()

    if args.rebuild_index:
        rebuild_index(meta)
        return

    # Pre-calcular fechas si backdate spread
    backdates = []
    if args.backdate_spread_days > 0 and args.count > 1:
        # Distribuir N posts uniformemente en el rango [hace N dias, hoy]
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        step_hours = (args.backdate_spread_days * 24) / max(args.count, 1)
        for i in range(args.count):
            # i=0 = mas viejo, i=N-1 = mas reciente. Random jitter +/- 4h por naturalidad
            hours_back = (args.count - 1 - i) * step_hours
            jitter = random.uniform(-4, 4)
            backdates.append(now - timedelta(hours=hours_back + jitter))
        backdates.sort()  # asc para escribir en orden cronologico

    ok_count = 0
    failed_count = 0
    for i in range(args.count):
        override = backdates[i] if backdates else None
        try:
            if _generate_one(args, meta, override_published=override):
                ok_count += 1
            else:
                failed_count += 1
        except Exception as e:
            failed_count += 1
            log(f"ERROR post {i+1}/{args.count}: {type(e).__name__}: {e}")
            # Continuar con el siguiente, no abortar todo
        # Throttle entre llamados Claude para no saturar API ni rate-limit
        if i < args.count - 1:
            import time
            time.sleep(2.5)

    if not args.dry_run and ok_count > 0:
        rebuild_index(meta)
        log(f"BATCH OK: {ok_count}/{args.count} OK ({failed_count} fallaron). Total blog: {len(meta['posts'])}")


if __name__ == "__main__":
    main()
