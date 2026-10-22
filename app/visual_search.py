"""
Visual search: "upload a photo, find the most similar designs in the
catalog." Matches on two real, extracted signals instead of raw pixels:

  1. Pattern/subject tags - from the SAME Azure AI Vision resource and
     client already proven working in production for Vision Lens
     (app/vision_client.py). This is genuine AI image understanding
     ("floral", "skull", "line art", "geometric"), not metadata someone
     typed in.
  2. Dominant color - computed locally with Pillow (no Azure call): the
     average color of the design itself, with the flat background
     chroma-keyed out first so a white background doesn't just make
     every design "white."

Why not a full embedding model (what Flipkart/Amazon actually run)? That
needs either a self-hosted model (large deploy footprint, real risk on a
free-tier App Service we've already seen struggle) or Azure's Image
Retrieval API (region-limited, untested on this account - the same kind
of thing that cost a lot of debugging time earlier in this project). This
reuses infrastructure that is ALREADY live and working, at the cost of
matching on "what it looks like" (subject + color) rather than deep
stylistic meaning. A real step up from pixel-pattern hashing, at zero new
Azure risk.
"""
from io import BytesIO

from PIL import Image

from .vision_client import analyze_tags_and_caption


def extract_signals(image_bytes: bytes) -> tuple[list[str], tuple[int, int, int]]:
    """Returns (tags, dominant_rgb) for one image. Used both at design-generation time and for an uploaded search photo."""
    tags, _caption = analyze_tags_and_caption(image_bytes)
    color = _dominant_color(image_bytes)
    return tags, color


def _dominant_color(image_bytes: bytes, threshold: int = 24) -> tuple[int, int, int]:
    """
    Average color of the design itself, background excluded. Samples the
    background color from the four corners (same trick as
    app/compositing.py's chroma key) so a design on a white/flat backdrop
    isn't just reported as white.
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    small = img.resize((64, 64), Image.LANCZOS)
    w, h = small.size
    corners = [small.getpixel((0, 0)), small.getpixel((w - 1, 0)),
               small.getpixel((0, h - 1)), small.getpixel((w - 1, h - 1))]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    total = [0, 0, 0]
    count = 0
    for y in range(h):
        for x in range(w):
            r, g, b = small.getpixel((x, y))
            dist = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            if dist > threshold:
                total[0] += r
                total[1] += g
                total[2] += b
                count += 1

    if count == 0:  # the whole image was "background" (e.g. a blank image)
        return bg
    return (total[0] // count, total[1] // count, total[2] // count)


def tags_to_text(tags: list[str]) -> str:
    return ",".join(tags)


def text_to_tags(text: str | None) -> list[str]:
    return text.split(",") if text else []


def color_to_text(color: tuple[int, int, int]) -> str:
    return f"{color[0]},{color[1]},{color[2]}"


def text_to_color(text: str | None) -> tuple[int, int, int]:
    if not text:
        return (128, 128, 128)
    r, g, b = (int(p) for p in text.split(","))
    return (r, g, b)


def match_score(
    tags_a: list[str], color_a: tuple[int, int, int],
    tags_b: list[str], color_b: tuple[int, int, int],
) -> float:
    """
    0..1 combined similarity: 65% tag overlap (what it's a picture of),
    35% color closeness (how it's colored). Weighted toward tags because
    two designs sharing a subject ("skull", "floral") read as more
    genuinely "similar" to a shopper than two unrelated designs that
    happen to share a palette.
    """
    set_a, set_b = set(t.lower() for t in tags_a), set(t.lower() for t in tags_b)
    if set_a or set_b:
        tag_score = len(set_a & set_b) / len(set_a | set_b) if (set_a | set_b) else 0.0
    else:
        tag_score = 0.0

    max_dist = (255 ** 2 * 3) ** 0.5
    dist = sum((a - b) ** 2 for a, b in zip(color_a, color_b)) ** 0.5
    color_score = 1 - (dist / max_dist)

    return round(0.65 * tag_score + 0.35 * color_score, 4)
