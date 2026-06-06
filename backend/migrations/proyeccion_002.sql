-- IMPORFACTORY Premium — Proyector de ventas + metas fundamentadas (Sprint 36.2)
-- BD: imporfactory_premium · 2026-06-06
CREATE TABLE IF NOT EXISTS ventas_proyeccion (
    id INT PRIMARY KEY,
    inversion_ads DECIMAL(12,2) NOT NULL DEFAULT 5000,
    roas DECIMAL(6,2) NOT NULL DEFAULT 3.00,
    venta_organica DECIMAL(12,2) NOT NULL DEFAULT 5000,
    ticket_promedio DECIMAL(10,2) NOT NULL DEFAULT 486,
    pct_cobranza DECIMAL(5,2) NOT NULL DEFAULT 100.00,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO ventas_proyeccion (id, inversion_ads, roas, venta_organica, ticket_promedio, pct_cobranza)
VALUES (1, 5000, 3.00, 5000, 486, 100)
ON DUPLICATE KEY UPDATE id = id;
