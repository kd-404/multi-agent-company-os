"""
Customer shop assistant: answers questions about the company and the
products (including live stock), scans a photo you send to find related
products, and hands problems to a human via a support ticket.

This is intentionally NOT the CEO assistant: that one is a Foundry agent
grounded in internal documents and is admin-only (RBAC). This one is
deterministic and grounded in two public sources only - the product
catalog in the database and app/company_info.py - so it cannot leak
anything internal, and every number it states (price, stock) is read from
the database at the moment of the question.
"""
import logging
import re

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..db import get_db, Design, SupportTicket, User
from ..auth import get_optional_user
from ..catalog import product_dict, display_title, price_of
from ..company_info import answer_faq, COMPANY
from ..garments import GARMENTS, COLORS
from ..similar import find_similar
from ..agent_log import log_activity

log = logging.getLogger(__name__)
router = APIRouter()

MAX_IMAGE_BYTES = 8 * 1024 * 1024

_GARMENT_WORDS = {
    "linen": "linen-shirt", "shirt": None, "t-shirt": "tshirt", "tshirt": "tshirt", "tee": "tshirt",
    "hoodie": "hoodie", "short": "shorts", "shorts": "shorts", "full sleeve": "long-sleeve",
    "long sleeve": "long-sleeve", "full-sleeve": "long-sleeve",
}
_COLOR_WORDS = {"white": "white", "black": "black", "beige": "beige", "sage": "sage", "green": "sage",
                "gray": "heather-gray", "grey": "heather-gray", "cream": "beige", "sand": "beige"}
_STOP = {"the", "a", "an", "is", "are", "in", "of", "for", "do", "you", "have", "any", "what", "which",
         "me", "my", "show", "stock", "available", "availability", "left", "much", "many", "how", "there",
         "about", "tell", "i", "to", "and", "or", "with", "on", "it", "this", "that", "please", "price",
         "cost", "size", "sizes", "product", "products", "item", "items", "get", "want", "looking"}


def _cards(designs, limit=4):
    return [product_dict(d) for d in designs[:limit]]


def _stock_line(d: Design) -> str:
    p = product_dict(d)
    s = p["stock"]
    status = {"in": f"in stock ({s['count']} available)", "low": f"running low - only {s['count']} left", "out": "sold out right now"}[s["state"]]
    return f"{p['title']} (₹{p['price_inr']}) is {status}."


def _search(db: Session, text: str) -> list[Design]:
    t = text.lower()
    garment = next((g for w, g in _GARMENT_WORDS.items() if w in t and g), None)
    color = next((c for w, c in _COLOR_WORDS.items() if re.search(rf"\b{w}\b", t)), None)
    q = db.query(Design).filter(Design.status == "approved")
    if garment:
        q = q.filter(Design.garment == garment)
    if color:
        q = q.filter(Design.color == color)
    designs = q.order_by(Design.created_at.desc()).all()

    words = [w for w in re.findall(r"[a-z]+", t) if w not in _STOP and len(w) > 2]
    words = [w for w in words if w not in _GARMENT_WORDS and w not in _COLOR_WORDS]
    if words:
        def hit(d: Design) -> int:
            hay = f"{display_title(d)} {d.vision_tags or ''} {d.trend_summary or ''}".lower()
            return sum(1 for w in words if w in hay)
        scored = sorted(((hit(d), d) for d in designs), key=lambda p: p[0], reverse=True)
        matched = [d for s, d in scored if s > 0]
        if matched:
            return matched
        if not (garment or color):
            return []
    return designs


