"""
Mockup templates (one-time setup) + per-design mockup rendering.

Flow:
  1. Admin clicks "Generate mockup templates" ONCE (generate_templates
     below). This calls the image model for every (garment, color, slot)
     combo in app/garments.py's matrix - blank product photos, nothing
     printed on them - and saves them into the mockup_templates table
     (see db.py). This never needs to run again unless an admin wants
     fresh template photos (it's a safe upsert, re-running just overwrites
     each combo's row).
  2. For any design, GET /api/admin/design/{id}/mockup/{slot} composites
     that design's image onto ITS assigned (garment, color) template with
     Pillow - no AI call, pure image math (app/compositing.py) - and
     returns a PNG. Which garment/color a design is assigned is decided
     once, at generation time (see design_routes._generate_one_design),
     so the same design always renders the same way.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..db import get_db, Design, MockupTemplate, User
from ..auth import require_admin
from ..image_client import generate_image
from ..compositing import composite_mockup
from ..garments import GARMENTS, COLORS, DEFAULT_GARMENT, DEFAULT_COLOR

log = logging.getLogger(__name__)
router = APIRouter()

SLOTS = ("front", "back", "model")

_SLOT_FRAMING = {
    "front": (
        "flat lay, laid perfectly flat and centered on a light neutral gray "
        "background, sleeves tucked in symmetrically, shot from directly above, "
        "soft even studio lighting"
    ),
    "back": (
        "the BACK of the garment, flat lay, laid perfectly flat and centered on "
        "a light neutral gray background, sleeves tucked in symmetrically, shot "
        "from directly above, soft even studio lighting"
    ),
    "model": (
        "worn by a young adult model with a friendly, natural expression, "
        "standing confidently, three-quarter body shot from the chest to the "
        "waist, facing the camera directly, soft even studio lighting, light "
        "neutral gray background, authentic catalog-style pose. The model is an "
        "invented, generic person - not a real, named, or identifiable individual"
    ),
}

TEMPLATE_SIZE = "1024x1024"  # same size already proven working for design generation


def _template_prompt(garment: str, color: str, slot: str) -> str:
    garment_desc = GARMENTS[garment]["photo_desc"]
    color_desc = COLORS[color]["photo_desc"]
    framing = _SLOT_FRAMING[slot]
    return (
        f"Professional e-commerce product photography: a completely blank, plain "
        f"{color_desc} {garment_desc}, with no text, no logo, no printed graphic "
        f"on it anywhere, {framing}, no wrinkles beyond the natural fabric, high "
        f"resolution commercial catalog photo."
    )


@router.post("/api/admin/mockup-templates/generate")
def generate_templates(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """
    Walks the full garment x color x slot matrix. Each combo is generated
    and committed on its own (not batched into one transaction) so a
    failure partway through a ~2-5 minute run doesn't lose the combos that
    already succeeded.
    """
    results = {}
    for garment in GARMENTS:
        for color in COLORS:
            for slot in SLOTS:
                key = f"{garment}:{color}:{slot}"
                try:
                    image_bytes = generate_image(_template_prompt(garment, color, slot), size=TEMPLATE_SIZE)
                except Exception as e:
                    log.exception("Mockup template generation failed for %s", key)
                    results[key] = {"status": "error", "detail": f"{type(e).__name__}: {e}"}
                    continue

                existing = (
                    db.query(MockupTemplate)
                    .filter(MockupTemplate.garment == garment, MockupTemplate.color == color, MockupTemplate.slot == slot)
                    .first()
                )
                if existing:
                    existing.image_data = image_bytes
                else:
                    db.add(MockupTemplate(garment=garment, color=color, slot=slot, image_data=image_bytes))
                db.commit()
                results[key] = {"status": "ok"}

    succeeded = sum(1 for v in results.values() if v["status"] == "ok")
    return {"results": results, "succeeded": succeeded, "total": len(results)}


@router.get("/api/admin/mockup-templates")
def list_templates(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """
    Matrix status: for every (garment, color, slot) combo, whether it's
    been generated. The admin UI uses this both to show progress and to
    decide whether at least the default combo (tshirt/white) is ready
    enough to preview designs that predate this feature.
    """
    rows = db.query(MockupTemplate).all()
    by_combo = {(t.garment, t.color, t.slot): t.id for t in rows}

    matrix = {}
    for garment in GARMENTS:
        for color in COLORS:
            for slot in SLOTS:
                generated = (garment, color, slot) in by_combo
                matrix[f"{garment}:{color}:{slot}"] = {
                    "garment": garment,
                    "color": color,
                    "slot": slot,
                    "generated": generated,
                    "image_url": f"/api/admin/mockup-templates/{garment}/{color}/{slot}/image" if generated else None,
                }

    generated_count = sum(1 for v in matrix.values() if v["generated"])
    default_ready = all(
        matrix[f"{DEFAULT_GARMENT}:{DEFAULT_COLOR}:{slot}"]["generated"] for slot in SLOTS
    )
    return {
        "matrix": matrix,
        "generated_count": generated_count,
        "total_count": len(matrix),
        "default_ready": default_ready,
    }


@router.get("/api/admin/mockup-templates/{garment}/{color}/{slot}/image")
def get_template_image(
    garment: str, color: str, slot: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    template = (
        db.query(MockupTemplate)
        .filter(MockupTemplate.garment == garment, MockupTemplate.color == color, MockupTemplate.slot == slot)
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not generated yet")
    return Response(content=template.image_data, media_type="image/png")


def resolve_design_template(design: Design, slot: str, db: Session) -> MockupTemplate | None:
    garment = design.garment or DEFAULT_GARMENT
    color = design.color or DEFAULT_COLOR
    template = (
        db.query(MockupTemplate)
        .filter(MockupTemplate.garment == garment, MockupTemplate.color == color, MockupTemplate.slot == slot)
        .first()
    )
    if template:
        return template
    # Fall back to the default combo if this design's specific combo
    # hasn't been (re)generated yet - better to show it on a default white
    # tee than to break the page entirely.
    if (garment, color) != (DEFAULT_GARMENT, DEFAULT_COLOR):
        return (
            db.query(MockupTemplate)
            .filter(MockupTemplate.garment == DEFAULT_GARMENT, MockupTemplate.color == DEFAULT_COLOR, MockupTemplate.slot == slot)
            .first()
        )
    return None


@router.get("/api/admin/design/{design_id}/mockup/{slot}")
def get_design_mockup(
    design_id: int, slot: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    if slot not in SLOTS:
        raise HTTPException(status_code=404, detail="Unknown mockup slot")

    design = db.query(Design).filter(Design.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    template = resolve_design_template(design, slot, db)
    if not template:
        raise HTTPException(
            status_code=409,
            detail="Mockup templates haven't been generated yet - use 'Generate mockup templates' first",
        )

    mockup_bytes = composite_mockup(template.image_data, design.image_data, slot, garment=design.garment or DEFAULT_GARMENT)
    return Response(content=mockup_bytes, media_type="image/png")
