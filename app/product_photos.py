"""
AI product photography: turns an approved design into real-looking product
photos (flat lay + worn by a model) using the image model's EDIT endpoint,
with the design as the reference image.

Why this replaces "paste the design onto a template with Pillow" as the
primary path: compositing can't make a print look printed on a hoodie, can't
keep a dark print legible on black fabric, and can't frame a worn shot
around the right body area - the model can, if it's directed well. So each
photo gets an art-directed prompt built from what we actually know about the
design (its Vision tags, dominant color, the garment's print placement, the
contrast between art and fabric) - the "high level intelligence" is the
art-direction step plus a critic loop:

    1. build prompt  ->  2. edit_image(design, prompt)  ->  3. ask Azure
       Vision what's in the result (garment? color?)  ->  4. if it doesn't
       match the order, regenerate ONCE with a correction naming exactly what
       was wrong  ->  5. store the best result + the Vision caption.

Everything here is best-effort and falls back to the Pillow composite
(public_routes) - a failed photo never breaks a product page.
"""
import logging

from sqlalchemy.orm import Session

from .db import Design, ProductPhoto
from .garments import GARMENTS, COLORS, luminance
from .image_client import edit_image, generate_image
from .agent_log import log_activity, step, new_run_id

log = logging.getLogger(__name__)

PHOTO_SLOTS = ("front", "model")

_SETTINGS = [
    "a bright, clean light-gray studio with soft diffused window light",
    "a sunlit city street with a softly blurred background",
    "a warm golden-hour outdoor field with soft backlight",
    "a minimal warm-beige studio wall with gentle shadows",
]
_MODELS = [
    "a young woman with a relaxed, natural smile",
    "a young man with short dark hair and a friendly expression",
    "a young woman with long wavy hair looking just off-camera",
    "a young man with a light beard, relaxed and confident",
]


def _contrast_note(design: Design, color: str) -> str:
    try:
        art_lum = luminance(tuple(int(p) for p in (design.dominant_color or "").split(",")))
    except ValueError:
        return ""
    fabric_lum = luminance(COLORS[color]["rgb"])
    if abs(art_lum - fabric_lum) < 70:
        if fabric_lum < 100:
            return (
                " The artwork is dark and the fabric is dark, so print it like a real screen print with a thin "
                "light under-base and slightly brightened, vivid inks - it must stay clearly legible, never "
                "sink into the fabric."
            )
        return (
            " The artwork is light and the fabric is light, so give the print a subtle darker edge and rich "
            "inks - it must stay clearly legible against the fabric."
        )
    return ""


def build_photo_prompt(design: Design, garment: str, color: str, slot: str, correction: str = "") -> str:
    g, c = GARMENTS[garment], COLORS[color]
    tags = ", ".join([t for t in (design.vision_tags or "").split(",") if t][:6])
    seed = design.id or 0
    fabric = f"{c['photo_desc']} {g['photo_desc']}"

    base = (
        f"Professional e-commerce product photograph of {fabric}. The attached image is the exact print: "
        f"reproduce it faithfully (same shapes, colors and details - do not redraw, restyle, crop or add any text, "
        f"logos or watermarks) and place it {g['placement']}. It must look genuinely printed on the fabric: "
        f"follows the cloth's folds and weave, lit by the same light as the garment."
    )
    if tags:
        base += f" (The artwork depicts: {tags}.)"
    base += _contrast_note(design, color)

    if slot == "front":
        if g["category"] == "bottom":
            framing = " Flat lay shot from directly above on a light neutral surface, garment centered and fully visible."
        else:
            framing = " Flat lay shot from directly above on a light neutral surface, garment centered and fully visible, sleeves laid naturally."
    else:
        if g["category"] == "bottom":
            body = "waist to just below the knee"
        else:
            body = "head to mid-thigh" if garment == "hoodie" else "head to waist"
        framing = (
            f" Worn by {_MODELS[seed % len(_MODELS)]} - an invented, generic person, not a real or identifiable "
            f"individual - standing naturally, three-quarter body shot from {body}, in {_SETTINGS[(seed // 2) % len(_SETTINGS)]}. "
            f"The print is large enough to read clearly at thumbnail size and fully visible (not hidden by hair, "
            f"hands, straps or the hood)."
        )
    out = base + framing + " Photorealistic, high resolution, true-to-life color."
    if correction:
        out += f" IMPORTANT CORRECTION from the last attempt: {correction}"
    return out


def _verify(image_bytes: bytes, garment: str, color: str) -> tuple[int | None, str, str]:
    """Ask Azure Vision what it sees. Returns (1|0|None, caption, problem)."""
    try:
        from .vision_client import analyze_tags_and_caption
        tags, caption = analyze_tags_and_caption(image_bytes)
    except Exception:
        log.exception("Photo verification (Vision) unavailable")
        return None, "", ""

    text = (" ".join(tags) + " " + (caption or "")).lower()
    g = GARMENTS[garment]
    problems = []

    if any(k in text for k in g["avoid_keywords"]) and not any(k in text for k in g["keywords"] if k not in ("shirt",)):
        problems.append(f"the garment must be {g['photo_desc']}, not a different garment type")
    elif not any(k in text for k in g["keywords"]):
        problems.append(f"the garment must clearly be {g['photo_desc']}")

    all_color_words = {w for info in COLORS.values() for w in info["words"]}
    target_words = set(COLORS[color]["words"])
    if (caption or "") and any(w in (caption or "").lower() for w in all_color_words) \
            and not any(w in (caption or "").lower() for w in target_words):
        problems.append(f"the garment color must be {COLORS[color]['photo_desc']}")

    return (0 if problems else 1), caption or "", "; ".join(problems)


