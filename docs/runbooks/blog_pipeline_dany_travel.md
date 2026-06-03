# Pipeline Blog Dany Travel — Operacional

> **URL público:** https://danytraveloficial.com/blog/
> **Editor centralizado:** https://impor.imporchina.com/blog/editor
> **Branch:** `feature/imporfactory-premium-impor-2026-05-27` (commits Sprint 8-10)

## Arquitectura

```
EDITOR (impor.imporchina.com/blog/editor)
   ↓ Daniel escribe / regenera
   ↓ Panel Gemini con 8 fotos base + 8 MOOD_PRESETS
   ↓ Genera miniatura cyan + sparks + headline
   ↓
BD (blog_articulos + blog_generaciones_ai)
   ↓ POST /api/imporfactory/blog/5/articulos/{id}/publicar-estatico
   ↓ blog_static_html_service.publish_to_danytravel()
   ↓ Reusa generate_post.py (1061 lineas legacy) via importlib
   ↓ Renderiza HTML con schema.org BlogPosting + FAQPage + BreadcrumbList
   ↓
/var/www/danytravel/blog/posts/{date}-{slug}.html
   + actualiza index.html, categorias/*, sitemap.xml, feed.xml
```

## Crons activos

```
# /etc/cron.d/blog-danytravel — Generador legacy (heredado, 2026-05-14)
0 14 * * *   ubuntu  generate_post.py
              # 9am Ecuador -> 1 post nuevo cada dia
              # Round-robin entre 5 categorias original
              # Output: HTML estatico + meta JSON

# /etc/cron.d/imporfactory-premium (Sprint 10, 2026-06-03)
*/15 * * * * ubuntu  cron_blog_sync_thumbs.py
              # Sync posts_meta.json -> blog_articulos (idempotente)
              # Genera miniatura Gemini para hasta 5 posts/corrida sin miniatura
              # ~$0.20 por corrida (5 miniaturas $0.039 c/u)
```

## Mapeo categoria → miniatura

| Categoria | Foto base | MOOD preset | Kicker default |
|---|---|---|---|
| importaciones | espaldas-puerto (id=2) | puerto-contenedores | IMPORTACIONES |
| ecommerce | brazos-cruzados-bodega (id=1) | alibaba-pantalla | ECOMMERCE |
| dropshipping | telefono-clase1 (id=5) | dropi-app | DROPSHIPPING |
| negocios | ayudame-bodega (id=7) | bodega-productos | NEGOCIOS |
| marketing | regalo-brillando (id=6) | studio-neon | MARKETING DIGITAL |

## Costos

| Item | Costo unitario | Mensual (30 posts) |
|---|---|---|
| Outline Claude Opus 4.5 | $0.077 | $2.31 |
| Articulo 1200 palabras Claude | $0.326 | $9.78 |
| Miniatura Gemini 3.1 Flash | $0.039 | $1.17 |
| **TOTAL post completo** | **$0.44** | **$13.26/mes** |

## Operaciones tipicas

### Daniel revisa un post antes de publicar
1. Login en https://impor.imporchina.com/blog
2. Click en el post (estado: borrador)
3. Edita en /blog/editor — autosave c/4s
4. Panel Imagen → Gemini · Daniel — genera miniatura
5. Click "Publicar" — push HTML + reconstruye indices

### Forzar re-generar miniatura
1. Editor abre el post desde /blog
2. Panel Gemini — cambia foto base / mood / texto
3. Click "Usar como portada" + Publicar

### Detener cron (vacaciones / mantenimiento)
```bash
sudo sed -i 's/^0 14/#0 14/' /etc/cron.d/blog-danytravel
# Reactivar quitando el # de las lineas
```

### Restaurar miniatura por defecto (rollback)
```sql
UPDATE blog_articulos SET miniatura_url = NULL, miniatura_alt = NULL WHERE id = X;
-- Proximo cron generara una nueva
```

### Forzar sync inmediato (sin esperar 15 min)
```bash
/home/ubuntu/sistema/backend/venv/bin/python3 \
  /home/ubuntu/sistema/backend/app/scripts/cron_blog_sync_thumbs.py
```

## Estado actual

- 47 posts publicados en danytraveloficial.com/blog/ (HTML estaticos)
- 47 posts migrados a blog_articulos (editables desde IMPORFACTORY)
- Miniaturas Gemini retroactivas en proceso (~$1.83 total para los 47)
- 2 crons activos: generador legacy + sync/thumbs

## Smoke checks

```bash
# Post publico responde
curl -sI https://danytraveloficial.com/blog/posts/{date}-{slug}.html

# Sitemap actualizado
curl -s https://danytraveloficial.com/blog/sitemap.xml | head -10

# Status BD
mysql -e "SELECT COUNT(*) total,
  SUM(CASE WHEN miniatura_url IS NOT NULL AND miniatura_url<>'' THEN 1 ELSE 0 END) con_mini
  FROM blog_articulos WHERE empresa_id=5;"

# Log cron sync
tail -20 /var/log/imporfactory_blog_sync.log
```

## Pendientes futuros (cuando Daniel decida)

- **blog.imporfactory.com**: vhost + service ya listos en server. Solo falta crear A record en Cloudflare (acceso pendiente) + certbot SSL.
- **YouTube auto-upload**: pipeline articulo → script video → TTS → ensamblado → upload @danytravel4695. Sprint futuro.
- **Re-render HTML con miniatura Gemini**: actualmente las miniaturas se persisten en BD pero los HTML legacy mantienen dany_scoth_.png como og:image. Al editar un post desde IMPORFACTORY y republicar, se actualiza og:image con la miniatura nueva.
