-- ════════════════════════════════════════════════════════════════════
-- IMPORCHAT Ventas — Landing webinar high-ticket (empresa_id=5)
-- Migración: imporchat_ventas_001.sql
-- Fecha: 2026-06-19
-- Tabla de órdenes de venta del lanzamiento IMPORCHAT vía Stripe Checkout.
-- Basada en el Playbook de Lanzamiento IMPORCHAT (oferta $497 + plan de
-- pagos 3×$197 + downsell LITE $197).
-- ════════════════════════════════════════════════════════════════════
-- ROLLBACK: DROP TABLE IF EXISTS imporchat_ordenes;

SET NAMES utf8mb4;

-- ────────────────────────────────────────────────────────────────────
-- imporchat_ordenes — una fila por intento de compra (Checkout Session)
-- Vive en la BD propia imporfactory_premium (get_db por defecto).
-- ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS imporchat_ordenes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  empresa_id INT NOT NULL DEFAULT 5,

  -- Qué compró
  plan ENUM('principal','cuotas','lite') NOT NULL,
  monto_usd DECIMAL(10,2) NOT NULL COMMENT 'Monto del primer cargo (cuota o pago único)',
  moneda VARCHAR(8) NOT NULL DEFAULT 'usd',

  -- Datos del comprador (lo que devuelve Stripe Checkout)
  email VARCHAR(200) NULL,
  nombre VARCHAR(200) NULL,
  telefono VARCHAR(40) NULL,

  -- Referencias Stripe
  stripe_session_id   VARCHAR(120) NULL UNIQUE,
  stripe_payment_intent VARCHAR(120) NULL,
  stripe_subscription_id VARCHAR(120) NULL,
  stripe_customer_id  VARCHAR(120) NULL,

  -- Control del plan de cuotas (3 cargos de $197)
  cuotas_total  INT NULL COMMENT 'NULL = pago único; 3 = plan de pagos',
  cuotas_pagadas INT NOT NULL DEFAULT 0,

  estado ENUM('pendiente','pagado','activo','completado','cancelado','reembolsado')
         NOT NULL DEFAULT 'pendiente',

  -- Atribución
  ip VARCHAR(60) NULL,
  user_agent VARCHAR(400) NULL,
  utm_json JSON NULL,

  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  INDEX ix_ico_estado (estado),
  INDEX ix_ico_email (email),
  INDEX ix_ico_plan (plan),
  INDEX ix_ico_sub (stripe_subscription_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Órdenes de venta IMPORCHAT (webinar high-ticket) vía Stripe Checkout';
