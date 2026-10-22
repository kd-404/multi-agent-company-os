"""
Mockup templates (one-time setup) + per-design mockup rendering.

Flow:
  1. Admin clicks "Generate mockup templates" ONCE (generate_templates below).
     This calls the image model 3 times - plain, blank T-shirt product
     photos: front, back, side - and saves them into the mockup_templates
     table (see db.py). This never needs to run again unless an admin wants
     fresh template photos.
  2. For any design, GET /api/admin/design/{id}/mockup/{slot} composites
     that design's image onto the matching template with Pillow - no AI
     call, pure image math (app/compositing.py) - and returns a PNG.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..db import get_db, Design, MockupTemplate, User
from ..auth import require_admin
from ..image_client import generate_image
from ..compositing import composite_mockup

log = logging.getLogger(__name__)
router = APIRouter()

TEMPLATE_PROMPTS: dict[str, str] = {
    "front": (
        "Professional e-commerce product photography: a completely blank plain "
        "white crewneck T-shirt, flat lay, laid perfectly flat and centered on a "
        "light neutral gray background, sleeves tucked in symmetrically, shot from "
        "directly above, soft even studio lighting, no wrinkles, no text, no logo, "
        "no printed graphic, no person, no mannequin, high resolution commercial "
        "catalog photo."
    ),
    "back": (
        "Professional e-commerce product photography: the BACK of a completely "
        "blank plain white crewneck T-shirt, flat lay, laid perfectly flat and "
        "centered on a light neutral gray background, sleeves tucked in "
        "symmetrically, shot from directly above, soft even studio lighting, no "
        "wrinkles, no text, no logo, no printed graphic, no person, no mannequin, "
        "high resolution commercial catalog photo."
    ),
    "side": (
        "Professional e-commerce product photography: a completely blank plain "
        "white crewneck T-shirt on a wooden hanger, photographed at a slight "
        "three-quarter angle to show depth and side profile, light neutral gray "
        "background, soft even studio lighting, no wrinkles, no text, no logo, no "
        "printed graphic, no person, high resolution commercial catalog photo."
    ),
}

TEMPLATE_SIZE = "1024x1024"  # same size already proven working for design generation


@router.post("/api/admin/mockup-templates/generate")
def generate_templates(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    results = {}
    for slot, prompt in TEMPLATE_PROMPTS.items():
        try:
            image_bytes = generate_image(prompt, size=TEMPLATE_SIZE)
        except Exception as e:
            log.exception("Mockup template generation failed for slot %s", slot)
            results[slot] = {"status": "error", "detail": f"{type(e).__name__}: {e}"}
            continue

        existing = db.query(MockupTemplate).filter(MockupTemplate.slot == slot).first()
        if existing:
            existing.image_data = image_bytes
        else:
            db.add(MockupTemplate(slot=slot, image_data=image_bytes))
        db.commit()
        results[slot] = {"status": "ok"}

    return results


@router.get("/api/admin/mockup-templates")
def list_templates(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    templates = db.query(MockupTemplate).all()
    by_slot = {t.slot: True for t in templates}
    return {
        slot: {
            "generated": by_slot.get(slot, False),
            "image_url": f"/api/admin/mockup-templates/{slot}/image" if by_slot.get(slot) else None,
        }
        for slot in TEMPLATE_PROMPTS
    }


@router.get("/api/admin/mockup-templates/{slot}/image")
def get_template_image(slot: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    template = db.query(MockupTemplate).filter(MockupTemplate.slot == slot).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not generated yet")
    return Response(content=template.image_data, media_type="image/png")


@router.get("/api/admin/design/{design_id}/mockup/{slot}")
def get_design_mockup(
    design_id: int, slot: str, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    if slot not in TEMPLATE_PROMPTS:
        raise HTTPException(status_code=404, detail="Unknown mockup slot")

    design = db.query(Design).filter(Design.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    template = db.query(MockupTemplate).filter(MockupTemplate.slot == slot).first()
    if not template:
        raise HTTPException(
            status_code=409,
            detail="Mockup templates haven't been generated yet - use 'Generate mockup templates' first",
        )

    mockup_bytes = composite_mockup(template.image_data, design.image_data, slot)
    return Response(content=mockup_bytes, media_type="image/png")
