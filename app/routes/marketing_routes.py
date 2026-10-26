"""
Marketing agent - two jobs, neither needs a new Azure resource or a new
Foundry agent to set up:

  1. Trend radar: re-runs the same live Tavily research the design agent
     uses, then compares it against every approved design's own trend
     research (simple keyword overlap - no extra AI call) to flag when a
     current trend genuinely isn't covered by the catalog yet.

  2. Caption drafting: for an approved design, builds a ready-to-post
     social caption + hashtags straight from that design's own trend
     summary and Vision tags - rule-based, not a second generation call,
     same philosophy as app/compositing.py (deterministic, not an AI call
     per request).

Both write to the shared AgentActivity feed (app/agent_log.py) so the
admin "Agent Status" dashboard reflects real runs of this agent, not just
the pipeline demo.
"""
import re
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db, Design, User
from ..auth import require_admin
from ..trend_research import research_trend
from ..agent_log import log_activity
from ..retry import with_retry
from .design_routes import _generate_one_design

log = logging.getLogger(__name__)
router = APIRouter()

TREND_RADAR_QUERY = (
    "trending T-shirt graphic design styles and themes right now, new and emerging"
)
# Below this fraction of shared keywords with the single best-matching
# approved design, a fresh trend is considered "not in the catalog yet."
OVERLAP_THRESHOLD = 0.15