@router.post("/api/public/assistant/chat")
async def assistant_chat(
    message: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    result = await _assistant_reply(message, file, db, user)
    try:  # observability only - never let logging break a shopper's chat
        photo = file is not None and bool(file.filename)
        shown = (message or "").strip()[:60] or "(photo)"
        n = len(result.get("products") or [])
        log_activity(db, "storefront", "ok",
                     f"Shopper asked: \"{shown}\" -> {'ticket #%s opened' % result['ticket_id'] if result.get('ticket_id') else '%d product(s) shown' % n if n else 'answered'}",
                     node="visual_search" if photo else "shop_assistant")
        if result.get("ticket_id"):
            log_activity(db, "support", "alert", f"Ticket #{result['ticket_id']} opened via the shop assistant.", node="support_desk")
    except Exception:
        log.exception("assistant activity log failed")
    return result


async def _assistant_reply(message, file, db, user):
    text = (message or "").strip()
    low = text.lower()

    # 1) Photo sent -> scan for related products
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > MAX_IMAGE_BYTES:
            return {"reply": "That image is too large - please send one under 8 MB.", "products": []}
        try:
            matches, tags = find_similar(db, data, limit=4)
        except ValueError:
            return {"reply": "I couldn't read that as an image - could you try a JPG or PNG?", "products": []}
        good = [(s, d) for s, d in matches if s >= 0.25] or matches[:3]
        if not good:
            return {"reply": "The collection is empty at the moment, so I couldn't find anything similar.", "products": []}
        seen = ", ".join([t for t in tags if t][:4])
        cards = []
        for s, d in good:
            c = product_dict(d)
            c["similarity"] = int(round(s * 100))
            cards.append(c)
        return {
            "reply": (f"I see {seen}. " if seen else "") + "These are the closest things we have:",
            "products": cards,
        }

    if not text:
        return {"reply": "Ask me anything about our products, stock, delivery or returns - or send a photo and I'll find similar pieces.", "products": []}

    # 2) Support hand-off
    if any(k in low for k in ("talk to support", "human", "complain", "complaint", "wrong item", "damaged",
                              "not received", "missing", "problem with", "refund my", "my order")):
        if user is None:
            return {"reply": "I can open a support ticket for you - please sign in first so the team knows who to reply to (Account, top right), then tell me again.", "products": [], "needs_login": True}
        ticket = SupportTicket(user_id=user.id, user_email=user.email, subject=text[:80], message=text, status="open")
        db.add(ticket)
        db.commit()
        return {"reply": f"I've opened support ticket #{ticket.id} with your message. The team will reply to {user.email}. Anything to add?", "products": [], "ticket_id": ticket.id}

    # 3) Greetings / help
    if re.fullmatch(r"(hi|hello|hey|hola|namaste|help|menu)[!. ]*", low):
        return {"reply": "Hi! I can check stock for a product, find shirts by colour or style, answer delivery and return questions, scan a photo for something similar, or open a support ticket. What would you like?", "products": []}

    # 4) Product / stock / catalog intents
    product_intent = any(k in low for k in (
        "stock", "available", "availability", "have", "show", "looking", "price", "cost", "linen", "hoodie",
        "shirt", "tee", "shorts", "t-shirt", "beige", "black", "white", "sage", "recommend", "suggest", "new", "best"))
    id_match = re.search(r"(?:#|id\s*|product\s*|design\s*)(\d{1,6})\b", low)
    if id_match:
        d = db.query(Design).filter(Design.id == int(id_match.group(1)), Design.status == "approved").first()
        if d:
            return {"reply": _stock_line(d), "products": _cards([d])}
        return {"reply": "I couldn't find a product with that number.", "products": []}

    if product_intent:
        found = _search(db, text)
        if found:
            ask_stock = any(k in low for k in ("stock", "available", "availability", "left", "have"))
            if ask_stock:
                lines = " ".join(_stock_line(d) for d in found[:3])
                return {"reply": lines, "products": _cards(found)}
            return {"reply": f"Here {'is' if len(found[:4]) == 1 else 'are'} what I found:", "products": _cards(found)}
        if not answer_faq(text):
            return {"reply": "I couldn't find a match for that. Try a colour or type (e.g. 'beige linen shirt', 'black hoodie'), or send a photo.", "products": []}

    # 5) Company / policy FAQ
    faq = answer_faq(text)
    if faq:
        return {"reply": faq, "products": []}

    # 6) Fallback
    return {"reply": f"I'm not sure about that one. I can help with {COMPANY['name']}'s products, stock, delivery, returns and custom prints - or type 'talk to support' to reach the team.", "products": []}
