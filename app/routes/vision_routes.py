"""
Lens-style vision endpoint, backed by Azure AI Vision Image Analysis.
Two modes from the same uploaded image:
  - "general": object/scene tags, OCR text, captions -> Lens-style behaviour
  - "design_check": tags + a code deny-list of protected names/brands/titles
    (same idea as the Design Studio's IP & Originality Check agent) ->
    flags a possible originality issue before a human ever reviews it
"""
from fastapi import APIRouter, UploadFile, File, Form, Depends
from azure.ai.vision.imageanalysis.models import VisualFeatures

from ..auth import require_permission
from ..vision_client import get_vision_client

router = APIRouter()

# Deny-list is code, not LLM judgment, on purpose — an LLM can be argued out
# of a flag, a plain string match on the Vision tags/caption cannot.
DENY_LIST = [
    "nike", "adidas", "puma", "marvel", "disney", "star wars",
    "thalapathi", "nayakan",  # Tamil-film titles/star nicknames, per the brief
]


@router.post("/api/vision/analyze")
async def analyze_image(
    file: UploadFile = File(...),
    mode: str = Form("general"),
    _user=Depends(require_permission("vision")),
):
    client = get_vision_client()
    image_bytes = await file.read()

    result = client.analyze(
        image_data=image_bytes,
        visual_features=[
            VisualFeatures.CAPTION,
            VisualFeatures.TAGS,
            VisualFeatures.READ,  # OCR
            VisualFeatures.OBJECTS,
        ],
    )

    caption = result.caption.text if result.caption else None
    confidence = result.caption.confidence if result.caption else None
    tags = [t.name for t in result.tags.list] if result.tags else []
    objects = [o.tags[0].name for o in result.objects.list if o.tags] if result.objects else []
    text_lines = []
    if result.read:
        for block in result.read.blocks:
            for line in block.lines:
                text_lines.append(line.text)

    response = {
        "caption": caption,
        "confidence": confidence,
        "tags": tags,
        "objects": objects,
        "detected_text": text_lines,
    }

    if mode == "design_check":
        haystack = " ".join(tags + objects + text_lines + ([caption] if caption else [])).lower()
        flagged = [term for term in DENY_LIST if term in haystack]
        response["originality_flagged"] = len(flagged) > 0
        response["flagged_terms"] = flagged

    return response