STOPWORDS = {
    "the", "a", "an", "and", "or", "with", "for", "of", "in", "on", "to", "is",
    "are", "this", "that", "from", "their", "its", "as", "by", "at", "be",
    "has", "have", "will", "also", "into", "about", "more", "than", "such",
    "which", "these", "those", "can", "often", "like", "while", "one", "right",
    "now", "trending", "trends", "trend", "design", "designs", "graphic", "tshirt",
}


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]{3,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def _draft_caption(design: Design) -> tuple[str, str]:
    """Builds (caption, hashtags) purely from data already on the row."""
    summary = (design.trend_summary or "").strip()
    first_sentence = re.split(r"(?<=[.!?])\s", summary)[0] if summary else "A new drop from today's research."
    hook = first_sentence if len(first_sentence) <= 180 else first_sentence[:177].rsplit(" ", 1)[0] + "..."
    caption = f"New drop, straight from today's trend research: {hook}"

    tag_source: list[str] = []
    if design.vision_tags:
        tag_source.extend(t.strip() for t in design.vision_tags.split(",") if t.strip())
    tag_source.extend(sorted(_keywords(summary)))

    seen: list[str] = []
    for t in tag_source:
        tag = "#" + re.sub(r"[^a-zA-Z0-9]", "", t).lower()
        if len(tag) > 2 and tag not in seen:
            seen.append(tag)
        if len(seen) >= 6:
            break
    hashtags = " ".join(seen + ["#LoomwellAI", "#AIFashion"])
    return caption, hashtags


@router.post("/api/admin/marketing/draft/{design_id}")
def draft_caption(
    design_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    design = db.query(Design).filter(Design.id == design_id, Design.status == "approved").first()
    if not design:
        raise HTTPException(status_code=404, detail="Approved design not found")

    caption, hashtags = _draft_caption(design)
    design.social_caption = caption
    design.social_hashtags = hashtags
    db.commit()

    log_activity(db, "marketing", "ok", f"Drafted a social caption for design #{design.id}.", design_id=design.id)
    return {"id": design.id, "caption": caption, "hashtags": hashtags}


@router.post("/api/admin/marketing/scan-trends")
def scan_trends(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    try:
        summary, sources = research_trend(TREND_RADAR_QUERY)
    except Exception as e:
        log.exception("Marketing trend scan failed")
        log_activity(db, "marketing", "error", f"Trend scan failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail="Trend research failed - check Log Stream")

    fresh_kw = _keywords(summary)
    approved = db.query(Design).filter(Design.status == "approved").all()

    best_overlap = 0.0
    for d in approved:
        existing_kw = _keywords(d.trend_summary)
        if not existing_kw or not fresh_kw:
            continue
        overlap = len(fresh_kw & existing_kw) / len(fresh_kw)
        best_overlap = max(best_overlap, overlap)

    flagged = (not approved) or best_overlap < OVERLAP_THRESHOLD
    generated = None

    if flagged:
        log_activity(
            db, "marketing", "alert",
            f"New trend not yet in the catalog: {summary[:240]}",
        )
        # Don't just flag it - close the loop by actually commissioning a
        # design for the gap the agent just found, same as the demo
        # pipeline does, so "scan for trends" visibly produces output
        # instead of a passive note nobody acts on.
        result = _generate_one_design(TREND_RADAR_QUERY, db)
        if result["status"] == "ok":
            generated = result["id"]
            log_activity(
                db, "marketing", "ok",
                f"Commissioned design #{generated} from the Design agent to cover that gap - pending review.",
                design_id=generated,
            )
        else:
            log_activity(
                db, "marketing", "error",
                f"Flagged a trend gap but couldn't commission a design for it: {result.get('detail')}",
            )
    else:
        log_activity(
            db, "marketing", "ok",
            f"Scanned current trends - catalog already covers them (best overlap {round(best_overlap * 100)}%).",
        )

    return {
        "flagged": flagged,
        "summary": summary,
        "sources": sources,
        "best_overlap": round(best_overlap, 2),
        "generated_design_id": generated,
    }


GRAPH_API_VERSION = "v21.0"


def instagram_configured() -> bool:
    return bool(settings.INSTAGRAM_ACCESS_TOKEN and settings.INSTAGRAM_BUSINESS_ACCOUNT_ID)


def _post_to_instagram(image_url: str, caption: str) -> str:
    """
    Two-step Instagram Graph API publish: create a media container from a
    PUBLICLY reachable image URL (Instagram's servers fetch it themselves -
    it can't be a local/relative path), then publish that container. Each
    step retries on timeouts/5xx/429 (see app/retry.py) - NOT on the
    create step retried as a whole with publish, since retrying a
    successful create would mint duplicate media containers; each step is
    its own independent retry instead. Raises on any HTTP error; returns
    the published media id.
    """
    base = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{settings.INSTAGRAM_BUSINESS_ACCOUNT_ID}"

    def _create():
        resp = httpx.post(
            f"{base}/media",
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": settings.INSTAGRAM_ACCESS_TOKEN,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp

    create = with_retry(_create, label="instagram_create_media")
    creation_id = create.json()["id"]

    def _publish():
        resp = httpx.post(
            f"{base}/media_publish",
            data={"creation_id": creation_id, "access_token": settings.INSTAGRAM_ACCESS_TOKEN},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp

    publish = with_retry(_publish, label="instagram_publish_media")
    return publish.json()["id"]


@router.post("/api/admin/marketing/schedule-post/{design_id}")
def schedule_post(
    design_id: int, request: Request, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    """
    "Post to Instagram" for one approved design, using its already-drafted
    caption/hashtags (drafted on the fly here if that hasn't happened yet).
    Despite the name there's no actual time-of-day scheduler behind this
    yet - it posts immediately when clicked; the name matches what the
    admin UI calls the button, and is the natural next step if real
    scheduling gets built later.
    """
    design = db.query(Design).filter(Design.id == design_id, Design.status == "approved").first()
    if not design:
        raise HTTPException(status_code=404, detail="Approved design not found")

    if not design.social_caption:
        caption, hashtags = _draft_caption(design)
        design.social_caption, design.social_hashtags = caption, hashtags
        db.commit()

    full_caption = f"{design.social_caption}\n\n{design.social_hashtags or ''}".strip()

    if not instagram_configured():
        entry = log_activity(
            db, "marketing", "simulated",
            f"Simulated an Instagram post for design #{design_id}: \"{design.social_caption[:100]}\" "
            f"- Instagram isn't connected yet, nothing was actually posted.",
            design_id=design_id,
        )
        return {"mode": "simulated", "design_id": design_id, "message": entry.message}

    image_url = f"{str(request.base_url).rstrip('/')}/api/public/design/{design_id}/mockup/front"
    try:
        media_id = _post_to_instagram(image_url, full_caption)
    except Exception as e:
        log.exception("Instagram post failed for design %s", design_id)
        log_activity(db, "marketing", "error", f"Instagram post failed for design #{design_id}: {type(e).__name__}: {e}", design_id=design_id)
        raise HTTPException(status_code=502, detail="Instagram post failed - check Log Stream for details.")

    log_activity(db, "marketing", "ok", f"Posted design #{design_id} to Instagram (media id {media_id}).", design_id=design_id)
    return {"mode": "live", "design_id": design_id, "media_id": media_id}


@router.get("/api/admin/marketing/feed")
def marketing_feed(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    approved = (
        db.query(Design)
        .filter(Design.status == "approved")
        .order_by(Design.created_at.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "image_url": f"/api/admin/design/{d.id}/image",
            "trend_summary": d.trend_summary,
            "caption": d.social_caption,
            "hashtags": d.social_hashtags,
        }
        for d in approved
    ]
