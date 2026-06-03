"""
IMPORFACTORY Premium — Wrapper Anthropic SDK con prompt caching.

Lee ANTHROPIC_API_KEY desde empresa_config(empresa_id=5).
Cada llamada persiste en blog_generaciones_ai con costo_usd para auditoría.

2026-05-27 Sprint 5.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# Modelo default + pricing (USD por 1M tokens, ajustar si cambia)
DEFAULT_MODEL = "claude-opus-4-5"

PRICING = {
    "claude-opus-4-5":    {"in": 15.0, "out": 75.0,  "cached_in": 1.5},
    "claude-opus-4-7":    {"in": 15.0, "out": 75.0,  "cached_in": 1.5},
    "claude-sonnet-4-5":  {"in": 3.0,  "out": 15.0,  "cached_in": 0.3},
    "claude-sonnet-4-6":  {"in": 3.0,  "out": 15.0,  "cached_in": 0.3},
}


SYSTEM_PROMPT_EDITOR = """Eres el asistente editorial de IMPORFACTORY (academia online de Daniel Bonilla en Ecuador).

VOZ DE MARCA:
- Directo, claro, sin floreos académicos. Hablas como un hermano mayor que ya vivió la importación y el ecommerce COD.
- Concreto: cifras reales, ejemplos de Ecuador/LATAM (Dropi, Funelish, infoaduana, FODINFA, Cleveland casas...).
- Honesto: si algo es difícil, decirlo. Si tiene riesgo, advertir. Cero hype barato.
- Educacional: cada artículo debe enseñar algo accionable hoy mismo.

AUDIENCIA:
- Emprendedores LATAM 22-45 años pensando en importar de China o vender por COD.
- Nivel de inglés bajo, leen en español. Bilingüismo solo cuando aporta (Alibaba, Stripe, MOQ).
- Atención corta. Primeros 3 párrafos deciden si siguen leyendo.

ESTRUCTURA EDITORIAL (para artículos):
1. Hook en primera línea (pregunta o cifra impactante).
2. Resumen TL;DR en 2-3 bullets antes del H2.
3. H2 secciones con subtemas claros, escaneables.
4. H3 para sub-temas dentro de cada H2.
5. Tablas/listas para densidad informativa.
6. FAQ al final con 4-6 preguntas que el LLM citará.
7. CTA final hacia membresía IMPORFACTORY o curso correspondiente.

OPTIMIZACIÓN SEO + LLM (GEO):
- Title tag 55-60 char, exact match keyword.
- Meta desc 150-155 char, beneficio claro.
- H1 incluye keyword principal.
- Párrafos cortos (3 líneas máx).
- Citas a fuentes con URL (SRI, FODINFA, Aduana del Ecuador, Alibaba blog) — los LLMs prefieren contenido con citas.
- Datos numéricos con fecha (ej. "según SRI 2026").
- Schema.org Article + FAQPage cuando aplique.
- Respuestas directas en la primera frase de cada párrafo (mejor citabilidad por Perplexity/ChatGPT).

