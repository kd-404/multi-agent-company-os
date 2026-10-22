"""
Shared Azure image-generation client, used by both the design agent
(design_routes.py) and the mockup-template generator (mockup_routes.py).

Why this is its own module: both callers need the exact same client setup
(same endpoint-derivation quirk, same credential), so it's pulled out once
here instead of duplicated. See the docstring on _azure_openai_base_url for
why the endpoint path is what it is - that was hard-won from a live 404.
"""
from urllib.parse import urlsplit

from openai import OpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from .config import settings

_image_client: OpenAI | None = None


def _azure_openai_base_url() -> str:
    """
    Image generation is NOT served from the Foundry *project* endpoint
    (<resource>.services.ai.azure.com/api/projects/<name>) that the chat
    agent uses - that path only serves agent/thread operations and 404s on
    /images/generations. It's served from the SAME host, under /openai/v1
    instead - confirmed against the "View code" sample Foundry generates
    for this exact deployment. So we only swap the path, never the host,
    deriving it from FOUNDRY_PROJECT_ENDPOINT instead of needing a second
    URL typed into Azure App Settings.
    """
    parts = urlsplit(settings.FOUNDRY_PROJECT_ENDPOINT)
    return f"{parts.scheme}://{parts.netloc}/openai/v1"


def get_image_client() -> OpenAI:
    global _image_client
    if _image_client is None:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://ai.azure.com/.default"
        )
        _image_client = OpenAI(base_url=_azure_openai_base_url(), api_key=token_provider)
    return _image_client


def generate_image(prompt: str, size: str = "1024x1024") -> bytes:
    """Calls the Foundry image deployment and returns raw PNG bytes."""
    client = get_image_client()
    result = client.images.generate(
        model=settings.FOUNDRY_IMAGE_DEPLOYMENT,
        prompt=prompt,
        size=size,
        n=1,
    )
    # gpt-image-1/1.5 series always return base64, never a URL.
    import base64
    return base64.b64decode(result.data[0].b64_json)
