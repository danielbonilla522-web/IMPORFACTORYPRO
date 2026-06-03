"""Inyecta una sección 'Últimos del blog' en /var/www/danytravel/index.html.

- Lee los 6 posts más recientes de posts_meta.json
- Renderiza cards con miniatura Gemini + categoría + título
- Reemplaza el bloque entre marcadores HTML <!-- BLOG_SECTION_START --> ... END -->
- Si los marcadores no existen, los inserta justo antes de "<!-- ═════ FOOTER"

Idempotente: re-ejecutable cualquier vez (cron, manual).
"""
import json
import sys
from pathlib import Path
from datetime import datetime

INDEX = Path("/var/www/danytravel/index.html")
META = Path("/home/ubuntu/blog-danytravel/posts_meta.json")

CATEGORIAS_META = {
    "importaciones": {"label": "🚢 Importaciones desde China", "color": "#00B4FF"},
    "ecommerce": {"label": "🛒 Ecommerce y ventas online", "color": "#33D6FF"},
    "dropshipping": {"label": "📦 Dropshipping", "color": "#FF6B6B"},
    "negocios": {"label": "💼 Negocios y emprendimiento", "color": "#7C5CFF"},
    "marketing": {"label": "📱 Marketing digital", "color": "#FFD700"},
}

START_MARK = "<!-- BLOG_SECTION_START -->"
END_MARK = "<!-- BLOG_SECTION_END -->"

def esc(s: str) -> str:
    return (str(s) or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def render_section(posts: list) -> str:
    cards = []
    for p in posts:
        cat_key = p.get("categoria", "importaciones")
        cat = CATEGORIAS_META.get(cat_key, CATEGORIAS_META["importaciones"])
        slug = p.get("slug", "")
        img = p.get("image_url") or "/img/dany_scoth_.png"
        title = p.get("title", "")
        desc = (p.get("meta_description", "") or "")[:120]
        try:
            pub = datetime.fromisoformat(p.get("published_iso", "")).strftime("%d/%m/%Y")
        except Exception:
            pub = ""
        cards.append(f"""    <a href="/blog/posts/{slug}.html" class="hp-blog-card">
      <div class="hp-blog-thumb"><img src="{img}" alt="{esc(title)}" loading="lazy"></div>
      <div class="hp-blog-body">
        <div class="hp-blog-cat" style="color:{cat['color']}">{cat['label']}</div>
        <h3>{esc(title)}</h3>
        <p>{esc(desc)}</p>
        <div class="hp-blog-meta"><span>📅 {pub}</span><span class="hp-blog-arrow">LEER →</span></div>
      </div>
    </a>""")

    cards_html = "\n".join(cards)

    return f"""{START_MARK}
<!-- ═══════════════════════ BLOG SECTION (auto-generated) ═══════════════════════ -->
<style>
.hp-blog{{padding:80px 0;background:linear-gradient(180deg,transparent,rgba(0,180,255,0.03));border-top:1px solid var(--neon-border);border-bottom:1px solid var(--neon-border)}}
.hp-blog-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:42px}}
.hp-blog-card{{background:linear-gradient(180deg,rgba(255,255,255,0.02),rgba(0,180,255,0.03));border:1px solid var(--neon-border);border-radius:14px;overflow:hidden;display:flex;flex-direction:column;transition:transform 280ms ease,border-color 280ms ease,box-shadow 280ms ease;text-decoration:none;color:inherit}}
.hp-blog-card:hover{{transform:translateY(-6px);border-color:var(--neon);box-shadow:0 18px 50px rgba(0,180,255,0.18),0 0 0 1px var(--neon-glow)}}
.hp-blog-thumb{{aspect-ratio:16/9;overflow:hidden;background:#000;position:relative}}
.hp-blog-thumb img{{width:100%;height:100%;object-fit:cover;display:block;transition:transform 500ms ease}}
.hp-blog-card:hover .hp-blog-thumb img{{transform:scale(1.06)}}
.hp-blog-body{{padding:20px 22px;display:flex;flex-direction:column;gap:10px;flex:1}}
.hp-blog-cat{{font-size:10px;font-weight:900;letter-spacing:1.5px;text-transform:uppercase}}
.hp-blog-card h3{{font-family:var(--font-h);font-size:18px;line-height:1.25;font-weight:900;color:var(--white);margin:0;letter-spacing:-0.3px}}
.hp-blog-card p{{font-size:13px;color:var(--ice);opacity:.7;line-height:1.5;margin:0}}
.hp-blog-meta{{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:12px;border-top:1px solid var(--neon-border);font-size:11px;color:var(--steel)}}
.hp-blog-arrow{{color:var(--neon);font-weight:900;letter-spacing:1px}}
.hp-blog-cta-row{{display:flex;justify-content:center;margin-top:36px}}
.hp-blog-cta{{display:inline-flex;align-items:center;gap:10px;padding:14px 32px;background:linear-gradient(135deg,var(--neon),#33D6FF);color:#000;font-weight:900;font-size:14px;letter-spacing:1px;text-transform:uppercase;border-radius:12px;text-decoration:none;box-shadow:0 10px 30px rgba(0,180,255,0.4);transition:transform 200ms ease,box-shadow 200ms ease}}
.hp-blog-cta:hover{{transform:translateY(-2px);box-shadow:0 14px 40px rgba(0,180,255,0.55)}}
@media (max-width:900px){{.hp-blog-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media (max-width:600px){{.hp-blog-grid{{grid-template-columns:1fr}}}}
</style>

<section class="hp-blog">
  <div class="wrap">
    <div class="section-head">
      <div class="section-eyebrow">Blog · Aprendé conmigo</div>
      <h2 class="section-title">Lo último del blog</h2>
      <p class="section-sub">Contenido nuevo todos los días sobre importaciones, ecommerce, dropshipping y negocios. Lo que aprendí en 8+ años importando desde China.</p>
    </div>
    <div class="hp-blog-grid">
{cards_html}
    </div>
    <div class="hp-blog-cta-row">
      <a href="/blog/" class="hp-blog-cta">VER TODO EL BLOG →</a>
    </div>
  </div>
</section>
{END_MARK}"""


def main():
    if not META.exists():
        print("ERR: posts_meta.json no encontrado")
        sys.exit(1)
    meta = json.load(META.open())
    posts = meta.get("posts", [])
    # Ordenar por fecha publicación descendiente, tomar últimos 6
    posts_sorted = sorted(posts, key=lambda p: p.get("published_iso", ""), reverse=True)[:6]
    section_html = render_section(posts_sorted)

    if not INDEX.exists():
        print("ERR: index.html no encontrado")
        sys.exit(1)
    src = INDEX.read_text()

    if START_MARK in src and END_MARK in src:
        # Reemplazar bloque existente
        start = src.find(START_MARK)
        end = src.find(END_MARK) + len(END_MARK)
        src = src[:start] + section_html + src[end:]
        action = "REPLACED"
    else:
        # Insertar antes del comentario FOOTER
        marker = "<!-- ═══════════════════════ FOOTER ═══════════════════════ -->"
        if marker not in src:
            print("ERR: no se encontró marker FOOTER")
            sys.exit(1)
        src = src.replace(marker, section_html + "\n\n" + marker, 1)
        action = "INSERTED"

    INDEX.write_text(src)
    print(f"OK_{action} posts={len(posts_sorted)}")


if __name__ == "__main__":
    main()
