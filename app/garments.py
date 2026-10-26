"""
The product matrix: which garment types and colors a design can be
rendered on, instead of every approved design always landing on the same
blank white tee. Shared by the mockup-template generator (which needs to
photograph each combo once), the design agent (which assigns a combo to
every design it generates), and the compositor (which needs the print-area
geometry per garment).

Deliberately a small, fixed matrix (4 garments x 3 colors = 12 combos) -
each combo needs 2-3 image-model calls to photograph once, so this stays
small enough that "Generate mockup templates" finishes in a few minutes
rather than becoming its own slow batch job. See mockup_routes.py's
generate_templates() for why that generation step now SKIPS already-
photographed combos by default instead of re-spending an image-model call
on every combo every time - adding a garment here only costs new calls
for the combos that are actually new.
"""
import random

GARMENTS: dict[str, dict] = {
    "tshirt": {
        "label": "T-Shirt",
        # used in the template photo prompt
        "photo_desc": "a plain crewneck short-sleeve T-shirt",
        "category": "top",
    },
    "long-sleeve": {
        "label": "Full-Sleeve Shirt",
        "photo_desc": "a plain long-sleeve crew shirt with full-length sleeves reaching the wrists",
        "category": "top",
    },
    "hoodie": {
        "label": "Hoodie",
        "photo_desc": "a plain pullover hoodie with a kangaroo front pocket and a drawstring hood",
        "category": "top",
    },
    "shorts": {
        "label": "Shorts",
        "photo_desc": "a pair of plain mid-thigh athletic/lounge shorts with an elastic drawstring waistband",
        "category": "bottom",
    },
}

COLORS: dict[str, dict] = {
    "white": {"label": "White", "photo_desc": "white", "rgb": (245, 245, 245)},
    "black": {"label": "Black", "photo_desc": "black", "rgb": (24, 24, 26)},
    "heather-gray": {"label": "Heather Gray", "photo_desc": "heather gray", "rgb": (150, 150, 150)},
}

DEFAULT_GARMENT = "tshirt"
DEFAULT_COLOR = "white"


def pick_garment_and_color(dominant_color_text: str | None) -> tuple[str, str]:
    """
    Picks a garment at random (so the grid looks mixed - hoodies, long
    sleeves, tees side by side) and a garment COLOR chosen to contrast
    with the design's own dominant color, so a mostly-white graphic never
    gets silently lost on a white shirt. Falls back to a random color
    when the design has no vision-extracted dominant color yet.
    """
    garment = random.choice(list(GARMENTS))

    if not dominant_color_text:
        return garment, random.choice(list(COLORS))

    try:
        r, g, b = (int(p) for p in dominant_color_text.split(","))
    except (ValueError, AttributeError):
        return garment, random.choice(list(COLORS))

    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    if luminance > 170:
        color = "black"
    elif luminance < 85:
        color = "white"
    else:
        color = random.choice(["white", "black", "heather-gray"])
    return garment, color


def garment_label(garment: str | None) -> str:
    return GARMENTS.get(garment or DEFAULT_GARMENT, GARMENTS[DEFAULT_GARMENT])["label"]


def color_label(color: str | None) -> str:
    return COLORS.get(color or DEFAULT_COLOR, COLORS[DEFAULT_COLOR])["label"]
