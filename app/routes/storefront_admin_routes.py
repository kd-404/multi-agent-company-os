"""
Admin tools that build out the storefront itself:

  * the Linen Edit - a plain (no graphic) linen shirt line that sits next to
    the AI-printed tees, so the shop isn't only graphic T-shirts;
  * brand imagery - the hero model shot, vintage farm/horse photographs and
    section banners, generated once with the image model and served from the
    database (App Service's disk is wiped on restart).

Every generation here is ONE image per request (or two for a linen product)
so a call stays well under the App Service request timeout; the admin UI
loops over items and shows progress.
"""
import logging

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, Design, ProductPhoto, BrandAsset, User
from ..auth import require_admin
from ..image_client import generate_image
from ..agent_log import log_activity, step
from ..visual_search import extract_signals, tags_to_text, color_to_text

log = logging.getLogger(__name__)
router = APIRouter()

_PEOPLE = "The model is an invented, generic person - not a real, named or identifiable individual."

LINEN_ITEMS = [
    {"title": "Sand Linen Camp-Collar Shirt", "color": "beige", "price": 1499,
     "blurb": "A relaxed camp-collar shirt in washed sand linen. Light, breathable and softly structured - made to be worn loose with the sleeves rolled."},
    {"title": "Ivory Linen Button-Down", "color": "white", "price": 1499,
     "blurb": "The easy white shirt: a clean button-down in ivory linen that gets softer with every wash. Tuck it in or leave it open over a tee."},
    {"title": "Sage Linen Resort Shirt", "color": "sage", "price": 1599,
     "blurb": "A muted sage resort shirt with a wide collar and a drapey, easy fall. Quiet colour, summer-evening mood."},
    {"title": "Oat Linen Overshirt", "color": "beige", "price": 1799,
     "blurb": "A slightly heavier oat linen overshirt with a straight hem - worn as a light jacket or buttoned up on its own."},
    {"title": "Chalk Linen Band-Collar Shirt", "color": "white", "price": 1599,
     "blurb": "A minimal band-collar shirt in chalk-white linen. No fuss, a clean neckline and a long, easy shape."},
    {"title": "Dune Linen Short-Sleeve Shirt", "color": "beige", "price": 1399,
     "blurb": "A short-sleeve linen shirt in warm dune beige - made for long lunches, markets and slow afternoons."},
]

_LINEN_SETTINGS = [
    "a sunlit countryside farm with a weathered wooden fence and soft golden-hour light",
    "a quiet sunlit stone courtyard with warm shadows and a few potted olive trees",
    "a wheat field at golden hour, warm haze, shallow depth of field",
    "a rustic barn doorway with warm natural light and straw-colored tones",
    "a soft beige studio wall with gentle window light",
    "a sunlit linen-draped table and open shutters, warm and airy",
]


def _linen_prompts(i: int, item: dict) -> dict:
    from ..garments import COLORS, GARMENTS
    fabric = f"{COLORS[item['color']]['photo_desc']} {GARMENTS['linen-shirt']['photo_desc']}"
    return {
        "front": (
            f"Professional e-commerce product photograph of {fabric}: '{item['title']}'. Flat lay shot from directly "
            f"above on a warm off-white surface, shirt buttoned and centered, visible linen weave and natural soft wrinkles, "
            f"no text, no logo, no print, soft diffused daylight. Photorealistic, high resolution."
        ),
        "model": (
            f"Editorial fashion photograph of a model wearing {fabric}, half-tucked, sleeves casually rolled, in "
            f"{_LINEN_SETTINGS[i % len(_LINEN_SETTINGS)]}. Three-quarter body shot, natural relaxed pose, beige and brown "
            f"earth-tone styling, vintage film warmth, soft grain. {_PEOPLE} No text, no logos. Photorealistic."
        ),
    }


@router.get("/api/admin/linen/status")
def linen_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    existing = {d.title for d in db.query(Design).filter(Design.kind == "plain").all()}
    return {"items": [{"index": i, "title": it["title"], "created": it["title"] in existing} for i, it in enumerate(LINEN_ITEMS)]}


