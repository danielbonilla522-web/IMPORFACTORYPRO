# IMPORFACTORY Premium — Runbook operacional

> **Vive en:** `https://impor.imporchina.com`
> **Stack:** mismo monolito uvicorn (puerto 8000), templates separados, CSS premium dedicado.
> **Empresa:** `empresa_id=5`

## Arquitectura

```
impor.imporchina.com (Apache vhost SSL Let's Encrypt)
    └─ proxy HTTP/1.1 → 127.0.0.1:8000 (uvicorn)
        └─ FastAPI: render_for_host detecta host y sirve:
            ├─ frontend/templates/imporfactory_premium/*.html
            └─ frontend/static/css/imporfactory_premium.css

DB: MySQL grupo_impor (mismo backend que ERP y IMPORSHOP)
    └─ 8 tablas dedicadas: clases_vivas, clase_inscripciones, clase_recordatorios,
       blog_articulos, blog_categorias, blog_videos_youtube, blog_generaciones_ai,
       finanzas_snapshots
    └─ whatsapp_queue extendida con alumno_id, trigger_origen, contexto_json
    └─ Reusa: alumnos, alumno_membresias, flujo_caja, empresa_config
```

## URLs

| URL | Quién | Qué hace |
|---|---|---|
| `/` | público | Landing premium (sin auth) |
| `/dashboard` | staff | Vista general + roadmap |
| `/clases` | staff | Calendario clases en vivo + recordatorios |
| `/blog` | staff | Lista de artículos blog SEO+LLM |
| `/blog/editor` | staff | Editor con panel AI (Claude + DALL-E) |
| `/finanzas` | staff | Dashboard KPIs ejecutivos |
| `/mensajeria` | staff | Cola WhatsApp + broadcasts |
| `/videos` | staff | Gestor YouTube |
| `/configuracion` | staff | (Reusa /os-config legacy) |
| `/api/blog/public/sitemap.xml` | público | Sitemap para Google |
| `/api/blog/public/articulos/{slug}` | público | JSON detalle artículo |

## Crons activos

`/etc/cron.d/imporfactory-premium`:
- `*/5 * * * *` — `cron_clases_recordatorios.py` (drena recordatorios → whatsapp_queue)
- `0 */6 * * *` — `cron_finanzas_snapshot.py` (recalcula MRR/churn/LTV)
- Logs: `/var/log/imporfactory_finanzas.log`, `/var/log/imporfactory_clases.log`

## Credenciales a configurar (empresa_config, empresa_id=5)

| Clave | Origen | Para qué |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com | Generar texto/outline/SEO/schema con Claude |
| `OPENAI_API_KEY` | platform.openai.com | Miniaturas DALL-E 3 HD |
| `YOUTUBE_OAUTH_CLIENT_ID` + `_CLIENT_SECRET` | console.cloud.google.com | OAuth YouTube (luego completar flow desde /videos) |

SQL para configurar manualmente:
```sql
INSERT INTO empresa_config (empresa_id, clave, valor) VALUES
  (5, 'ANTHROPIC_API_KEY', 'sk-ant-...'),
  (5, 'OPENAI_API_KEY', 'sk-...'),
  (5, 'YOUTUBE_OAUTH_CLIENT_ID', 'xxx.apps.googleusercontent.com'),
  (5, 'YOUTUBE_OAUTH_CLIENT_SECRET', 'GOCSPX-...')
ON DUPLICATE KEY UPDATE valor = VALUES(valor);
```

## Rollback rápido

Para deshabilitar una página premium (revertir a 404 limpio):
```bash
# Mover el template fuera de la carpeta premium
ssh ubuntu@impor "mv /home/ubuntu/sistema/frontend/templates/imporfactory_premium/clases /home/ubuntu/sistema/frontend/templates/imporfactory_premium/clases.disabled"
# El helper render_for_host hace fallback automático y los handlers retornan 404.
```

Para rollback completo del subdominio (apuntar a otra app, ej. Next.js):
```bash
# Editar /etc/apache2/sites-available/impor-le-ssl.conf cambiando ProxyPass
sudo systemctl reload apache2
```

Para rollback BD (8 tablas creadas):
```sql
DROP TABLE IF EXISTS finanzas_snapshots;
DROP TABLE IF EXISTS blog_generaciones_ai;
DROP TABLE IF EXISTS blog_videos_youtube;
DROP TABLE IF EXISTS blog_articulos;
DROP TABLE IF EXISTS blog_categorias;
DROP TABLE IF EXISTS clase_recordatorios;
DROP TABLE IF EXISTS clase_inscripciones;
DROP TABLE IF EXISTS clases_vivas;
ALTER TABLE whatsapp_queue
  DROP INDEX ix_wa_alumno, DROP INDEX ix_wa_trigger,
  DROP COLUMN contexto_json, DROP COLUMN trigger_origen, DROP COLUMN alumno_id;
```
Backup pre-migración: `/home/ubuntu/backups/whatsapp_queue_pre_imporfactory_20260527.sql`

