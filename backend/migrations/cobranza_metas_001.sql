-- IMPORFACTORY Premium — metas de cobranza por asesor (TV leaderboard)
-- BD: imporfactory_premium · 2026-06-06 Sprint 36
CREATE TABLE IF NOT EXISTS cobranza_metas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asesor VARCHAR(120) NOT NULL UNIQUE,
    meta_mensual DECIMAL(12,2) NOT NULL DEFAULT 0,
    activo TINYINT(1) NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Metas iniciales propuestas (Daniel ajusta luego). Proporcionales a carga de alumnos por closer.
INSERT INTO cobranza_metas (asesor, meta_mensual) VALUES
    ('Adrian', 8000.00),
    ('Eve',    5000.00),
    ('Kathy',  5000.00),
    ('Karito', 3000.00),
    ('Diego',  3000.00)
ON DUPLICATE KEY UPDATE meta_mensual = VALUES(meta_mensual);
