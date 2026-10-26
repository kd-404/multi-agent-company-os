"""
"Print your own": shoppers upload artwork (or describe it for the AI to
draw), pick a garment and colour, preview it, and order it.

Guard rails, because this accepts user input and spends image-model budget:
  * sign-in required; designs are private to their owner;
  * uploads are decoded and re-encoded with Pillow (rejects non-images,
    strips metadata, caps size/dimensions);
  * AI generation is rate-limited per user per day and prompts pass a small
    deny-list (real people / brands / explicit / hateful) before any call;
  * the preview is a Pillow composite onto the stored blank-garment
    template (free); a photographic "worn" preview is an explicit extra
    click (one image-edit call) and is cached on the row.
"""
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from ..db import get_db, CustomDesign, MockupTemplate, User
from ..auth import get_current_user
from ..catalog import CUSTOM_PRINT_PRICE_INR
from ..compositing import composite_mockup
from ..garments import GARMENTS, COLORS, DEFAULT_GARMENT, DEFAULT_COLOR
from ..image_client import generate_image, edit_image
from ..agent_log import log_activity

log = logging.getLogger(__name__)
router = APIRouter()

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_SIDE = 1536
AI_LIMIT_PER_DAY = 5
PHOTO_LIMIT_PER_DAY = 6

DENY_LIST = (
    "nude", "naked", "porn", "sexual", "explicit", "gore", "swastika", "nazi", "hitler", "isis", "kkk",
    "racist", "slur", "child abuse", "suicide", "self-harm", "terror",
    "disney", "marvel", "nike logo", "adidas logo", "pokemon", "mickey mouse", "spiderman", "batman",
    "trump", "biden", "modi", "taylor swift", "elon musk",
)


def printable_garments() -> list[dict]:
    return [{"key": k, "label": g["label"], "colors": [{"key": c, "label": COLORS[c]["label"] if "label" in COLORS[c] else c.replace("-", " ").title()} for c in g["colors"]]}
            for k, g in GARMENTS.items() if g["printable"] and g["category"] == "top"]


@router.get("/api/studio/options")
def studio_options():
    return {"garments": printable_garments(), "price_inr": CUSTOM_PRINT_PRICE_INR, "ai_limit_per_day": AI_LIMIT_PER_DAY}


def _normalize_image(raw: bytes) -> bytes:
    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception:
        raise HTTPException(status_code=400, detail="That file isn't a readable image (use PNG, JPG or WebP)")
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _check_choice(garment: str, color: str):
    if garment not in GARMENTS or not GARMENTS[garment]["printable"] or GARMENTS[garment]["category"] != "top":
        raise HTTPException(status_code=400, detail="Pick a T-shirt, full-sleeve or hoodie")
    if color not in GARMENTS[garment]["colors"]:
        raise HTTPException(status_code=400, detail=f"{GARMENTS[garment]['label']} isn't available in that colour")


def _template(garment: str, color: str, slot: str, db: Session) -> MockupTemplate | None:
    for g, c in ((garment, color), (DEFAULT_GARMENT, DEFAULT_COLOR)):
        t = db.query(MockupTemplate).filter(MockupTemplate.garment == g, MockupTemplate.color == c, MockupTemplate.slot == slot).first()
        if t:
            return t
    return None


def _owned(cid: int, db: Session, user: User) -> CustomDesign:
    cd = db.query(CustomDesign).filter(CustomDesign.id == cid).first()
    if not cd or cd.user_id != user.id:
        raise HTTPException(status_code=404, detail="Design not found")  # 404, not 403: don't reveal others' ids
    return cd


def _row(cd: CustomDesign) -> dict:
    return {
        "id": cd.id, "garment": cd.garment, "color": cd.color, "source": cd.source, "prompt": cd.prompt,
        "garment_label": GARMENTS[cd.garment]["label"] if cd.garment in GARMENTS else cd.garment,
        "color_label": cd.color.replace("-", " ").title(),
        "price_inr": CUSTOM_PRINT_PRICE_INR, "has_photo": cd.preview_data is not None,
        "preview_url": f"/api/studio/design/{cd.id}/preview", "art_url": f"/api/studio/design/{cd.id}/art",
        "photo_url": f"/api/studio/design/{cd.id}/photo" if cd.preview_data else None,
        "created_at": cd.created_at.isoformat(),
    }