## Smoke checks post-deploy

```bash
# DNS
dig impor.imporchina.com +short  # → 18.205.94.210

# SSL + landing
curl -I https://impor.imporchina.com/  # → 200

# Aislamiento ERP legacy (debe seguir intacto)
curl -I https://erp.imporchina.com/    # → 200 (login ERP normal)
curl -I https://imporshop.imporchina.com/  # → 200 (IMPORSHOP normal)

# Sitemap público (sin auth)
curl https://impor.imporchina.com/api/blog/public/sitemap.xml | head -5

# Snapshot finanzas manual
ssh ubuntu@impor "/home/ubuntu/sistema/backend/venv/bin/python3 /home/ubuntu/sistema/backend/app/scripts/cron_finanzas_snapshot.py"
```

## Flujos E2E críticos

### Crear clase con recordatorios automáticos
1. Login staff en `impor.imporchina.com`
2. `/clases` → botón **+ Programar clase**
3. Llenar wizard (título, fecha futura, audiencia)
4. Submit → backend:
   - Inserta en `clases_vivas`
   - Inscribe alumnos del filtro de membresía (tabla `clase_inscripciones`)
   - Programa 3 recordatorios por alumno: 24h/1h/5min antes (tabla `clase_recordatorios`)
5. Cron `*/5min` revisa `clase_recordatorios.estado=pendiente AND programado_para<=NOW()+1min`
6. Drena → `whatsapp_queue` con `trigger_origen='clase_recordatorio'`
7. Worker `whatsapp_queue.py` envía vía `wacli-imporfactory` con rate-limit anti-baneo

### Crear artículo blog con AI
1. `/blog` → **+ Nuevo artículo**
2. Panel **AI** lateral: input tema + keyword → **⚡ Generar outline** (Claude)
3. Outline aparece en editor markdown
4. **AI → Generar texto** (Claude, ~$0.05)
5. Panel **Imagen** → DALL-E HD genera miniatura ($0.08), click "Usar como portada"
6. Panel **SEO** → **⚡ Auto-generar SEO meta** (title 60ch + meta 155ch)
7. Panel **LLM** → **⚡ Analizar citability** → score 0-100 + sugerencias
8. **Publicar** → estado pasa a `publicado`, aparece en sitemap.xml

### Broadcast WhatsApp
1. `/mensajeria` → **+ Broadcast**
2. Texto con `{nombre}` → seleccionar segmento (importacion, ecommerce...)
3. Botón **Vista previa (dry-run)** → cuenta destinatarios + tiempo estimado
4. Botón **Enviar broadcast** → encola con rate-limit progresivo
5. Worker drena `whatsapp_queue` con `trigger_origen='broadcast_manual'`

## Costos AI (visibles en /mensajeria)

- Claude Opus 4.7 outline: ~$0.01
- Claude Opus 4.7 artículo 1500 palabras: $0.04-$0.08 con caching
- DALL-E 3 HD 1792x1024: $0.08
- Artículo completo: ~$0.20 - $0.30
- Endpoint `GET /api/imporfactory/wa/5/costos-ai` retorna desglose 30d

## Troubleshooting

| Síntoma | Probable causa | Fix |
|---|---|---|
| `/blog/editor` panel AI da "API key no configurada" | Falta `ANTHROPIC_API_KEY` en `empresa_config` | Insertar via SQL o desde `/configuracion` |
| Recordatorios no se envían | Cron no corre, o `wacli-imporfactory` desconectado | `cat /var/log/imporfactory_clases.log` + `/api/jeff/wa-imporfactory/status` |
| Snapshot finanzas vacío | Cron no corrió aún | Ejecutar manual: `python3 .../cron_finanzas_snapshot.py` |
| YouTube /videos da error 400 OAuth | Falta `YOUTUBE_OAUTH_CLIENT_ID/SECRET` | Setup en Google Cloud + insertar en config |
| `imporfactory.imporchina.com` rompió | NO se tocó | Sigue apuntando a puerto 3001 (Next.js alumnos), no a este sistema |

## Branch git

- Branch: `feature/imporfactory-premium-impor-2026-05-27`
- Remote: `origin/feature/imporfactory-premium-impor-2026-05-27`
- Commits Sprint 1-7 con prefijo `[IMPORFACTORY-PREMIUM]`
- Merge a `main` cuando Daniel valide y pase regresión.
