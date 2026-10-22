"""
Design agent: trend research (Tavily web search) -> image generation
(Foundry gpt-image-1.5) -> saved as a pending Design row for admin review.

Pipeline, each run:
  1. Tavily search for current T-shirt design trends, with include_answer
     set to "advanced" so Tavily itself returns a synthesized written
     summary of the search results - this IS the trend brief, no separate
     text-generation call needed.
  2. That summary becomes the image prompt (plus fixed style instructions
     so the output is usable as an actual T-shirt graphic, not a mockup
     photo or a scene).
  3. gpt-image-1.5 generates the image; we save its bytes INTO a Design
     row (not as a file on disk - see db.py's Design.image_data for why)
     with status "pending".

No live web search tool is attached to the image/chat models here - Tavily
is called directly over HTTP, so this pipeline has no dependency on any
Foundry agent beyond the image deployment itself.
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, Design, SearchLog, User
from ..auth import require_admin
from ..image_client import generate_image
from ..visual_search import extract_signals, tags_to_text, color_to_text

log = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_TREND_QUERY = (
    "trending T-shirt graphic design patterns, colors and styles right now"
)

IMAGE_STYLE_SUFFIX = (
    " Render as a single standalone graphic design suitable for screen-printing "
    "on a T-shirt: centered composition, no mockup, no visible T-shirt or model, "
    "no readable text or logos, clean vector-illustration style, transparent-friendly "
    "flat background."
)


def _research_trend(query: str) -> tuple[str, list[str]]:
    """Calls Tavily directly; returns (written summary, source URLs)."""
    resp = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {settings.TAVILY_API_KEY}"},
        json={
            "query": query,
            "search_depth": "advanced",
            "max_results": 5,
            "topic": "general",
            "include_answer": "advanced",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    summary = data.get("answer") or ""
    if not summary:
        # Fall back to stitching result snippets together if Tavily didn't
        # return a synthesized answer for some reason.
        summary = " ".join(r.get("content", "") for r in data.get("results", [])[:3])
    sources = [r["url"] for r in data.get("results", []) if r.get("url")]
    return summary, sources


@router.post("/api/admin/design/generate")
def generate_design(
    focus: str = Form(default=""),  # optional: admin can narrow the trend search
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = focus.strip() or DEFAULT_TREND_QUERY

    try:
        summary, sources = _research_trend(query)
    except Exception as e:
        log.exception("Tavily trend research failed")
        return {"status": "error", "stage": "trend_research", "detail": f"{type(e).__name__}: {e}"}

    image_prompt = f"{summary}{IMAGE_STYLE_SUFFIX}"

    try:
        image_bytes = generate_image(image_prompt, size="1024x1024")
    except Exception as e:
        log.exception("Image generation failed")
        return {"status": "error", "stage": "image_generation", "detail": f"{type(e).__name__}: {e}"}

    # Tagging/color extraction feeds visual search (see app/visual_search.py)
    # but isn't core to "did we get a design" - a Vision hiccup here
    # shouldn't fail the whole generation. Falls back to untagged; a design
    # with no tags yet gets backfilled lazily on first search.
    vision_tags_text, dominant_color_text = None, None
    try:
        tags, color = extract_signals(image_bytes)
        vision_tags_text, dominant_color_text = tags_to_text(tags), color_to_text(color)
    except Exception:
        log.exception("Vision tagging failed for new design (non-fatal, will backfill on search)")

    design = Design(
        trend_query=query,
        trend_summary=summary,
        sources="\n".join(sources),
        image_prompt=image_prompt,
        image_data=image_bytes,
        vision_tags=vision_tags_text,
        dominant_color=dominant_color_text,
        status="pending",
    )
    db.add(design)
    db.commit()
    db.refresh(design)

    return {
        "status": "ok",
        "id": design.id,
        "image_url": f"/api/admin/design/{design.id}/image",
        "trend_summary": summary,
        "sources": sources,
    }


@router.get("/api/admin/design/list")
def list_designs(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    designs = db.query(Design).order_by(Design.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "trend_query": d.trend_query,
            "trend_summary": d.trend_summary,
            "sources": d.sources.split("\n") if d.sources else [],
            "image_url": f"/api/admin/design/{d.id}/image",
            "status": d.status,
            "created_at": d.created_at.isoformat(),
        }
        for d in designs
    ]


@router.get("/api/admin/design/{design_id}/image")
def get_design_image(
    design_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    design = db.query(Design).filter(Design.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")
    return Response(content=design.image_data, media_type="image/png")


def _set_status(design_id: int, status: str, db: Session, _admin: User):
    design = db.query(Design).filter(Design.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")
    design.status = status
    db.commit()
    return {"status": "ok", "id": design.id, "new_status": status}


@router.post("/api/admin/design/{design_id}/approve")
def approve_design(
    design_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    return _set_status(design_id, "approved", db, _admin)


@router.post("/api/admin/design/{design_id}/reject")
def reject_design(
    design_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    return _set_status(design_id, "rejected", db, _admin)


TREND_WINDOW_DAYS = 7
TREND_MIN_SEARCHES = 2  # how many "find similar" hits in the window count as a trend


@router.get("/api/admin/search-trends")
def search_trends(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """
    The "notify the admin" half of visual search: every public
    /api/public/visual-search call logs which approved design it matched
    best. This groups those hits over the last TREND_WINDOW_DAYS and
    surfaces any design that came up at least TREND_MIN_SEARCHES times -
    i.e. "customers keep uploading photos that look like this one."

    This is a dashboard feed the admin checks, not a push notification
    (no email/SMS is wired up to this project) - see the panel on the
    admin dashboard.
    """
    window_start = datetime.now(timezone.utc) - timedelta(days=TREND_WINDOW_DAYS)
    logs = (
        db.query(SearchLog)
        .filter(SearchLog.created_at >= window_start, SearchLog.matched_design_id.isnot(None))
        .all()
    )

    counts: dict[int, int] = {}
    for entry in logs:
        counts[entry.matched_design_id] = counts.get(entry.matched_design_id, 0) + 1

    trending = []
    for design_id, count in counts.items():
        if count < TREND_MIN_SEARCHES:
            continue
        design = db.query(Design).filter(Design.id == design_id).first()
        if not design:
            continue
        trending.append({
            "design_id": design_id,
            "search_count": count,
            "trend_summary": design.trend_summary,
            "image_url": f"/api/admin/design/{design_id}/image",
            "status": design.status,
        })

    trending.sort(key=lambda t: t["search_count"], reverse=True)
    return trending
