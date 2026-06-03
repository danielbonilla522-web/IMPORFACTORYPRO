-- ════════════════════════════════════════════════════════════════════
-- IMPORFACTORY Premium — Schema BD (empresa_id=5)
-- Migración: imporfactory_premium_001.sql
-- Fecha: 2026-05-27
-- Sprint 2: 8 tablas nuevas + ALTER whatsapp_queue
-- ════════════════════════════════════════════════════════════════════
-- ROLLBACK: ver final del archivo

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS=1;

-- ────────────────────────────────────────────────────────────────────
-- 1) ALTER whatsapp_queue: agregar columnas para integración premium
-- ────────────────────────────────────────────────────────────────────
ALTER TABLE whatsapp_queue
  ADD COLUMN alumno_id INT NULL AFTER empresa_id,
  ADD COLUMN trigger_origen VARCHAR(60) NULL AFTER batch_id,
  ADD COLUMN contexto_json JSON NULL AFTER trigger_origen,
  ADD INDEX ix_wa_trigger (trigger_origen, estado),
  ADD INDEX ix_wa_alumno (alumno_id);

-- ────────────────────────────────────────────────────────────────────
-- 2) clases_vivas — masterclasses / webinars Zoom
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clases_vivas (
  id INT AUTO_INCREMENT PRIMARY KEY,
  empresa_id INT NOT NULL DEFAULT 5,
  titulo VARCHAR(220) NOT NULL,
  descripcion TEXT NULL,
  instructor VARCHAR(120) NOT NULL DEFAULT 'Daniel Bonilla',
  fecha_inicio DATETIME NOT NULL,
  duracion_min INT NOT NULL DEFAULT 60,
  zoom_meeting_id VARCHAR(80) NULL,
  zoom_join_url VARCHAR(500) NULL,
  zoom_password VARCHAR(40) NULL,
  zoom_start_url VARCHAR(500) NULL,
  max_asistentes INT NOT NULL DEFAULT 1000,
  grabacion_url VARCHAR(500) NULL,
  grabacion_password VARCHAR(40) NULL,
  estado ENUM('programada','en_vivo','finalizada','cancelada') NOT NULL DEFAULT 'programada',
  dirigida_a JSON NULL COMMENT 'Array de tipo_membresia: ["importacion","ecommerce","kit","infoaduana"]',
  imagen_portada_url VARCHAR(500) NULL,
  slug VARCHAR(120) NULL UNIQUE,
  notas_internas TEXT NULL,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX ix_clases_empresa (empresa_id),
  INDEX ix_clases_fecha_estado (fecha_inicio, estado),
  INDEX ix_clases_estado (estado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Masterclasses y webinars en vivo (Zoom)';

-- ────────────────────────────────────────────────────────────────────
-- 3) clase_inscripciones — alumnos inscritos a cada clase
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clase_inscripciones (
  id INT AUTO_INCREMENT PRIMARY KEY,
  clase_id INT NOT NULL,
  alumno_id INT NOT NULL,
  fecha_inscripcion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  inscripcion_modo ENUM('auto','manual','masiva') NOT NULL DEFAULT 'auto',
  asistio ENUM('no','si','parcial','no_registrado') NOT NULL DEFAULT 'no_registrado',
  minutos_asistidos INT NOT NULL DEFAULT 0,
  zoom_user_email VARCHAR(150) NULL,
  joined_at DATETIME NULL,
  left_at DATETIME NULL,
  CONSTRAINT fk_inscripcion_clase FOREIGN KEY (clase_id) REFERENCES clases_vivas(id) ON DELETE CASCADE,
  UNIQUE KEY uq_clase_alumno (clase_id, alumno_id),
  INDEX ix_inscripcion_alumno (alumno_id),
  INDEX ix_inscripcion_clase_asistio (clase_id, asistio)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Inscripciones de alumnos a clases en vivo';

-- ────────────────────────────────────────────────────────────────────
-- 4) clase_recordatorios — cola de recordatorios programados WA
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clase_recordatorios (
  id INT AUTO_INCREMENT PRIMARY KEY,
  clase_id INT NOT NULL,
  alumno_id INT NOT NULL,
  tipo ENUM('24h','1h','5min','post_grabacion') NOT NULL,
  estado ENUM('pendiente','encolado','enviado','fallo','no_aplica') NOT NULL DEFAULT 'pendiente',
  mensaje_wa_queue_id INT NULL,
  programado_para DATETIME NOT NULL,
  enviado_en DATETIME NULL,
  error_msg TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_recordatorio_clase FOREIGN KEY (clase_id) REFERENCES clases_vivas(id) ON DELETE CASCADE,
  UNIQUE KEY uq_recordatorio (clase_id, alumno_id, tipo),
  INDEX ix_recordatorio_pendiente (estado, programado_para)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Recordatorios programados de clases via WhatsApp';

-- ────────────────────────────────────────────────────────────────────
-- 5) blog_categorias — categorías del blog editorial
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS blog_categorias (
  id INT AUTO_INCREMENT PRIMARY KEY,
  empresa_id INT NOT NULL DEFAULT 5,
  slug VARCHAR(80) NOT NULL,
  nombre VARCHAR(120) NOT NULL,
  descripcion TEXT NULL,
  icon VARCHAR(8) NULL,
  color VARCHAR(16) NULL DEFAULT '#0EA5E9',
  seo_titulo VARCHAR(200) NULL,
  seo_descripcion VARCHAR(300) NULL,
  orden INT NOT NULL DEFAULT 0,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY uq_categoria_slug (slug),
  INDEX ix_categoria_empresa (empresa_id, activo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Categorias del blog editorial IMPORFACTORY';

INSERT IGNORE INTO blog_categorias (empresa_id, slug, nombre, descripcion, icon, color, orden) VALUES
  (5, 'importacion-china', 'Importación China', 'Guías y casos de estudio sobre importar de Alibaba, 1688, Made-in-China', '🚢', '#00BFFF', 1),
  (5, 'ecommerce-cod', 'Ecommerce COD', 'Dropshipping COD, Shopify, Funelish, campañas y conversión', '🛒', '#7C5CFF', 2),
  (5, 'casos-exito', 'Casos de éxito', 'Historias de alumnos que escalaron con IMPORFACTORY', '🏆', '#E6B800', 3),
  (5, 'noticias-comercio', 'Noticias Comercio', 'Aranceles, FODINFA, regulaciones SRI, infoaduana', '📰', '#2BD9A0', 4),
  (5, 'tendencias-producto', 'Productos ganadores', 'Análisis de tendencias y productos para vender en EC/LATAM', '🔥', '#FF6B6B', 5);

-- ────────────────────────────────────────────────────────────────────
-- 6) blog_articulos — artículos del blog SEO + LLM
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS blog_articulos (
  id INT AUTO_INCREMENT PRIMARY KEY,
  empresa_id INT NOT NULL DEFAULT 5,
  slug VARCHAR(220) NOT NULL,
  titulo VARCHAR(260) NOT NULL,
  subtitulo VARCHAR(300) NULL,
  contenido_md MEDIUMTEXT NULL,
  contenido_html MEDIUMTEXT NULL,
  miniatura_url VARCHAR(500) NULL,
  miniatura_alt VARCHAR(200) NULL,
  autor_id INT NULL COMMENT 'usuarios.id del staff que escribió',
  autor_nombre_publico VARCHAR(120) NOT NULL DEFAULT 'Equipo IMPORFACTORY',
  categoria_id INT NULL,
  estado ENUM('borrador','revision','programado','publicado','archivado') NOT NULL DEFAULT 'borrador',
  fecha_publicacion DATETIME NULL,
  seo_titulo VARCHAR(200) NULL,
  seo_descripcion VARCHAR(300) NULL,
  seo_keywords JSON NULL,
  seo_canonical_url VARCHAR(500) NULL,
  seo_og_image VARCHAR(500) NULL,
  schema_org JSON NULL COMMENT 'JSON-LD para SEO + LLM citability',
  llm_optimization_score INT NULL COMMENT '0-100 score de citabilidad por LLMs',
  llm_citations_estimadas JSON NULL,
  tiempo_lectura_min INT NULL,
  vistas INT NOT NULL DEFAULT 0,
  vistas_30d INT NOT NULL DEFAULT 0,
  tags JSON NULL,
  faqs_json JSON NULL,
  referencias_json JSON NULL,
  generado_con_ai TINYINT(1) NOT NULL DEFAULT 0,
  revisado_humano TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_articulo_slug (slug),
  INDEX ix_articulo_estado_fecha (estado, fecha_publicacion),
  INDEX ix_articulo_categoria_estado (categoria_id, estado),
  INDEX ix_articulo_empresa (empresa_id),
  FULLTEXT KEY ftx_articulo (titulo, subtitulo, contenido_md)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Articulos blog SEO + LLM optimization';

-- ────────────────────────────────────────────────────────────────────
-- 7) blog_videos_youtube — videos espejados de YouTube
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS blog_videos_youtube (
  id INT AUTO_INCREMENT PRIMARY KEY,
  articulo_id INT NULL,
  empresa_id INT NOT NULL DEFAULT 5,
  video_id_yt VARCHAR(40) NULL,
  youtube_channel_id VARCHAR(60) NULL,
  titulo VARCHAR(260) NOT NULL,
  descripcion TEXT NULL,
  thumbnail_url VARCHAR(500) NULL,
  duracion_seg INT NULL,
  estado ENUM('borrador','programado','publicado','privado','no_listado','eliminado') NOT NULL DEFAULT 'borrador',
  fecha_publicacion DATETIME NULL,
  fecha_programada DATETIME NULL,
  script_md MEDIUMTEXT NULL,
  storyboard_json JSON NULL,
  tags_yt JSON NULL,
  views INT NOT NULL DEFAULT 0,
  likes INT NOT NULL DEFAULT 0,
  comments INT NOT NULL DEFAULT 0,
  last_stats_sync DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_video_yt (video_id_yt),
  INDEX ix_video_articulo (articulo_id),
  INDEX ix_video_estado (estado),
  INDEX ix_video_empresa (empresa_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Videos YouTube espejados, programados y ligados a articulos';

-- ────────────────────────────────────────────────────────────────────
-- 8) blog_generaciones_ai — registro auditable de uso AI
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS blog_generaciones_ai (
  id INT AUTO_INCREMENT PRIMARY KEY,
  articulo_id INT NULL,
  video_id INT NULL,
  tipo ENUM('miniatura','texto','outline','seo_meta','schema_org','video_script','optimizacion_llm','reescribir') NOT NULL,
  prompt TEXT NULL,
  modelo_usado VARCHAR(80) NULL COMMENT 'claude-opus-4-7, dall-e-3, gpt-4o-mini',
  parametros_json JSON NULL,
  resultado_url VARCHAR(500) NULL,
  resultado_texto MEDIUMTEXT NULL,
  costo_usd DECIMAL(8,4) NULL,
  tokens_input INT NULL,
  tokens_output INT NULL,
  duracion_ms INT NULL,
  generado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  generado_por_id INT NULL,
  aceptado TINYINT(1) NOT NULL DEFAULT 0,
  INDEX ix_gen_articulo_tipo (articulo_id, tipo),
  INDEX ix_gen_video (video_id),
  INDEX ix_gen_fecha (generado_en),
  INDEX ix_gen_modelo (modelo_usado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Auditoria de generaciones AI (Claude, DALL-E) con costos';

-- ────────────────────────────────────────────────────────────────────
-- 9) finanzas_snapshots — cache diario de KPIs ejecutivos
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS finanzas_snapshots (
  id INT AUTO_INCREMENT PRIMARY KEY,
  empresa_id INT NOT NULL DEFAULT 5,
  fecha DATE NOT NULL,
  mrr DECIMAL(12,2) NULL,
  arr DECIMAL(12,2) NULL,
  ingresos_mes DECIMAL(12,2) NULL,
  ingresos_mes_pasado DECIMAL(12,2) NULL,
  gastos_mes DECIMAL(12,2) NULL,
  utilidad DECIMAL(12,2) NULL,
  margen_pct DECIMAL(6,3) NULL,
  churn_rate_30d DECIMAL(6,3) NULL,
  churn_rate_90d DECIMAL(6,3) NULL,
  ltv DECIMAL(12,2) NULL,
  cac_estimado DECIMAL(12,2) NULL,
  alumnos_activos INT NULL,
  alumnos_nuevos_mes INT NULL,
  alumnos_vencidos_30d INT NULL,
  alumnos_proximos_vencer_30d INT NULL,
  cuentas_por_cobrar DECIMAL(12,2) NULL,
  suscripciones_stripe_activas INT NULL,
  breakdown_membresias_json JSON NULL,
  costo_ai_30d DECIMAL(10,4) NULL DEFAULT 0,
  calculado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_fin_empresa_fecha (empresa_id, fecha),
  INDEX ix_fin_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Snapshot diario de KPIs financieros ejecutivos';

-- ────────────────────────────────────────────────────────────────────
-- ROLLBACK (en caso de necesitar revertir):
-- ────────────────────────────────────────────────────────────────────
-- DROP TABLE IF EXISTS finanzas_snapshots;
-- DROP TABLE IF EXISTS blog_generaciones_ai;
-- DROP TABLE IF EXISTS blog_videos_youtube;
-- DROP TABLE IF EXISTS blog_articulos;
-- DROP TABLE IF EXISTS blog_categorias;
-- DROP TABLE IF EXISTS clase_recordatorios;
-- DROP TABLE IF EXISTS clase_inscripciones;
-- DROP TABLE IF EXISTS clases_vivas;
-- ALTER TABLE whatsapp_queue
--   DROP INDEX ix_wa_alumno,
--   DROP INDEX ix_wa_trigger,
--   DROP COLUMN contexto_json,
--   DROP COLUMN trigger_origen,
--   DROP COLUMN alumno_id;
