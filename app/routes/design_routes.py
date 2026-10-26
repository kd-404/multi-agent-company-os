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

from fastapi import APIRouter, Depends, Form, HTTPException, Response
from sqlalchemy.orm import Session

from ..db import get_db, Design, SearchLog, User
from ..auth import require_admin
from ..image_client import generate_image
from ..visual_search import extract_signals, tags_to_text, color_to_text
from ..trend_research import research_trend
from ..agent_log import log_activity
from ..garments import pick_garment_and_color, garment_label, color_label, GARMENTS, COLORS

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

# Deliberately varied style angles for batch generation, so a run of several
# designs doesn't converge on the same "generic trendy graphic" look every
# time Tavily happens to return similar search results. Each one still goes
# through the same live trend-research step - this just points the research
# at a different corner of the design world each time.
BATCH_STYLE_PRESETS = [
    "bold streetwear graffiti-style graphic with spray-paint texture",
    "minimalist single continuous line-art illustration",
    "Japanese ukiyo-e woodblock print inspired illustration",
    "retro 90s skate culture graphic with distressed texture",
    "geometric abstract pattern with bold color blocking",
    "detailed botanical nature illustration with fine linework",
    "psychedelic pattern with swirling trippy colors",
    "vintage collegiate varsity typography design",
]


def _generate_one_design(query: str, db: Session, forced_garment: str | None = None, forced_color: str | None = None) -> dict:
    """
    The whole pipeline for one design: trend research -> image -> tagging ->
    saved Design row. Shared by the single-design, batch, and agent-demo
    endpoints so they can't drift apart. Every call reports to the
    Design agent's activity feed (app/agent_log.py), success or failure,
    so the admin "Agent Status" dashboard reflects real runs, not just
    the pipeline demo.
    """
    try:
        summary, sources = research_trend(query)
    except Exception as e:
        log.exception("Tavily trend research failed")
        log_activity(db, "design", "error", f"Trend research failed: {type(e).__name__}: {e}")
        return {"status": "error", "stage": "trend_research", "detail": f"{type(e).__name__}: {e}", "query": query}

    image_prompt = f"{summary}{IMAGE_STYLE_SUFFIX}"

    try:
        image_bytes = generate_image(image_prompt, size="1024x1024")
    except Exception as e:
        log.exception("Image generation failed")
        log_activity(db, "design", "error", f"Image generation failed: {type(e).__name__}: {e}")
        return {"status": "error", "stage": "image_generation", "detail": f"{type(e).__name__}: {e}", "query": query}

    # Tagging/color extraction feeds visual search (see app/visual_search.py)
    # but isn't core to "did we get a design" - a Vision hiccup here
    # shouldn't fail the whole generation. Falls back to untagged; a design
    # with no tags yet gets backfilled lazily on first search.
    vision_tags_text, dominant_color_text = None, None
    try:
        tags, color = extract_signals(image_bytes)
        vision_tags_text, dominant_color_text = tags_to_text(tags), color_to_text(color)
        log.info("Vision tagging OK for new design: tags=%s color=%s", tags, color)
    except Exception:
        log.exception("Vision tagging FAILED for new design (non-fatal, will backfill on search)")

    # Mixed product matrix (see app/garments.py): every design lands on a
    # different garment type, and a color picked to contrast with the
    # design's own dominant color, instead of always the same white tee -
    # unless the admin forced a specific garment/color for this run (the
    # "Garment"/"Color" selectors on the Generate form), in which case that
    # choice wins outright.
    auto_garment, auto_color = pick_garment_and_color(dominant_color_text)
    garment = forced_garment if forced_garment in GARMENTS else auto_garment
    color = forced_color if forced_color in COLORS else auto_color

    design = Design(
        trend_query=query,
        trend_summary=summary,
        sources="\n".join(sources),
        image_prompt=image_prompt,
        image_data=image_bytes,
        vision_tags=vision_tags_text,
        dominant_color=dominant_color_text,
        garment=garment,
        color=color,
        status="pending",
    )
    db.add(design)
    db.commit()
    db.refresh(design)

    log_activity(
        db, "design", "ok",
        f"Generated design #{design.id} ({garment_label(garment)}, {color_label(color)}) from live trend research.",
        design_id=design.id,
    )

    return {
        "status": "ok",
        "id": design.id,
        "image_url": f"/api/admin/design/{design.id}/image",
        "trend_summary": summary,
        "sources": sources,
        "garment": garment,
        "color": color,
    }


@router.post("/api/admin/design/generate")
def generate_design(
    focus: str = Form(default=""),  # optional: admin can narrow the trend search
    garment: str = Form(default=""),  # optional: force a garment instead of random
    color: str = Form(default=""),  # optional: force a color instead of random
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = focus.strip() or DEFAULT_TREND_QUERY
    return _generate_one_design(query, db, forced_garment=garment or None, forced_color=color or None)


MAX_BATCH_SIZE = 8


@router.post("/api/admin/design/generate-batch")
def generate_batch(
    count: int = Form(default=MAX_BATCH_SIZE),
    garment: str = Form(default=""),  # optional: force every design in the batch onto one garment
    color: str = Form(default=""),  # optional: force every design in the batch onto one color
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """
    Runs several generations back to back, each pointed at a different style
    preset (BATCH_STYLE_PRESETS) so the batch doesn't converge on one look.
    Synchronous and can take a couple of minutes for a full batch of 8 -
    the admin UI warns about this and shows a running count rather than a
    single spinner. Garment/color default to the mixed-matrix auto-pick
    (each design independently random, contrast-matched to its own art) -
    forcing one here pins every design in this batch to the same garment
    and/or color instead, for when the admin wants a themed batch.
    """
    count = max(1, min(count, MAX_BATCH_SIZE))
    forced_garment, forced_color = garment or None, color or None
    results = []
    for i in range(count):
        preset = BATCH_STYLE_PRESETS[i % len(BATCH_STYLE_PRESETS)]
        query = f"{preset} — trending T-shirt graphic design right now"
        results.append(_generate_one_design(query, db, forced_garment=forced_garment, forced_color=forced_color))
    return {"results": results, "succeeded": sum(1 for r in results if r["status"] == "ok")}


@router.post("/api/admin/design/{design_id}/reassign")
def reassign_design(
    design_id: int,
    garment: str = Form(...),
    color: str = Form(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """
    Moves an already-generated design onto a different garment/color combo
    without re-running trend research or image generation - for the designs
    that predate the garment matrix (they all landed on the T-Shirt/White
    default) or any design the admin just wants to see on a different
    product. The mockup is re-composited on the fly from the existing
    artwork the next time it's requested (see mockup_routes.resolve_design_template) -
    nothing to regenerate here, just the two columns on the Design row.
    """
    if garment not in GARMENTS:
        raise HTTPException(status_code=400, detail=f"Unknown garment '{garment}'")
    if color not in COLORS:
        raise HTTPException(status_code=400, detail=f"Unknown color '{color}'")

    design = db.query(Design).filter(Design.id == design_id).first()
    if not design:
        raise HTTPException(status_code=404, detail="Design not found")

    design.garment = garment
    design.color = color
    db.commit()

    log_activity(
        db, "design", "ok",
        f"Reassigned design #{design.id} to {garment_label(garment)}, {color_label(color)}.",
        design_id=design.id,
    )

    return {
        "status": "ok",
        "id": design.id,
        "garment": garment,
        "color": color,
        "garment_label": garment_label(garment),
        "color_label": color_label(color),
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
            "garment": d.garment,
            "color": d.color,
            "garment_label": garment_label(d.garment),
            "color_label": color_label(d.color),
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
