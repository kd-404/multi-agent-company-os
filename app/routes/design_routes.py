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
import base64
import logging
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Response
from sqlalchemy.orm import Session
from openai import OpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from ..config import settings
from ..db import get_db, Design, User
from ..auth import require_admin

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

_image_client: OpenAI | None = None


def _azure_openai_base_url() -> str:
    """
    Image generation is NOT served from the Foundry *project* endpoint
    (<resource>.services.ai.azure.com/api/projects/<name>) that the chat
    agent uses - that path only serves agent/thread operations and 404s on
    /images/generations. It's served from the SAME host, under /openai/v1
    instead - confirmed against the "View code" sample Foundry generates
    for this exact deployment (not the generic openai.azure.com pattern
    some Microsoft docs show, which 404s here). So we only swap the path,
    never the host, deriving it from FOUNDRY_PROJECT_ENDPOINT instead of
    needing a second URL typed into Azure App Settings.
    """
    parts = urlsplit(settings.FOUNDRY_PROJECT_ENDPOINT)
    return f"{parts.scheme}://{parts.netloc}/openai/v1"


def _get_image_client() -> OpenAI:
    global _image_client
    if _image_client is None:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://ai.azure.com/.default"
        )
        _image_client = OpenAI(base_url=_azure_openai_base_url(), api_key=token_provider)
    return _image_client


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


def _generate_image(prompt: str) -> bytes:
    client = _get_image_client()
    result = client.images.generate(
        model=settings.FOUNDRY_IMAGE_DEPLOYMENT,
        prompt=prompt,
        size="1024x1024",
        n=1,
    )
    # gpt-image-1/1.5 series always return base64, never a URL.
    b64 = result.data[0].b64_json
    return base64.b64decode(b64)


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
        image_bytes = _generate_image(image_prompt)
    except Exception as e:
        log.exception("Image generation failed")
        return {"status": "error", "stage": "image_generation", "detail": f"{type(e).__name__}: {e}"}

    design = Design(
        trend_query=query,
        trend_summary=summary,
        sources="\n".join(sources),
        image_prompt=image_prompt,
        image_data=image_bytes,
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