@router.post("/api/studio/upload")
async def studio_upload(
    garment: str = Form(...), color: str = Form(...), file: UploadFile = File(...),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    _check_choice(garment, color)
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Image is too large (max 8 MB)")
    cd = CustomDesign(user_id=user.id, garment=garment, color=color, source="upload", image_data=_normalize_image(raw))
    db.add(cd)
    db.commit()
    db.refresh(cd)
    return _row(cd)


@router.post("/api/studio/generate")
def studio_generate(
    garment: str = Form(...), color: str = Form(...), prompt: str = Form(...),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    _check_choice(garment, color)
    prompt = prompt.strip()
    if len(prompt) < 4 or len(prompt) > 300:
        raise HTTPException(status_code=400, detail="Describe your design in 4-300 characters")
    low = prompt.lower()
    if any(term in low for term in DENY_LIST):
        raise HTTPException(status_code=400, detail="I can't make that one - try an original idea that doesn't involve real people, brands or explicit content")

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    used = db.query(CustomDesign).filter(CustomDesign.user_id == user.id, CustomDesign.source == "ai", CustomDesign.created_at >= since).count()
    if used >= AI_LIMIT_PER_DAY:
        raise HTTPException(status_code=429, detail=f"Daily limit of {AI_LIMIT_PER_DAY} AI designs reached - upload your own art or try again tomorrow")

    art_prompt = (
        f"A standalone print-ready graphic for a T-shirt: {prompt}. Centered illustration on a plain, solid, flat "
        f"background with generous empty margin, bold clean shapes, limited rich colour palette, no mockup, no garment, "
        f"no text unless the description asks for it, no watermark, original artwork."
    )
    try:
        data = generate_image(art_prompt, size="1024x1024")
    except Exception as e:
        log.exception("Studio AI generation failed")
        raise HTTPException(status_code=502, detail="The image generator is busy - please try again in a moment")
    cd = CustomDesign(user_id=user.id, garment=garment, color=color, source="ai", prompt=prompt, image_data=data)
    db.add(cd)
    db.commit()
    db.refresh(cd)
    log_activity(db, "design", "ok", f"Print-your-own: AI artwork generated for a customer (custom #{cd.id}).")
    return _row(cd)


@router.post("/api/studio/design/{cid}/restyle")
def studio_restyle(
    cid: int, garment: str = Form(...), color: str = Form(...),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    cd = _owned(cid, db, user)
    _check_choice(garment, color)
    cd.garment, cd.color, cd.preview_data = garment, color, None
    db.commit()
    return _row(cd)


@router.get("/api/studio/mine")
def studio_mine(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(CustomDesign).filter(CustomDesign.user_id == user.id).order_by(CustomDesign.id.desc()).limit(24).all()
    return [_row(cd) for cd in rows]


@router.get("/api/studio/design/{cid}/art")
def studio_art(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cd = _owned(cid, db, user)
    return Response(content=cd.image_data, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.get("/api/studio/design/{cid}/preview")
def studio_preview(cid: int, slot: str = "front", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cd = _owned(cid, db, user)
    if slot not in ("front", "model"):
        slot = "front"
    t = _template(cd.garment, cd.color, slot, db)
    if not t:
        # No blank garment photos yet: show the artwork itself rather than an error
        return Response(content=cd.image_data, media_type="image/png")
    png = composite_mockup(t.image_data, cd.image_data, slot, garment=cd.garment)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.get("/api/studio/design/{cid}/photo")
def studio_photo(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cd = _owned(cid, db, user)
    if not cd.preview_data:
        raise HTTPException(status_code=404, detail="No photo yet")
    return Response(content=cd.preview_data, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.post("/api/studio/design/{cid}/photo")
def studio_make_photo(cid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Optional extra: a photographic 'worn' preview via the image-edit model
    (the same art-directed prompt the catalog uses)."""
    cd = _owned(cid, db, user)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    made = db.query(CustomDesign).filter(CustomDesign.user_id == user.id, CustomDesign.preview_data.isnot(None), CustomDesign.created_at >= since).count()
    if cd.preview_data is None and made >= PHOTO_LIMIT_PER_DAY:
        raise HTTPException(status_code=429, detail="Daily photo-preview limit reached")
    from types import SimpleNamespace
    from ..product_photos import build_photo_prompt
    from ..visual_search import extract_signals, tags_to_text, color_to_text
    try:
        tags, rgb = extract_signals(cd.image_data)
        tags_text, color_text = tags_to_text(tags), color_to_text(rgb)
    except Exception:
        tags_text, color_text = "", None
    shim = SimpleNamespace(id=cd.id, vision_tags=tags_text, dominant_color=color_text)
    prompt = build_photo_prompt(shim, cd.garment, cd.color, "model")
    try:
        cd.preview_data = edit_image(prompt, cd.image_data)
    except Exception:
        log.exception("Studio photo preview failed")
        raise HTTPException(status_code=502, detail="Couldn't make the photo preview - the flat preview is still accurate")
    db.commit()
    return _row(cd)
