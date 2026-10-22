"""
Public storefront API - no login required. Only ever reads APPROVED
designs; pending/rejected designs never reach these endpoints, even if
someone guesses an id, because every query here filters on
Design.status == "approved".

This is deliberately separate from design_routes.py (the admin review
API) so the admin-only endpoints stay behind require_admin with zero risk
of a copy-paste accidentally exposing an unreviewed design publicly.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db, Design, MockupTemplate, SearchLog
from ..compositing import composite_mockup
from ..visual_search import compute_hash, similarity

router = APIRouter()

MOCKUP_SLOTS = ("front", "back", "side")

# Mockups don't change once a design is approved, so the browser (and any
# CDN in front of this later) can hold onto them instead of re-fetching.
MOCKUP_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


@router.get("/api/public/products")
def list_products(db: Session = Depends(get_db)):
    designs = (
        db.query(Design)
        .filter(Design.status == "approved")
        .order_by(Design.created_at.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "trend_summary": d.trend_summary,
            "sources": d.sources.split("\n") if d.sources else [],
            "mockups": {slot: f"/api/public/design/{d.id}/mockup/{slot}" for slot in MOCKUP_SLOTS},
            "created_at": d.created_at.isoformat(),
        }
        for d in designs
    ]


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

    template = db.query(MockupTemplate).filter(MockupTemplate.slot == slot).first()
    if not template:
        raise HTTPException(status_code=409, detail="Mockup templates not generated yet")

    mockup_bytes = composite_mockup(template.image_data, design.image_data, slot)
    return Response(content=mockup_bytes, media_type="image/png", headers=MOCKUP_CACHE_HEADERS)


@router.post("/api/public/visual-search")
async def visual_search(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    "Find similar designs" - compares the uploaded photo's perceptual hash
    (see app/visual_search.py for why it's a hash and not an embedding
    model) against every approved design's hash, and returns the closest
    matches. Also drops one SearchLog row for the top match, which is all
    the admin "Customer interest" panel (design_routes.search_trends)
    reads from - no uploaded photos are ever stored.
    """
    image_bytes = await file.read()
    try:
        query_hash = compute_hash(image_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't read that as an image - try a JPG or PNG.")

    designs = db.query(Design).filter(Design.status == "approved").all()
    if not designs:
        return []

    scored = []
    for d in designs:
        if not d.image_hash:
            # Backfills designs approved before this feature existed.
            d.image_hash = compute_hash(d.image_data)
            db.add(d)
        scored.append((similarity(query_hash, d.image_hash), d))
    db.commit()

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top_matches = scored[:6]

    if top_matches:
        best_score, best_design = top_matches[0]
        db.add(SearchLog(matched_design_id=best_design.id, score=round(best_score * 100)))
        db.commit()

    return [
        {
            "id": d.id,
            "trend_summary": d.trend_summary,
            "sources": d.sources.split("\n") if d.sources else [],
            "mockups": {slot: f"/api/public/design/{d.id}/mockup/{slot}" for slot in MOCKUP_SLOTS},
            "similarity": round(score * 100),
        }
        for score, d in top_matches
    ]
