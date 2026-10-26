"""
Public storefront API - no login required. Only ever reads APPROVED
designs; pending/rejected designs never reach these endpoints, even if
someone guesses an id, because every query here filters on
Design.status == "approved".

This is deliberately separate from design_routes.py (the admin review
API) so the admin-only endpoints stay behind require_admin with zero risk
of a copy-paste accidentally exposing an unreviewed design publicly.
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db, Design, SearchLog, ProductPhoto, BrandAsset
from ..compositing import composite_mockup
from ..garments import DEFAULT_GARMENT
from ..catalog import product_dict
from ..similar import find_similar
from .mockup_routes import resolve_design_template

log = logging.getLogger(__name__)
router = APIRouter()

MOCKUP_SLOTS = ("front", "back", "model")

# Mockups don't change once a design is approved, so the browser (and any
# CDN in front of this later) can hold onto them instead of re-fetching.
# Short on purpose: when an AI product photo replaces the composite fallback
# the URL stays the same, so a long cache would keep showing the stale one.
MOCKUP_CACHE_HEADERS = {"Cache-Control": "public, max-age=300"}


@router.get("/api/public/products")
def list_products(db: Session = Depends(get_db)):
    designs = (
        db.query(Design)
        .filter(Design.status == "approved")
        .order_by(Design.created_at.desc())
        .all()
    )
    return [product_dict(d) for d in designs]


@router.get("/api/public/products/{design_id}")
def get_product(design_id: int, db: Session = Depends(get_db)):
    """Single approved design, for the dedicated /shop/design/{id} page."""
    d = db.query(Design).filter(Design.id == design_id, Design.status == "approved").first()
    if not d:
        raise HTTPException(status_code=404, detail="Design not found")
    return product_dict(d, include_caption=True)


@router.get("/api/public/brand")
def list_brand_assets(db: Session = Depends(get_db)):
    """Which storefront images have been generated (the shop falls back to
    plain beige panels for the rest)."""
    return {"keys": [k for (k,) in db.query(BrandAsset.key).all()]}


@router.get("/api/public/brand/{key}")
def brand_asset(key: str, db: Session = Depends(get_db)):
    asset = db.query(BrandAsset).filter(BrandAsset.key == key).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Not generated yet")
    return Response(content=asset.image_data, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/api/public/design/{design_id}/mockup/{slot}")
def public_design_mockup(design_id: int, slot: str, db: Session = Depends(get_db)):
    if slot not in MOCKUP_SLOTS:
        raise HTTPException(status_code=404, detail="Unknown mockup slot")

    design = (
        db.query(Design)
        .filter(Design.id == design_id, Design.status == "approved")
        .first()
    )
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    photo = db.query(ProductPhoto).filter(ProductPhoto.design_id == design_id, ProductPhoto.slot == slot).first()
    if photo:
        return Response(content=photo.image_data, media_type="image/png", headers=MOCKUP_CACHE_HEADERS)
    if (design.kind or "print") == "plain":
        raise HTTPException(status_code=404, detail="Photo not available")

    template = resolve_design_template(design, slot, db)
    if not template:
        raise HTTPException(status_code=409, detail="Mockup templates not generated yet")

    mockup_bytes = composite_mockup(template.image_data, design.image_data, slot, garment=design.garment or DEFAULT_GARMENT)
    return Response(content=mockup_bytes, media_type="image/png", headers=MOCKUP_CACHE_HEADERS)


@router.post("/api/public/visual-search")
async def visual_search(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    "Find similar designs" - extracts the uploaded photo's pattern/subject
    tags (Azure Vision) and dominant color (Pillow), then compares those
    against the same signals stored on every approved design (see
    app/visual_search.py for how matching is scored and why). Also drops
    one SearchLog row for the top match, which is all the admin
    "Customer interest" panel (design_routes.search_trends) reads from -
    no uploaded photos are ever stored.
    """
    image_bytes = await file.read()
    try:
        top_matches, _tags = find_similar(db, image_bytes, limit=6)
    except ValueError:
        raise HTTPException(status_code=400, detail="Couldn't read that as an image - try a JPG or PNG.")

    if top_matches:
        best_score, best_design = top_matches[0]
        db.add(SearchLog(matched_design_id=best_design.id, score=round(best_score * 100)))
        db.commit()

    return [{**product_dict(d), "similarity": round(score * 100)} for score, d in top_matches]
