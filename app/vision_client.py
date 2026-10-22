"""
Shared Azure AI Vision client - used by vision_routes.py (Vision Lens) and
now visual_search.py (design tagging + visual-search matching). Pulled out
once here so both callers share the exact same, already-proven-working
client setup instead of duplicating it.
"""
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential

from .config import settings


def get_vision_client() -> ImageAnalysisClient:
    return ImageAnalysisClient(
        endpoint=settings.VISION_ENDPOINT,
        credential=AzureKeyCredential(settings.VISION_KEY),
    )


def analyze_tags_and_caption(image_bytes: bytes) -> tuple[list[str], str | None]:
    """Returns (tags, caption) for an image, using the same Vision call Vision Lens makes."""
    client = get_vision_client()
    result = client.analyze(
        image_data=image_bytes,
        visual_features=[VisualFeatures.TAGS, VisualFeatures.CAPTION],
    )
    tags = [t.name for t in result.tags.list] if result.tags else []
    caption = result.caption.text if result.caption else None
    return tags, caption
