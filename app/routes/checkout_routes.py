"""
Demo checkout - a full-page, Amazon/Flipkart-style flow (login -> address ->
order summary -> payment) that mimics a real checkout but takes no money.

What it is for: showing the *funnel*. Every step a shopper reaches is its
own CheckoutEvent row (opened -> address -> payment -> paid), so the admin
"Checkout Funnel" panel can answer "how many people came, how many got to
payment, where did they drop off, and who were they" - the data a real
payment integration would feed an analytics agent, without the integration.

What it deliberately does NOT do: collect card numbers, CVV or UPI IDs, or
talk to a payment provider. Payment is a *method choice* only; a form that
looked like it collected payment credentials - even fake ones - would be
indistinguishable from a credential-harvesting page. Totals are always
recomputed on the server; the browser's numbers are never trusted.

An item is either a catalog product ("design", incl. the plain linen line)
or a shopper's own studio creation ("custom", owner-only).
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, CheckoutEvent, Design, CustomDesign, User
from ..auth import get_current_user, require_admin
from ..agent_log import log_activity
from ..catalog import (
    product_dict, price_of, mrp_of, display_title,
    CUSTOM_PRINT_PRICE_INR, FREE_DELIVERY_OVER_INR, DELIVERY_FEE_INR,
)
from ..garments import GARMENTS

log = logging.getLogger(__name__)
router = APIRouter()

SIZES = ["S", "M", "L", "XL"]
PAYMENT_METHODS = {"upi": "UPI", "card": "Credit / Debit card", "netbanking": "Net banking",
                   "wallet": "Wallets", "cod": "Pay on delivery"}
COUPONS = {"WELCOME10": ("10% off your order (up to ₹200)", 10, 200)}
STAGES = ("opened", "address", "payment", "paid")


def _resolve_item(kind: str, item_id: int, db: Session, user: User) -> dict:
    if kind == "design":
        d = db.query(Design).filter(Design.id == item_id, Design.status == "approved").first()
        if not d:
            raise HTTPException(status_code=404, detail="Product not found")
        p = product_dict(d)
        return {"kind": "design", "id": d.id, "title": p["title"], "subtitle": f"{p['garment_label']} · {p['color_label']}",
                "image": p["mockups"]["front"], "price": p["price_inr"], "mrp": p["mrp_inr"],
                "stock": p["stock"], "plain": p["kind"] == "plain", "design": d}
    if kind == "custom":
        cd = db.query(CustomDesign).filter(CustomDesign.id == item_id).first()
        if not cd or cd.user_id != user.id:
            raise HTTPException(status_code=404, detail="Design not found")
        label = GARMENTS.get(cd.garment, {}).get("label", cd.garment)
        return {"kind": "custom", "id": cd.id, "title": f"Your custom {label}", "subtitle": f"{label} · {cd.color.replace('-', ' ').title()}",
                "image": f"/api/studio/design/{cd.id}/preview", "price": CUSTOM_PRINT_PRICE_INR,
                "mrp": mrp_of(CUSTOM_PRINT_PRICE_INR), "stock": {"state": "in", "label": "Made to order", "count": 999},
                "plain": False, "design": None}
    raise HTTPException(status_code=404, detail="Unknown item type")


def _totals(item: dict, quantity: int, coupon: str | None) -> dict:
    quantity = max(1, min(10, quantity))
    mrp_total = item["mrp"] * quantity
    subtotal = item["price"] * quantity
    discount_on_mrp = mrp_total - subtotal
    coupon_discount, coupon_note = 0, None
    code = (coupon or "").strip().upper()
    if code:
        if code in COUPONS:
            note, pct, cap = COUPONS[code]
            coupon_discount = min(cap, subtotal * pct // 100)
            coupon_note = f"{code} applied - {note}"
        else:
            coupon_note = "That coupon code isn't valid"
            code = ""
    payable_items = subtotal - coupon_discount
    delivery = 0 if payable_items >= FREE_DELIVERY_OVER_INR else DELIVERY_FEE_INR
    total = payable_items + delivery
    return {
        "quantity": quantity, "mrp_total": mrp_total, "discount_on_mrp": discount_on_mrp,
        "subtotal": subtotal, "coupon": code or None, "coupon_discount": coupon_discount, "coupon_note": coupon_note,
        "delivery": delivery, "total": total, "you_save": discount_on_mrp + coupon_discount,
        "free_delivery_over": FREE_DELIVERY_OVER_INR,
    }


def _log_event(db: Session, item: dict, user: User, stage: str, amount: int, **extra) -> CheckoutEvent:
    e = CheckoutEvent(design_id=item["id"], user_id=user.id, user_email=user.email, stage=stage, amount_inr=amount,
                      item_kind=item["kind"], **extra)
    db.add(e)
    db.commit()
    try:
        label = {"opened": "opened checkout", "address": "entered an address", "payment": "reached payment", "paid": "placed an order"}[stage]
        log_activity(db, "payment", "ok", f"{user.email.split('@')[0]} {label} (₹{amount}, {item['kind']} #{item['id']}).",
                     design_id=item["id"] if item["kind"] == "design" else None, node="checkout")
    except Exception:
        log.exception("funnel activity log failed")
    return e


def _recent_exists(db: Session, item: dict, user: User, stage: str, minutes: int = 30) -> bool:
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return db.query(CheckoutEvent).filter(
        CheckoutEvent.user_id == user.id, CheckoutEvent.design_id == item["id"],
        CheckoutEvent.item_kind == item["kind"], CheckoutEvent.stage == stage, CheckoutEvent.created_at >= since,
    ).first() is not None


@router.get("/api/checkout/item/{kind}/{item_id}")
def checkout_item(kind: str, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Entry point of the funnel - logged once per shopper/item per 30 minutes."""
    item = _resolve_item(kind, item_id, db, user)
    if not _recent_exists(db, item, user, "opened"):
        _log_event(db, item, user, "opened", item["price"])
    return {
        "kind": kind, "id": item["id"], "title": item["title"], "subtitle": item["subtitle"], "image": item["image"],
        "price": item["price"], "mrp": item["mrp"], "stock": item["stock"], "sizes": SIZES,
        "user_email": user.email, "payment_methods": PAYMENT_METHODS,
        "free_delivery_over": FREE_DELIVERY_OVER_INR, "delivery_fee": DELIVERY_FEE_INR,
        "totals": _totals(item, 1, None),
    }