@router.post("/api/admin/linen/create/{index}")
def create_linen_item(index: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Photographs ONE linen shirt (flat lay + worn shot, 2 image calls) and
    adds it to the catalog as an approved plain product. Idempotent."""
    if not 0 <= index < len(LINEN_ITEMS):
        raise HTTPException(status_code=404, detail="No such linen item")
    item = LINEN_ITEMS[index]
    if db.query(Design).filter(Design.kind == "plain", Design.title == item["title"]).first():
        return {"status": "exists", "title": item["title"]}

    prompts = _linen_prompts(index, item)
    try:
        with step(db, "design", "linen_atelier", f"Photographing '{item['title']}'") as st:
            front = generate_image(prompts["front"], size="1024x1024")
            model = generate_image(prompts["model"], size="1024x1024")
            st.done = f"'{item['title']}' photographed (flat lay + on model)."
    except Exception as e:
        log.exception("Linen item generation failed")
        log_activity(db, "design", "error", f"Linen item '{item['title']}' failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail=f"Image generation failed: {type(e).__name__}: {e}")

    tags_text, color_text = None, None
    try:
        tags, color = extract_signals(front)
        tags_text, color_text = tags_to_text(tags), color_to_text(color)
    except Exception:
        log.exception("Vision tagging failed for linen item (non-fatal)")

    design = Design(
        trend_query="Linen Edit", trend_summary=item["blurb"], sources="",
        image_prompt=prompts["front"], image_data=front,
        vision_tags=tags_text, dominant_color=color_text,
        garment="linen-shirt", color=item["color"], status="approved",
        kind="plain", title=item["title"], price_inr=item["price"], virtual_stock=40,
    )
    db.add(design)
    db.commit()
    db.refresh(design)
    db.add(ProductPhoto(design_id=design.id, slot="front", image_data=front, verified=None))
    db.add(ProductPhoto(design_id=design.id, slot="model", image_data=model, verified=None))
    db.commit()
    log_activity(db, "design", "ok", f"Added linen product '{item['title']}' (#{design.id}) to the catalog.", design_id=design.id)
    return {"status": "created", "design_id": design.id, "title": item["title"]}


# ---------------- Brand imagery ----------------

_PALETTE = "warm beige, ivory, caramel and chocolate-brown palette, soft natural light"

BRAND_ASSETS = {
    "hero": ("1536x1024",
             "Luxury editorial fashion photograph: a tall, elegant supermodel posing confidently, wearing a crisp white "
             "linen shirt and wide-leg beige trousers, full body, warm beige seamless studio backdrop, soft directional "
             "window light, calm and minimal, generous empty space on the left side of the frame. " + _PALETTE + ". " + _PEOPLE),
    "farm-1": ("1024x1536",
               "Vintage 35mm film photograph, warm faded tones and fine grain: a model in a loose beige linen shirt stands "
               "beside a chestnut horse at a wooden farm fence, golden-hour light, wheat fields behind, quiet nostalgic mood. "
               + _PALETTE + ". " + _PEOPLE + " No text."),
    "farm-2": ("1024x1536",
               "Vintage film photograph, soft light leaks and grain: a model in a white cotton T-shirt and brown trousers "
               "leading a cream-colored horse down a dusty farm path past an old red-brown barn, late afternoon sun. "
               + _PALETTE + ". " + _PEOPLE + " No text."),
    "farm-3": ("1024x1536",
               "Vintage aesthetic portrait: a model in a sage-green linen shirt resting a hand on a dark bay horse's neck "
               "in a sunlit paddock, hay bales and a weathered wooden gate behind, hazy warm film look. "
               + _PALETTE + ". " + _PEOPLE + " No text."),
    "shirts-banner": ("1536x1024",
                      "Wide editorial still life: folded linen shirts in sand, ivory and sage stacked on a rustic wooden table "
                      "beside a straw hat and dried wheat, soft window light, " + _PALETTE + ", empty space on the right."),
    "tees-banner": ("1536x1024",
                    "Wide lifestyle photograph: white and beige cotton T-shirts hanging on a wooden rail in a sunlit minimal "
                    "studio with plants, " + _PALETTE + ", calm and airy, empty space on the left."),
    "studio-banner": ("1536x1024",
                      "Wide flat-lay of a creator's desk: a plain white T-shirt, sketchbook with a bold illustration, colored "
                      "pencils and fabric swatches on a warm beige linen surface, soft daylight, " + _PALETTE + "."),
}


@router.get("/api/admin/brand/status")
def brand_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    have = {k for (k,) in db.query(BrandAsset.key).all()}
    return {"assets": [{"key": k, "created": k in have} for k in BRAND_ASSETS]}


@router.post("/api/admin/brand/generate/{key}")
def generate_brand_asset(
    key: str, force: bool = Form(default=False),
    db: Session = Depends(get_db), _admin: User = Depends(require_admin),
):
    if key not in BRAND_ASSETS:
        raise HTTPException(status_code=404, detail="Unknown brand asset")
    existing = db.query(BrandAsset).filter(BrandAsset.key == key).first()
    if existing and not force:
        return {"status": "exists", "key": key}
    size, prompt = BRAND_ASSETS[key]
    try:
        with step(db, "design", "brand_stylist", f"Generating brand image '{key}'") as st:
            data = generate_image(prompt, size=size)
            st.done = f"Brand image '{key}' generated."
    except Exception as e:
        log.exception("Brand asset generation failed: %s", key)
        raise HTTPException(status_code=502, detail=f"Image generation failed: {type(e).__name__}: {e}")
    if existing:
        existing.image_data = data
    else:
        db.add(BrandAsset(key=key, image_data=data))
    db.commit()
    return {"status": "created", "key": key}
