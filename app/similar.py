"""Rank approved products by visual similarity to an uploaded photo (used by
the shop's 'Find something like it' and by the shop assistant's image scan)."""
import logging

from sqlalchemy.orm import Session

from .db import Design
from .visual_search import (
    extract_signals, match_score, tags_to_text, text_to_tags, color_to_text, text_to_color,
)

log = logging.getLogger(__name__)


def find_similar(db: Session, image_bytes: bytes, limit: int = 6) -> tuple[list[tuple[float, Design]], list[str]]:
    """Returns ([(score 0..1, design), ...] best first, query_tags). Raises
    ValueError if the photo can't be analyzed."""
    try:
        query_tags, query_color = extract_signals(image_bytes)
    except Exception as e:
        log.exception("Similarity search: could not analyze the uploaded photo")
        raise ValueError("Couldn't read that as an image") from e

    scored = []
    for d in db.query(Design).filter(Design.status == "approved").all():
        if d.vision_tags is None or d.dominant_color is None:
            try:
                tags, color = extract_signals(d.image_data)
                d.vision_tags, d.dominant_color = tags_to_text(tags), color_to_text(color)
                db.add(d)
            except Exception:
                log.exception("Similarity search: backfill tagging failed for design %s", d.id)
                continue
        scored.append((match_score(query_tags, query_color, text_to_tags(d.vision_tags), text_to_color(d.dominant_color)), d))
    db.commit()
    scored.sort(key=lambda p: p[0], reverse=True)
    return scored[:limit], query_tags
