"""
The product matrix: which garment types and colors exist, which colors each
garment is actually sold in, and how a design gets assigned a combo.

Shared by the mockup-template generator (photographs each combo once, as a
fallback backdrop), the AI product-photo pipeline (app/product_photos.py),
the design agent (assigns a combo to every design) and the compositor
(print-area geometry per garment).

Each garment lists only the colors it's sold in (not a full cross product):
that keeps the template matrix - and the image-model bill - small, and
avoids offering combos nobody would sell (a white hoodie print on white).
"""
import random

GARMENTS: dict[str, dict] = {
    "tshirt": {
        "label": "T-Shirt",
        "photo_desc": "a plain crewneck short-sleeve T-shirt",
        "category": "top",
        "printable": True,
        "colors": ["white", "black", "beige", "heather-gray"],
        "keywords": ["t-shirt", "tshirt", "shirt", "tee"],
        "avoid_keywords": ["hoodie", "sweatshirt"],
        "placement": "centered on the chest, roughly 30% of the garment width, a hand-width below the collar",
    },
    "long-sleeve": {
        "label": "Full-Sleeve Shirt",
        "photo_desc": "a plain long-sleeve crew shirt with full-length sleeves reaching the wrists",
        "category": "top",
        "printable": True,
        "colors": ["white", "black", "heather-gray"],
        "keywords": ["long sleeve", "long-sleeve", "shirt", "sweater", "sweatshirt"],
        "avoid_keywords": ["hoodie"],
        "placement": "centered on the chest, roughly 30% of the garment width, a hand-width below the collar",
    },
    "hoodie": {
        "label": "Hoodie",
        "photo_desc": "a plain pullover hoodie with a kangaroo front pocket and a drawstring hood",
        "category": "top",
        "printable": True,
        "colors": ["black", "heather-gray", "beige"],
        "keywords": ["hoodie", "hooded", "sweatshirt"],
        "avoid_keywords": [],
        "placement": "centered on the chest ABOVE the kangaroo pocket and clear of the drawstrings, roughly 28% of the garment width",
    },
    "shorts": {
        "label": "Shorts",
        "photo_desc": "a pair of plain mid-thigh athletic/lounge shorts with an elastic drawstring waistband",
        "category": "bottom",
        "printable": True,
        "colors": ["black", "beige", "heather-gray"],
        "keywords": ["shorts", "short"],
        "avoid_keywords": [],
        "placement": "a small graphic on the wearer's left thigh, about a hand-width above the hem",
    },
    "linen-shirt": {
        "label": "Linen Shirt",
        "photo_desc": "a relaxed button-up linen shirt with a soft camp collar and natural fabric texture",
        "category": "top",
        "printable": False,   # sold plain - the Linen Edit, no graphic
        "colors": ["beige", "white", "sage"],
        "keywords": ["shirt", "linen", "button"],
        "avoid_keywords": ["hoodie"],
        "placement": "",
    },
}

COLORS: dict[str, dict] = {
    "white": {"label": "White", "photo_desc": "crisp white", "rgb": (245, 245, 245), "words": ["white", "cream", "ivory"]},
    "black": {"label": "Black", "photo_desc": "black", "rgb": (24, 24, 26), "words": ["black", "dark"]},
    "heather-gray": {"label": "Heather Gray", "photo_desc": "heather gray", "rgb": (150, 150, 150), "words": ["gray", "grey"]},
    "beige": {"label": "Beige", "photo_desc": "soft sand beige", "rgb": (221, 204, 178), "words": ["beige", "tan", "cream", "khaki", "sand", "brown"]},
    "sage": {"label": "Sage", "photo_desc": "muted sage green", "rgb": (160, 176, 140), "words": ["green", "sage", "olive"]},
}

DEFAULT_GARMENT = "tshirt"
DEFAULT_COLOR = "white"


def all_combos() -> list[tuple[str, str]]:
    """Every (garment, color) pair actually sold."""
    return [(g, c) for g, info in GARMENTS.items() for c in info["colors"]]


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def pick_garment_and_color(dominant_color_text: str | None) -> tuple[str, str]:
    """
    Picks a printable garment at random (so the grid looks mixed) and, from
    the colors THAT garment is sold in, one that contrasts with the design's
    own dominant color - so a mostly-white graphic never gets lost on a
    white shirt and a dark one isn't buried on black.
    """
    garment = random.choice([g for g, info in GARMENTS.items() if info["printable"]])
    allowed = GARMENTS[garment]["colors"]

    try:
        lum = luminance(tuple(int(p) for p in dominant_color_text.split(",")))  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return garment, random.choice(allowed)

    # Rank allowed colors by how far their luminance is from the design's,
    # then pick among the best two so the grid doesn't become monotone.
    ranked = sorted(allowed, key=lambda c: -abs(luminance(COLORS[c]["rgb"]) - lum))
    return garment, random.choice(ranked[:2])


def garment_label(garment: str | None) -> str:
    return GARMENTS.get(garment or DEFAULT_GARMENT, GARMENTS[DEFAULT_GARMENT])["label"]


def color_label(color: str | None) -> str:
    return COLORS.get(color or DEFAULT_COLOR, COLORS[DEFAULT_COLOR])["label"]