def _store(db: Session, design_id: int, slot: str, data: bytes, verified: int | None, caption: str):
    existing = db.query(ProductPhoto).filter(ProductPhoto.design_id == design_id, ProductPhoto.slot == slot).first()
    if existing:
        existing.image_data, existing.verified, existing.caption, existing.source = data, verified, caption, "ai"
    else:
        db.add(ProductPhoto(design_id=design_id, slot=slot, image_data=data, verified=verified, caption=caption))
    db.commit()


def generate_product_photo(db: Session, design: Design, slot: str, run_id: str | None = None) -> dict:
    """One slot, with the critic loop. Raises only if the image model itself
    fails twice; callers treat that as 'keep using the Pillow fallback'."""
    garment = design.garment or "tshirt"
    color = design.color or "white"
    if garment not in GARMENTS or color not in COLORS:
        raise ValueError(f"Unknown garment/color {garment}/{color}")

    with step(db, "design", "photo_director", f"Writing the {slot} photo brief for design #{design.id}", run_id=run_id, design_id=design.id) as st:
        prompt = build_photo_prompt(design, garment, color, slot)
        st.done = f"Brief ready: {GARMENTS[garment]['label']} / {COLORS[color]['label']}, print {GARMENTS[garment]['placement'][:48]}..."
    with step(db, "design", "photographer", f"Photographing design #{design.id} ({slot})", run_id=run_id, design_id=design.id) as st:
        img = edit_image(prompt, design.image_data)
        st.done = f"{slot} photo shot."
    with step(db, "design", "photo_critic", f"Checking the {slot} photo with Vision", run_id=run_id, design_id=design.id) as st:
        verified, caption, problem = _verify(img, garment, color)
        st.done = ("Verified: right garment and colour." if verified == 1
                   else "Could not verify (Vision unavailable)." if verified is None
                   else f"Mismatch - {problem}")

    retried = False
    if verified == 0:
        retried = True
        log.info("Photo for design %s/%s failed critic (%s) - regenerating once", design.id, slot, problem)
        with step(db, "design", "photographer", f"Re-shooting {slot} with the critic's correction", run_id=run_id, design_id=design.id) as st:
            prompt2 = build_photo_prompt(design, garment, color, slot, correction=problem)
            img2 = edit_image(prompt2, design.image_data)
            st.done = "Corrected photo shot."
        with step(db, "design", "photo_critic", f"Re-checking the {slot} photo", run_id=run_id, design_id=design.id) as st:
            v2, cap2, _ = _verify(img2, garment, color)
            st.done = "Now verified." if v2 == 1 else "Still unverified - keeping the better attempt."
        if v2 != 0:  # better or unverifiable - keep the retry
            img, verified, caption = img2, v2, cap2

    _store(db, design.id, slot, img, verified, caption)
    log_activity(db, "design", "ok", f"Design #{design.id} {slot} photo is live on the storefront.",
                 design_id=design.id, node="storefront", run_id=run_id)
    return {"slot": slot, "verified": verified, "caption": caption, "retried": retried}


def generate_photos_for_design(db: Session, design_id: int, slots=PHOTO_SLOTS) -> list[dict]:
    design = db.query(Design).filter(Design.id == design_id).first()
    if not design:
        return []
    results = []
    run_id = new_run_id("photo")
    for slot in slots:
        try:
            res = generate_product_photo(db, design, slot, run_id=run_id)
            results.append(res)
            log_activity(
                db, "design", "ok" if res["verified"] != 0 else "alert",
                f"AI product photo ({slot}) for design #{design_id}: "
                f"{'verified by Vision' if res['verified'] == 1 else 'could not be fully verified' if res['verified'] is None else 'garment/color mismatch kept after one retry'}"
                f"{' (regenerated once after a critic correction)' if res['retried'] else ''}.",
                design_id=design_id,
            )
        except Exception as e:
            log.exception("AI product photo failed for design %s/%s", design_id, slot)
            log_activity(db, "design", "error", f"AI product photo ({slot}) failed for design #{design_id}: {type(e).__name__}: {e}", design_id=design_id)
            results.append({"slot": slot, "error": f"{type(e).__name__}: {e}"})
    return results


def background_generate(design_id: int):
    """FastAPI BackgroundTasks entry point (own DB session - the request's is closed)."""
    from .db import SessionLocal
    db = SessionLocal()
    try:
        generate_photos_for_design(db, design_id)
    finally:
        db.close()


# ---------- Plain products (the linen collection) & brand imagery ----------

def generate_plain_product_photo(prompt: str, size: str = "1024x1024") -> bytes:
    return generate_image(prompt, size=size)
