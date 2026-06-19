"""API Ventas IMPORCHAT — landing del webinar high-ticket (público, sin auth).

Endpoints:
  POST /api/imporchat/checkout  → crea Stripe Checkout Session + orden pendiente.
  POST /api/imporchat/webhook   → eventos Stripe (pago confirmado, cuotas, refund).

Ofertas definidas en services/stripe_service.OFERTAS:
  principal $497 · cuotas 3×$197 · lite $197 (downsell).

2026-06-19.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services import stripe_service

router = APIRouter(prefix="/api/imporchat", tags=["imporchat-ventas"])


# ─── Modelos ───
class CheckoutPayload(BaseModel):
    plan: str = Field(..., description="principal | cuotas | lite")
    email: Optional[EmailStr] = None


# ─── Helpers ───
async def _registrar_orden_pendiente(
    db: AsyncSession, *, plan: str, session_id: str, email: Optional[str],
    monto_centavos: int, cuotas_total: Optional[int], request: Request,
) -> int:
    ip = (request.headers.get("x-forwarded-for") or
          (request.client.host if request.client else "") or "").split(",")[0].strip()[:60]
    ua = (request.headers.get("user-agent") or "")[:400]
    res = await db.execute(text("""
        INSERT INTO imporchat_ordenes
            (plan, monto_usd, email, stripe_session_id, cuotas_total, estado, ip, user_agent)
        VALUES
            (:plan, :monto, :email, :sid, :cuotas, 'pendiente', :ip, :ua)
    """), {
        "plan": plan,
        "monto": round(monto_centavos / 100.0, 2),
        "email": email,
        "sid": session_id,
        "cuotas": cuotas_total,
        "ip": ip, "ua": ua,
    })
    await db.commit()
    return res.lastrowid


# ─── Checkout ───
@router.post("/checkout")
async def checkout(
    payload: CheckoutPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Crea la Checkout Session y devuelve la URL de pago de Stripe."""
    if payload.plan not in stripe_service.OFERTAS:
        raise HTTPException(400, "Plan inválido. Use principal, cuotas o lite.")

    base = str(request.base_url).rstrip("/")
    success_url = f"{base}/imporchat/gracias?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/imporchat?checkout=cancelado"

    try:
        session = await stripe_service.create_checkout_session(
            db,
            plan=payload.plan,
            success_url=success_url,
            cancel_url=cancel_url,
            email=str(payload.email) if payload.email else None,
        )
    except RuntimeError as e:
        # Falta de configuración (clave Stripe) → 503 con mensaje claro
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    try:
        await _registrar_orden_pendiente(
            db, plan=payload.plan, session_id=session["id"],
            email=str(payload.email) if payload.email else None,
            monto_centavos=session["monto_centavos"],
            cuotas_total=session["cuotas_total"], request=request,
        )
    except Exception:
        # No bloquear el pago si falla el registro local; el webhook reconcilia.
        pass

    return {"ok": True, "url": session["url"], "session_id": session["id"], "plan": payload.plan}


# ─── Webhook ───
async def _marcar_pagado_por_session(db: AsyncSession, obj: dict) -> None:
    session_id = obj.get("id")
    customer_details = obj.get("customer_details") or {}
    email = customer_details.get("email") or obj.get("customer_email")
    nombre = customer_details.get("name")
    telefono = customer_details.get("phone")
    pi = obj.get("payment_intent")
    sub = obj.get("subscription")
    customer = obj.get("customer")
    es_sub = (obj.get("mode") == "subscription")
    estado = "activo" if es_sub else "pagado"

    await db.execute(text("""
        UPDATE imporchat_ordenes SET
            estado = :estado,
            email = COALESCE(:email, email),
            nombre = COALESCE(:nombre, nombre),
            telefono = COALESCE(:telefono, telefono),
            stripe_payment_intent = COALESCE(:pi, stripe_payment_intent),
            stripe_subscription_id = COALESCE(:sub, stripe_subscription_id),
            stripe_customer_id = COALESCE(:cust, stripe_customer_id),
            cuotas_pagadas = CASE WHEN :es_sub THEN GREATEST(cuotas_pagadas, 1) ELSE cuotas_pagadas END
        WHERE stripe_session_id = :sid
    """), {
        "estado": estado, "email": email, "nombre": nombre, "telefono": telefono,
        "pi": pi, "sub": sub, "cust": customer, "es_sub": es_sub, "sid": session_id,
    })
    await db.commit()


async def _contar_cuota(db: AsyncSession, subscription_id: str) -> None:
    """invoice.paid de un plan de cuotas: suma 1 y cancela tras la 3ª."""
    row = (await db.execute(text("""
        SELECT id, cuotas_total, cuotas_pagadas
        FROM imporchat_ordenes
        WHERE stripe_subscription_id = :sub LIMIT 1
    """), {"sub": subscription_id})).mappings().first()
    if not row:
        return
    pagadas = int(row["cuotas_pagadas"] or 0) + 1
    total = int(row["cuotas_total"] or 3)
    completado = pagadas >= total
    await db.execute(text("""
        UPDATE imporchat_ordenes
        SET cuotas_pagadas = :pag,
            estado = CASE WHEN :done THEN 'completado' ELSE 'activo' END
        WHERE id = :id
    """), {"pag": pagadas, "done": completado, "id": row["id"]})
    await db.commit()
    if completado:
        # Plan de pagos liquidado: cancelar la suscripción para no cobrar de más.
        try:
            await stripe_service.cancel_subscription(db, subscription_id)
        except Exception:
            pass


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Recibe eventos de Stripe. Verifica firma si hay STRIPE_WEBHOOK_SECRET."""
    raw = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = await stripe_service._get_webhook_secret(db)

    if secret:
        if not stripe_service.verify_webhook_signature(raw, sig, secret):
            raise HTTPException(400, "Firma de webhook inválida")
    # Si no hay secret configurado, se acepta sin verificar (modo dev/sandbox).

    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Payload no es JSON válido")

    tipo = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if tipo == "checkout.session.completed":
        await _marcar_pagado_por_session(db, obj)

    elif tipo == "invoice.paid":
        # Cargo recurrente de un plan de cuotas. Solo cuenta los ciclos > 1
        # (el primero ya se marcó en checkout.session.completed).
        sub = obj.get("subscription")
        reason = obj.get("billing_reason")
        if sub and reason == "subscription_cycle":
            await _contar_cuota(db, sub)

    elif tipo in ("charge.refunded", "refund.created"):
        pi = obj.get("payment_intent")
        if pi:
            await db.execute(text("""
                UPDATE imporchat_ordenes SET estado = 'reembolsado'
                WHERE stripe_payment_intent = :pi
            """), {"pi": pi})
            await db.commit()

    elif tipo == "customer.subscription.deleted":
        sub = obj.get("id")
        if sub:
            await db.execute(text("""
                UPDATE imporchat_ordenes
                SET estado = CASE WHEN estado = 'completado' THEN 'completado' ELSE 'cancelado' END
                WHERE stripe_subscription_id = :sub
            """), {"sub": sub})
            await db.commit()

    return {"received": True}
