"""
Pure image-math compositing: takes a generated design (flat graphic, roughly
square, flat-ish background) and pastes it onto a blank T-shirt mockup
template photo, in a fixed print area. No AI calls happen in this file -
that's the whole point. The AI parts (trend research, design generation,
template photography) each run once; this runs every time someone views a
mockup and is cheap, fast and deterministic.

PRINT_AREAS below are first-guess coordinates (as fractions of the template
image's width/height) for where the chest-print region sits in each
template photo. They were picked to match the framing the template prompts
ask for (flat-lay, centered, shot from directly above / slight angle for
"side"), but the image model doesn't guarantee pixel-perfect framing every
time it's asked to regenerate a template - if a design looks off-center or
mis-sized once real templates exist, these are the numbers to nudge.
"""
from io import BytesIO

from PIL import Image, ImageChops, ImageFilter

# (left, top, right, bottom) as fractions of template width/height.
PRINT_AREAS: dict[str, tuple[float, float, float, float]] = {
    "front": (0.37, 0.27, 0.63, 0.50),
    "side": (0.40, 0.30, 0.60, 0.48),
    # "back" has no print area - a design agent run only ever produces one
    # graphic, meant for the front; the back template stays a blank shirt,
    # same as a real single-sided print-on-demand listing.
}

# Horizontal shear applied to the design on the "side" angle shot, to
# suggest the garment is turned rather than flat-on to the camera.
SIDE_SHEAR = 0.15


def _remove_background(design: Image.Image, threshold: int = 24) -> Image.Image:
    """
    The design image comes back as a flat PNG with a solid-ish background
    (gpt-image models don't reliably emit true alpha transparency even when
    asked to), not a graphic with real transparency. This samples the
    background color from the four corners and makes close-matching pixels
    transparent, with a soft feather on the alpha so the cutout edge isn't
    a hard jagged line.
    """
    rgba = design.convert("RGBA")
    w, h = rgba.size
    corners = [rgba.getpixel((0, 0)), rgba.getpixel((w - 1, 0)),
               rgba.getpixel((0, h - 1)), rgba.getpixel((w - 1, h - 1))]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    pixels = rgba.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            dist = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            if dist < threshold:
                pixels[x, y] = (r, g, b, 0)

    alpha = rgba.getchannel("A").filter(ImageFilter.GaussianBlur(2))
    rgba.putalpha(alpha)
    return rgba


def _shade_onto_fabric(design_rgba: Image.Image, template_region: Image.Image) -> Image.Image:
    """
    Makes the flat design pick up the template photo's own lighting/wrinkles
    instead of sitting on top like a sticker: multiplies the design's RGB by
    the template region's grayscale luminance, keeping the design's own
    alpha mask.
    """
    shadow_map = template_region.convert("L").convert("RGB")
    shaded_rgb = ImageChops.multiply(design_rgba.convert("RGB"), shadow_map)
    shaded = shaded_rgb.convert("RGBA")
    shaded.putalpha(design_rgba.getchannel("A"))
    return shaded


def composite_mockup(template_bytes: bytes, design_bytes: bytes | None, slot: str) -> bytes:
    """
    Returns PNG bytes of `template_bytes` with `design_bytes` composited
    into the print area for `slot`. If `slot` has no print area (currently
    "back") or design_bytes is None, the template is returned unchanged.
    """
    template = Image.open(BytesIO(template_bytes)).convert("RGBA")

    box_frac = PRINT_AREAS.get(slot)
    if box_frac is None or design_bytes is None:
        out = BytesIO()
        template.save(out, format="PNG")
        return out.getvalue()

    w, h = template.size
    left, top, right, bottom = box_frac
    box = (int(left * w), int(top * h), int(right * w), int(bottom * h))
    box_w, box_h = box[2] - box[0], box[3] - box[1]

    design = Image.open(BytesIO(design_bytes))
    design_rgba = _remove_background(design)

    # Fit the design into the box, preserving aspect ratio, centered.
    design_ratio = design_rgba.width / design_rgba.height
    box_ratio = box_w / box_h
    if design_ratio > box_ratio:
        fit_w, fit_h = box_w, int(box_w / design_ratio)
    else:
        fit_w, fit_h = int(box_h * design_ratio), box_h
    design_rgba = design_rgba.resize((max(fit_w, 1), max(fit_h, 1)), Image.LANCZOS)

    paste_x = box[0] + (box_w - fit_w) // 2
    paste_y = box[1] + (box_h - fit_h) // 2

    template_region = template.crop((paste_x, paste_y, paste_x + fit_w, paste_y + fit_h))
    shaded = _shade_onto_fabric(design_rgba, template_region)

    if slot == "side":
        # Mild shear to suggest the garment is turned, not flat to camera.
        shaded = shaded.transform(
            shaded.size, Image.AFFINE,
            (1, SIDE_SHEAR, -SIDE_SHEAR * shaded.height / 2, 0, 1, 0),
            resample=Image.BICUBIC,
        )

    template.alpha_composite(shaded, (paste_x, paste_y))

    out = BytesIO()
    template.convert("RGB").save(out, format="PNG")
    return out.getvalue()
