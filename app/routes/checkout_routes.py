"""
Demo checkout - a Loomwell-branded (not a Razorpay look-alike) mimic
checkout flow, used whenever real payment isn't wired up yet (i.e.
always, until Razorpay KYC clears - see payment_routes.py for the real
integration, which this doesn't touch or replace).

Why this exists separately from payment_routes.py's simulate_order(): that
function only ever wrote one AgentActivity line ("simulated a test
order"), with no funnel visibility - no way to tell how many shoppers
actually reached checkout versus how many of THOSE completed it, and no
captured shipping details, even fictional ones. This is the fix: every
checkout-modal open and every completed demo confirmation is its own
CheckoutEvent row (app/db.py), queryable by the admin "Checkout Funnel"
panel as a real (if simulated) conversion funnel with per-shopper detail,
not just a cumulative count.

No real payment data is ever asked for here - no card number, no CVV, no
UPI id - on purpose: a form that LOOKED like it collected payment details,
even fake ones, would read as a fake checkout/credential-collection page.
This instead collects only a name + shipping address (clearly labeled as
a demo, no real charge), which is enough to make the funnel realistic
without reproducing the part of a checkout flow that would actually be
sensitive if it were real.
"""
import logging

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, CheckoutEvent, Design, User
from ..auth import get_current_user, require_admin
from ..agent_log import log_activity

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_PRICE_INR = 899


def _log_checkout_event(
    db: Session, design_id: int, user: User, stage: str,
    amount_inr: int = DEFAULT_PRICE_INR,
    shipping_name: str | None = None, shipping_address: str | None = None,
) -> CheckoutEvent:
    event = CheckoutEvent(
        design_id=design_id, user_id=user.id, user_email=user.email,
        stage=stage, amount_inr=amount_inr,
        shipping_name=shipping_name, shipping_address=shipping_address,
    )
    db.add(event)
    db.commit()
    return event


@router.post("/api/public/checkout/open/{design_id}")
def open_checkout(
    design_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Called the moment the demo checkout modal opens - logs the funnel's
    entry point, before the shopper has typed anything."""
    design = db.query(Design).filter(Design.id == design_id, Design.status == "approved").first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    _log_checkout_event(db, design_id, user, "opened")

    return {
        "design_id": design_id,
        "amount_inr": DEFAULT_PRICE_INR,
        "design_summary": design.trend_summary,
        "garment_label": design.garment,
        "color_label": design.color,
        "user_email": user.email,
    }


@router.post("/api/public/checkout/confirm/{design_id}")
def confirm_checkout(
    design_id: int,
    shipping_name: str = Form(...),
    shipping_address: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Completes the demo checkout - no real charge happens anywhere in
    this call. Logs the "paid" funnel event, decrements virtual stock the
    same way a real sale would (see warehouse_routes.record_sale), and
    reports to the Payment agent's activity feed so this still shows up
    on "Agent Status" exactly like the old one-line simulated order did."""
    design = db.query(Design).filter(Design.id == design_id, Design.status == "approved").first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    name = shipping_name.strip()
    address = shipping_address.strip()
    if not name or not address:
        raise HTTPException(status_code=400, detail="Name and shipping address are required")

    _log_checkout_event(
        db, design_id, user, "paid",
        shipping_name=name, shipping_address=address,
    )

    log_activity(
        db, "payment", "simulated",
        f"Demo checkout completed for design #{design_id} by {user.email}: "
        f"₹{DEFAULT_PRICE_INR} (no real charge - Razorpay isn't connected yet).",
        design_id=design_id,
    )

    from .warehouse_routes import record_sale  # local import: avoids a module-load cycle
    record_sale(db, design_id, qty=1)

    return {"status": "ok", "design_id": design_id, "amount_inr": DEFAULT_PRICE_INR}


@router.get("/api/admin/checkout-funnel/summary")
def checkout_funnel_summary(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """
    Backs the admin "Checkout Funnel" panel: how many shoppers reached
    checkout, how many of those completed it, and the recent event-by-
    event feed (who, which design, which stage, when) - this is the
    direct answer to "how many users came till payment and gone, with
    user details."
    """
    opened_count = db.query(CheckoutEvent).filter(CheckoutEvent.stage == "opened").count()
    paid_count = db.query(CheckoutEvent).filter(CheckoutEvent.stage == "paid").count()
    conversion_pct = round(100 * paid_count / opened_count) if opened_count else 0

    recent = (
        db.query(CheckoutEvent)
        .order_by(CheckoutEvent.created_at.desc())
        .limit(100)
        .all()
    )
    design_ids = {e.design_id for e in recent}
    designs_by_id = {
        d.id: d for d in db.query(Design).filter(Design.id.in_(design_ids)).all()
    } if design_ids else {}

    events = []
    for e in recent:
        d = designs_by_id.get(e.design_id)
        events.append({
            "id": e.id,
            "stage": e.stage,
            "user_email": e.user_email,
            "design_id": e.design_id,
            "design_summary": (d.trend_summary[:80] + "...") if d and len(d.trend_summary) > 80 else (d.trend_summary if d else "(deleted design)"),
            "amount_inr": e.amount_inr,
            "shipping_name": e.shipping_name,
            "shipping_address": e.shipping_address,
            "created_at": e.created_at.isoformat(),
        })

    return {
        "opened": opened_count,
        "paid": paid_count,
        "abandoned": max(0, opened_count - paid_count),
        "conversion_pct": conversion_pct,
        "events": events,
    }