@router.post("/api/checkout/quote/{kind}/{item_id}")
def checkout_quote(
    kind: str, item_id: int, quantity: int = Form(default=1), coupon: str = Form(default=""),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    item = _resolve_item(kind, item_id, db, user)
    return _totals(item, quantity, coupon)


def _validate_address(name, phone, pincode, address, city, state) -> dict:
    name, address, city, state = name.strip(), address.strip(), city.strip(), state.strip()
    phone = re.sub(r"[\s\-+]", "", phone)
    phone = phone[-10:] if phone.startswith("91") and len(phone) == 12 else phone
    errors = {}
    if len(name) < 2:
        errors["name"] = "Enter your full name"
    if not re.fullmatch(r"[6-9]\d{9}", phone):
        errors["phone"] = "Enter a valid 10-digit mobile number"
    if not re.fullmatch(r"\d{6}", pincode.strip()):
        errors["pincode"] = "Enter a 6-digit pincode"
    if len(address) < 8:
        errors["address"] = "Enter your house no., building and street"
    if len(city) < 2:
        errors["city"] = "Enter your city"
    if len(state) < 2:
        errors["state"] = "Select your state"
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    return {"name": name, "phone": phone, "pincode": pincode.strip(), "address": address, "city": city, "state": state}


def _join_address(a: dict) -> str:
    return f"{a['address']}, {a['city']}, {a['state']} - {a['pincode']} · Ph {a['phone']}"


@router.post("/api/checkout/address/{kind}/{item_id}")
def checkout_address(
    kind: str, item_id: int,
    name: str = Form(...), phone: str = Form(...), pincode: str = Form(...), address: str = Form(...),
    city: str = Form(...), state: str = Form(...), quantity: int = Form(default=1), coupon: str = Form(default=""),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Shopper finished the address step -> funnel stage 'address'. Returns
    the delivery estimate and totals the next step displays."""
    item = _resolve_item(kind, item_id, db, user)
    a = _validate_address(name, phone, pincode, address, city, state)
    totals = _totals(item, quantity, coupon)
    _log_event(db, item, user, "address", totals["total"], shipping_name=a["name"], shipping_address=_join_address(a), quantity=totals["quantity"])
    eta = datetime.now(timezone.utc) + timedelta(days=5)
    return {"status": "ok", "totals": totals, "eta": eta.strftime("%a, %d %b"), "address_line": _join_address(a)}


@router.post("/api/checkout/payment/{kind}/{item_id}")
def checkout_payment_step(
    kind: str, item_id: int, quantity: int = Form(default=1), coupon: str = Form(default=""),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Shopper reached the payment step -> funnel stage 'payment'."""
    item = _resolve_item(kind, item_id, db, user)
    totals = _totals(item, quantity, coupon)
    if not _recent_exists(db, item, user, "payment", minutes=10):
        _log_event(db, item, user, "payment", totals["total"], quantity=totals["quantity"])
    return {"status": "ok", "totals": totals}


@router.post("/api/checkout/confirm/{kind}/{item_id}")
def checkout_confirm(
    kind: str, item_id: int,
    name: str = Form(...), phone: str = Form(...), pincode: str = Form(...), address: str = Form(...),
    city: str = Form(...), state: str = Form(...),
    size: str = Form(...), quantity: int = Form(default=1), coupon: str = Form(default=""),
    payment_method: str = Form(...),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Place the (demo) order. No charge happens anywhere in this call."""
    item = _resolve_item(kind, item_id, db, user)
    a = _validate_address(name, phone, pincode, address, city, state)
    if size not in SIZES:
        raise HTTPException(status_code=422, detail={"errors": {"size": "Choose a size"}})
    if payment_method not in PAYMENT_METHODS:
        raise HTTPException(status_code=422, detail={"errors": {"payment": "Choose a payment method"}})
    totals = _totals(item, quantity, coupon)
    if item["kind"] == "design" and item["design"].virtual_stock < totals["quantity"]:
        raise HTTPException(status_code=409, detail="Sorry - that item just sold out or doesn't have enough stock")

    ev = _log_event(db, item, user, "paid", totals["total"], shipping_name=a["name"], shipping_address=_join_address(a),
                    payment_method=payment_method, size=size, quantity=totals["quantity"])
    log_activity(
        db, "payment", "simulated",
        f"Demo order LW{ev.id:06d}: {item['title']} x{totals['quantity']} ({size}) for {user.email}, "
        f"₹{totals['total']} via {PAYMENT_METHODS[payment_method]} - no real charge, no payment provider connected.",
        design_id=item["id"] if item["kind"] == "design" else None,
    )
    if item["kind"] == "design":
        from .warehouse_routes import record_sale  # local import: avoids a module-load cycle
        record_sale(db, item["id"], qty=totals["quantity"])

    eta = datetime.now(timezone.utc) + timedelta(days=5)
    return {
        "status": "ok", "order_id": f"LW{ev.id:06d}", "title": item["title"], "subtitle": item["subtitle"], "image": item["image"],
        "size": size, "quantity": totals["quantity"], "totals": totals, "payment_method": PAYMENT_METHODS[payment_method],
        "address_line": _join_address(a), "name": a["name"], "eta": eta.strftime("%a, %d %b"),
    }


@router.get("/api/admin/checkout-funnel/summary")
def checkout_funnel_summary(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """
    Backs the admin "Checkout Funnel" panel: how many shoppers reached each
    step (opened -> address -> payment -> paid), where they dropped off, and
    the recent event-by-event feed with who they were.
    """
    counts = {s: db.query(CheckoutEvent).filter(CheckoutEvent.stage == s).count() for s in STAGES}
    opened, paid = counts["opened"], counts["paid"]
    stages = []
    prev = None
    for s in STAGES:
        n = counts[s]
        stages.append({"stage": s, "count": n, "pct_of_opened": round(100 * n / opened) if opened else 0,
                       "dropped_from_prev": (max(0, prev - n) if prev is not None else 0)})
        prev = n

    recent = db.query(CheckoutEvent).order_by(CheckoutEvent.created_at.desc()).limit(100).all()
    design_ids = {e.design_id for e in recent if (e.item_kind or "design") == "design"}
    designs = {d.id: d for d in db.query(Design).filter(Design.id.in_(design_ids)).all()} if design_ids else {}

    events = []
    for e in recent:
        kind = e.item_kind or "design"
        if kind == "design":
            d = designs.get(e.design_id)
            label = display_title(d) if d else "(deleted product)"
        else:
            label = f"Custom print #{e.design_id}"
        events.append({
            "id": e.id, "stage": e.stage, "user_email": e.user_email, "design_id": e.design_id, "item_kind": kind,
            "design_summary": label, "amount_inr": e.amount_inr, "shipping_name": e.shipping_name,
            "shipping_address": e.shipping_address, "payment_method": PAYMENT_METHODS.get(e.payment_method or "", e.payment_method),
            "size": e.size, "quantity": e.quantity, "created_at": e.created_at.isoformat(),
        })

    return {
        "opened": opened, "paid": paid, "abandoned": max(0, opened - paid),
        "conversion_pct": round(100 * paid / opened) if opened else 0,
        "stages": stages, "events": events,
    }
