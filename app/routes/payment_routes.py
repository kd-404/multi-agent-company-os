"""
Payment agent.

Two modes, decided purely by whether RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET
are set (Azure App Service -> Configuration -> Application settings):

  - Not configured (default): every "order" is simulated - logged to the
    AgentActivity feed with status="simulated" and says so in the message,
    never dressed up as a real transaction. This is what the admin "Run
    full pipeline" demo always uses, by design, so clicking it never tries
    to hit real Razorpay or move real money.
  - Configured: POST /api/public/payment/create-order/{design_id} opens a
    REAL Razorpay order; the shop frontend then opens Razorpay's hosted
    Checkout widget. This server never trusts the browser's word that a
    payment succeeded - /api/public/payment/verify independently recomputes
    Razorpay's HMAC signature over (order_id, payment_id) using the secret
    key before marking an Order "paid".
"""
import hashlib
import hmac
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, AgentActivity, Design, Order, User
from ..auth import require_admin, get_current_user
from ..agent_log import log_activity
from ..retry import with_retry

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_PRICE_INR = 899


def razorpay_configured() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def simulate_order(db: Session, design_id: int, amount_inr: int = DEFAULT_PRICE_INR) -> AgentActivity:
    """Returns the AgentActivity entry it wrote. Used by the admin demo
    pipeline (always) and by the public checkout when Razorpay isn't
    configured yet."""
    return log_activity(
        db, "payment", "simulated",
        f"Simulated a test order for design #{design_id}: ₹{amount_inr} "
        f"(Razorpay isn't connected yet - no real charge happened).",
        design_id=design_id,
    )


@router.post("/api/admin/payment/simulate/{design_id}")
def simulate_order_endpoint(
    design_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    entry = simulate_order(db, design_id)
    return {"design_id": design_id, "status": entry.status, "message": entry.message}


# ---------- Public checkout (one design at a time - no multi-item cart yet) ----------

@router.post("/api/public/payment/create-order/{design_id}")
def create_order(
    design_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    design = db.query(Design).filter(Design.id == design_id, Design.status == "approved").first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    if not razorpay_configured():
        entry = simulate_order(db, design_id)
        from .warehouse_routes import record_sale  # local import: avoids a module-load cycle with warehouse_routes
        record_sale(db, design_id, qty=1)
        return {
            "mode": "simulated",
            "design_id": design_id,
            "amount_inr": DEFAULT_PRICE_INR,
            "message": entry.message,
        }

    # Fixed (not per-attempt) receipt, so a RETRY of this same checkout
    # attempt reuses the same receipt value rather than minting a new one
    # per retry - Razorpay treats receipt as idempotency-adjacent, so this
    # keeps a retried request from being misread as a second, separate order.
    receipt = f"loomwell-{design_id}-{user.id}-{int(time.time())}"
    try:
        def _create_order():
            resp = httpx.post(
                "https://api.razorpay.com/v1/orders",
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                json={
                    "amount": DEFAULT_PRICE_INR * 100,  # paise
                    "currency": "INR",
                    "receipt": receipt,
                    "notes": {"design_id": str(design_id), "user_id": str(user.id)},
                },
                timeout=20.0,
            )
            resp.raise_for_status()
            return resp.json()

        data = with_retry(_create_order, label="razorpay_create_order")
    except Exception as e:
        log.exception("Razorpay order creation failed")
        log_activity(db, "payment", "error", f"Razorpay order creation failed: {type(e).__name__}: {e}", design_id=design_id)
        raise HTTPException(status_code=502, detail="Couldn't start checkout with Razorpay right now - try again shortly.")

    order = Order(
        design_id=design_id, user_id=user.id, amount_inr=DEFAULT_PRICE_INR,
        status="created", razorpay_order_id=data["id"],
    )
    db.add(order)
    db.commit()

    return {
        "mode": "live",
        "key_id": settings.RAZORPAY_KEY_ID,  # public key, safe to send to the browser
        "razorpay_order_id": data["id"],
        "amount": DEFAULT_PRICE_INR * 100,
        "currency": "INR",
        "design_id": design_id,
        "design_summary": design.trend_summary,
    }


class VerifyPaymentPayload(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/api/public/payment/verify")
def verify_payment(
    payload: VerifyPaymentPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if not razorpay_configured():
        raise HTTPException(status_code=409, detail="Razorpay isn't connected")

    order = (
        db.query(Order)
        .filter(Order.razorpay_order_id == payload.razorpay_order_id, Order.user_id == user.id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, payload.razorpay_signature):
        order.status = "failed"
        db.commit()
        log_activity(db, "payment", "error", f"Payment signature mismatch for design #{order.design_id} - rejected, not captured.", design_id=order.design_id)
        raise HTTPException(status_code=400, detail="Payment could not be verified")

    order.status = "paid"
    order.razorpay_payment_id = payload.razorpay_payment_id
    db.commit()

    log_activity(
        db, "payment", "ok",
        f"Real payment captured for design #{order.design_id}: ₹{order.amount_inr} "
        f"(Razorpay order {order.razorpay_order_id}).",
        design_id=order.design_id,
    )

    from .warehouse_routes import record_sale
    record_sale(db, order.design_id, qty=1)

    return {"status": "ok", "design_id": order.design_id}
