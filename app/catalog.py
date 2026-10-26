"""
Shared catalog helpers: display titles, prices, stock wording, and the one
JSON shape every storefront surface (shop grid, detail page, shop
assistant, visual search) uses for a product - so they can't drift apart.
"""
from .db import Design
from .garments import garment_label, color_label, DEFAULT_GARMENT

DEFAULT_PRINT_PRICE_INR = 899
CUSTOM_PRINT_PRICE_INR = 999
FREE_DELIVERY_OVER_INR = 999
DELIVERY_FEE_INR = 59

# Vision tags that describe "it's a picture" rather than what the picture IS
_GENERIC_TAGS = {
    "clothing", "text", "art", "drawing", "illustration", "graphic", "design", "cartoon",
    "pattern", "sketch", "painting", "poster", "font", "logo", "symbol", "clipart",
    "emblem", "vector graphics", "graphics", "creative arts", "visual arts", "shirt",
    "t-shirt", "sleeve", "outdoor", "indoor", "person", "decoration", "colorfulness",
}


def display_title(d: Design) -> str:
    if d.title:
        return d.title
    tags = [t.strip() for t in (d.vision_tags or "").split(",") if t.strip()]
    keep = [t for t in tags if t.lower() not in _GENERIC_TAGS][:2]
    subject = " & ".join(t.title() for t in keep) if keep else "Original"
    return f"{subject} {garment_label(d.garment)}" if d.garment != "linen-shirt" else subject


def price_of(d: Design) -> int:
    return d.price_inr or DEFAULT_PRINT_PRICE_INR


def mrp_of(price: int) -> int:
    """Struck-through 'list price' shown next to the selling price (a plain
    25% markup rounded to the nearest 10 - a display convention, the
    customer always pays `price`)."""
    return int(round(price * 1.25 / 10.0) * 10)


def stock_status(d: Design) -> dict:
    n = d.virtual_stock if d.virtual_stock is not None else 0
    if n <= 0:
        return {"state": "out", "label": "Sold out", "count": 0}
    if n <= 10:
        return {"state": "low", "label": f"Only {n} left", "count": n}
    return {"state": "in", "label": "In stock", "count": n}


def product_dict(d: Design, *, include_caption: bool = False) -> dict:
    kind = d.kind or "print"
    slots = ("front", "model") if kind == "plain" else ("front", "back", "model")
    out = {
        "id": d.id,
        "kind": kind,
        "title": display_title(d),
        "trend_summary": d.trend_summary,
        "sources": d.sources.split("\n") if d.sources else [],
        "mockups": {slot: f"/api/public/design/{d.id}/mockup/{slot}" for slot in slots},
        "garment": d.garment or DEFAULT_GARMENT,
        "garment_label": garment_label(d.garment),
        "color": d.color,
        "color_label": color_label(d.color),
        "price_inr": price_of(d),
        "mrp_inr": mrp_of(price_of(d)),
        "stock": stock_status(d),
        "created_at": d.created_at.isoformat(),
    }
    if include_caption:
        out["caption"] = d.social_caption
        out["hashtags"] = d.social_hashtags
    return out