NUNCA:
- Hablar como ChatGPT genérico ("¡Hola! Hoy te voy a contar...").
- Promesas absolutas ("ganarás $10K seguro").
- Inventar cifras o regulaciones que no existan.
- Usar emojis a granel — solo cuando aporten (1-2 por artículo máximo).
"""


async def _get_api_key(db: AsyncSession, empresa_id: int = 5) -> Optional[str]:
    # Prioridad 1: variable de entorno (cargada de backend/.env por dotenv)
    import os
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key
    # Prioridad 2: empresa_config por empresa
    row = (await db.execute(text("""
        SELECT valor FROM empresa_config
        WHERE empresa_id = :emp AND clave = 'ANTHROPIC_API_KEY'
        LIMIT 1
    """), {"emp": empresa_id})).first()
    return row[0] if row else None


def _calc_cost(model: str, tokens_in: int, tokens_out: int, cached_in: int = 0) -> float:
    p = PRICING.get(model, {"in": 15.0, "out": 75.0, "cached_in": 1.5})
    cost = (tokens_in * p["in"] / 1_000_000.0
            + tokens_out * p["out"] / 1_000_000.0
            + cached_in * p["cached_in"] / 1_000_000.0)
    return round(cost, 6)


async def generate_text(
    db: AsyncSession,
    user_prompt: str,
    *,
    articulo_id: Optional[int] = None,
    tipo: str = "texto",
    system_extra: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4000,
    temperature: float = 0.7,
    generado_por_id: Optional[int] = None,
) -> dict:
    """Llama Claude API y retorna {text, cost_usd, tokens_in, tokens_out, generacion_id}.

    Persiste en blog_generaciones_ai automáticamente.
    Usa prompt caching ephemeral en el system prompt (TTL 5min) para
    reducir 90% el costo en lotes.
    """
    api_key = await _get_api_key(db)
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada en empresa_config(empresa_id=5). "
                          "Configurar en /configuracion antes de usar AI.")

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        raise RuntimeError("Anthropic SDK no instalado. pip install anthropic")

    client = AsyncAnthropic(api_key=api_key)
    system_blocks = [
        {"type": "text", "text": SYSTEM_PROMPT_EDITOR, "cache_control": {"type": "ephemeral"}},
    ]
    if system_extra:
        system_blocks.append({"type": "text", "text": system_extra})

    t0 = time.time()
    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_blocks,
        messages=[{"role": "user", "content": user_prompt}],
    )
    duracion_ms = int((time.time() - t0) * 1000)

    text_out = "".join([b.text for b in resp.content if b.type == "text"])
    tokens_in = resp.usage.input_tokens
    tokens_out = resp.usage.output_tokens
    cached_in = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
    cost = _calc_cost(model, tokens_in, tokens_out, cached_in)

    # Persistir auditoría
    gen_res = await db.execute(text("""
        INSERT INTO blog_generaciones_ai
            (articulo_id, tipo, prompt, modelo_usado, parametros_json,
             resultado_texto, costo_usd, tokens_input, tokens_output,
             duracion_ms, generado_por_id)
        VALUES
            (:aid, :tipo, :prompt, :model, :params,
             :result, :cost, :tin, :tout, :dur, :uid)
    """), {
        "aid": articulo_id, "tipo": tipo, "prompt": user_prompt[:8000],
        "model": model, "params": json.dumps({"max_tokens": max_tokens, "temperature": temperature}),
        "result": text_out, "cost": cost, "tin": tokens_in, "tout": tokens_out,
        "dur": duracion_ms, "uid": generado_por_id,
    })
    await db.commit()

    return {
        "text": text_out,
        "cost_usd": cost,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cached_in": cached_in,
        "duracion_ms": duracion_ms,
        "model": model,
        "generacion_id": gen_res.lastrowid,
    }


async def generate_outline(db: AsyncSession, tema: str, keyword: str, longitud_palabras: int = 1500,
                            articulo_id: Optional[int] = None) -> dict:
    """Genera outline H1/H2/H3 estructurado."""
    prompt = (f"Genera el outline para un artículo SEO de ~{longitud_palabras} palabras "
              f"sobre el tema: '{tema}'. Keyword principal: '{keyword}'.\n\n"
              "Formato salida (en markdown):\n"
              "# H1: ...\n## H2-1: ...\n### H3-1.1: ...\n### H3-1.2: ...\n## H2-2: ...\n"
              "(etc)\n\nIncluye al final una sección '## FAQ' con 4-6 preguntas frecuentes "
              "que respondan dudas comunes (para citas por LLMs).")
    return await generate_text(db, prompt, articulo_id=articulo_id, tipo="outline", max_tokens=2000)


async def generate_article(db: AsyncSession, outline: str, keyword: str, tono: str = "directo",
                            longitud_palabras: int = 1500, articulo_id: Optional[int] = None) -> dict:
    """Genera artículo completo en markdown a partir de outline."""
    prompt = (f"Escribe el artículo COMPLETO en markdown siguiendo este outline. "
              f"Longitud objetivo: {longitud_palabras} palabras. Tono: {tono}. "
              f"Keyword principal: '{keyword}'.\n\nOutline:\n{outline}\n\n"
              "IMPORTANTE: estructura cada sección con respuestas directas en la primera frase, "
              "incluye datos numéricos con fecha, agrega 1-2 citas a fuentes oficiales con URL, "
              "y termina con FAQ + CTA hacia membresía IMPORFACTORY.")
    return await generate_text(db, prompt, articulo_id=articulo_id, tipo="texto", max_tokens=8000)


async def generate_seo_meta(db: AsyncSession, articulo_id: int, contenido_md: str, keyword: str) -> dict:
    """Genera title tag, meta description, keywords desde contenido."""
    prompt = (f"Para el siguiente artículo (keyword: '{keyword}'), genera EN JSON estricto:\n"
              "- seo_titulo: 55-60 chars, incluye keyword\n"
              "- seo_descripcion: 150-155 chars, beneficio claro\n"
              "- seo_keywords: array de 5-8 keywords secundarias\n\n"
              "Solo devuelve el JSON, nada más.\n\n"
              f"Contenido:\n{contenido_md[:3000]}")
    return await generate_text(db, prompt, articulo_id=articulo_id, tipo="seo_meta", max_tokens=500, temperature=0.3)


async def generate_schema_org(db: AsyncSession, articulo_id: int, titulo: str, contenido_md: str,
                                tipo_schema: str = "Article", autor: str = "Equipo IMPORFACTORY") -> dict:
    """Genera JSON-LD schema.org Article + opcionalmente FAQPage."""
    prompt = (f"Genera el JSON-LD schema.org para este artículo. "
              f"Tipo: {tipo_schema}. Título: '{titulo}'. Autor: '{autor}'. "
              f"Publisher: IMPORFACTORY (Ecuador). Fecha de publicación: hoy. "
              f"Si el contenido tiene FAQ explícitas, incluye también FAQPage en @graph. "
              "Solo devuelve el JSON-LD válido (con @context, @type, etc), sin comentarios ni markdown.\n\n"
              f"Contenido (primeras 2000 chars):\n{contenido_md[:2000]}")
    return await generate_text(db, prompt, articulo_id=articulo_id, tipo="schema_org", max_tokens=2000, temperature=0.2)


async def optimize_for_llm(db: AsyncSession, articulo_id: int, contenido_md: str) -> dict:
    """Analiza el artículo y devuelve score 0-100 + sugerencias accionables GEO."""
    prompt = ("Evalúa este artículo para CITABILIDAD por LLMs (ChatGPT, Claude, Perplexity, "
              "Google AI Overviews). Da un score 0-100 y sugerencias accionables.\n\n"
              "Criterios (cada uno 0-10 puntos):\n"
              "1. Respuestas directas en primera frase de cada párrafo\n"
              "2. Estructura H2/H3 jerárquica clara\n"
              "3. Datos numéricos con fechas\n"
              "4. Citas a fuentes oficiales con URL\n"
              "5. FAQ explícita al final (mínimo 4 preguntas)\n"
              "6. Tablas o listas para densidad informativa\n"
              "7. Definición clara de términos técnicos\n"
              "8. Longitud adecuada (1000-2500 palabras)\n"
              "9. Ejemplos concretos con nombres/lugares específicos\n"
              "10. Esqueleto schema.org-friendly (Article + FAQPage)\n\n"
              "Devuelve EN JSON:\n"
              "{\"score\": <0-100>, \"breakdown\": {1:..,2:..,...}, "
              "\"sugerencias\": [\"...\"], \"fortalezas\": [\"...\"]}\n\n"
              f"Artículo:\n{contenido_md[:6000]}")
    return await generate_text(db, prompt, articulo_id=articulo_id, tipo="optimizacion_llm",
                                max_tokens=2000, temperature=0.3)


async def generate_video_script(db: AsyncSession, articulo_id: int, contenido_md: str,
                                  duracion_target_seg: int = 480) -> dict:
    """Genera script para video YouTube basado en artículo."""
    prompt = (f"Convierte este artículo en un script para video YouTube de ~{duracion_target_seg} segundos.\n\n"
              "Estructura:\n"
              "- [0:00-0:08] HOOK fuerte (pregunta o cifra impactante)\n"
              "- [0:08-0:25] INTRO + qué van a aprender\n"
              "- [0:25-...] DESARROLLO con timestamps\n"
              "- [Final-30s] CTA hacia IMPORFACTORY\n\n"
              "Tono conversacional como hablando a la cámara, frases cortas, hablado.\n"
              "Incluye también:\n"
              "- titulo_yt (60 chars max)\n"
              "- descripcion_yt (300-500 chars con timestamps)\n"
              "- tags_yt (10-15 tags)\n"
              "- thumbnail_prompt (descripción para generar miniatura DALL-E)\n\n"
              "Formato salida: JSON estricto con keys script, titulo_yt, descripcion_yt, tags_yt, thumbnail_prompt.\n\n"
              f"Artículo:\n{contenido_md[:5000]}")
    return await generate_text(db, prompt, articulo_id=articulo_id, tipo="video_script",
                                max_tokens=4000, temperature=0.7)
