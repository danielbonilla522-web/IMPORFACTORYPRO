-- IMPORFACTORY Premium — tracking de clicks en CTA del blog (Sprint 37)
-- BD: imporfactory_premium · 2026-06-07
CREATE TABLE IF NOT EXISTS blog_clics_cta (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    slug VARCHAR(220) NOT NULL,
    tipo_cta ENUM('club','whatsapp') NOT NULL DEFAULT 'club',
    articulo_id INT NULL,
    referrer VARCHAR(300) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_clics_slug (slug),
    INDEX ix_clics_fecha (created_at),
    INDEX ix_clics_art (articulo_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
