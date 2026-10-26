"""
Shared Azure AI Vision client - used by vision_routes.py (Vision Lens) and
now visual_search.py (design tagging + visual-search matching). Pulled out
once here so both callers share the exact same, already-proven-working
client setup instead of duplicating it.
"""
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError

from .config import settings
from .retry import with_retry


def get_vision_client() -> ImageAnalysisClient:
    return ImageAnalysisClient(
        endpoint=settings.VISION_ENDPOINT,
        credential=AzureKeyCredential(settings.VISION_KEY),
    )


def _is_retryable_vision_error(exc: Exception) -> bool:
    """429/5xx from the Vision resource, or a network-level failure
    reaching it, is worth retrying; a 4xx (bad key, malformed image) is not."""
    if isinstance(exc, (ServiceRequestError, ServiceResponseError)):
        return True
    if isinstance(exc, HttpResponseError):
        return (exc.status_code or 0) in (429, 500, 502, 503, 504)
    return False


def analyze_tags_and_caption(image_bytes: bytes) -> tuple[list[str], str | None]:
    """Returns (tags, caption) for an image, using the same Vision call
    Vision Lens makes (with retry/backoff on rate limits/5xx/network
    errors - see app/retry.py)."""
    client = get_vision_client()

    def _call():
        return client.analyze(
            image_data=image_bytes,
            visual_features=[VisualFeatures.TAGS, VisualFeatures.CAPTION],
        )

    result = with_retry(_call, label="vision_analyze", retryable=_is_retryable_vision_error)
    tags = [t.name for t in result.tags.list] if result.tags else []
    caption = result.caption.text if result.caption else None
    return tags, caption
