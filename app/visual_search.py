"""
Visual search: "upload a photo, find the most similar designs in the
catalog." Deliberately NOT built on an Azure embeddings API - the Vision
resource already wired up for this project (see vision_routes.py) only
does tags/captions/OCR, not image vectors, and Azure's actual image-vector
feature (Image Retrieval) is region-limited and untested here. Given how
many live-deploy debugging cycles region/API-version mismatches have
already cost this project, this uses a perceptual hash instead: pure
Pillow, no external model, no Azure call, works identically in this
sandbox and in production, same every time.

What it actually captures: structural/layout and color-gradient
similarity (shapes, composition, broad color changes), not deep semantic
meaning ("skull" vs "flower"). For a small catalog of flat graphic T-shirt
designs - which tend to differ a lot in composition and palette even when
the subject matter differs - that's a reasonable, honest stand-in for
"finds similar designs," not a claim of full semantic image understanding.
"""
from io import BytesIO

from PIL import Image

HASH_SIZE = 16  # 16x16 -> 256-bit hash; enough resolution for flat graphics


def compute_hash(image_bytes: bytes) -> str:
    """
    A 'difference hash' (dhash): shrink to a small grayscale grid, then for
    each row record whether each pixel is brighter than its neighbor to the
    right. The resulting bit pattern is stable under resizing/recompression
    and changes smoothly as the image's structure changes - two visually
    similar images produce hashes that differ in only a few bits.
    """
    img = Image.open(BytesIO(image_bytes)).convert("L").resize(
        (HASH_SIZE + 1, HASH_SIZE), Image.LANCZOS
    )
    pixels = list(img.getdata())
    bits = []
    for row in range(HASH_SIZE):
        offset = row * (HASH_SIZE + 1)
        for col in range(HASH_SIZE):
            bits.append(1 if pixels[offset + col] > pixels[offset + col + 1] else 0)
    # Pack bits into a hex string for compact storage.
    value = int("".join(str(b) for b in bits), 2)
    return format(value, f"0{HASH_SIZE * HASH_SIZE // 4}x")


def similarity(hash_a: str, hash_b: str) -> float:
    """Returns 0..1, where 1 is pixel-identical after the hash's downsampling."""
    if not hash_a or not hash_b:
        return 0.0
    int_a, int_b = int(hash_a, 16), int(hash_b, 16)
    hamming = bin(int_a ^ int_b).count("1")
    total_bits = HASH_SIZE * HASH_SIZE
    return 1 - (hamming / total_bits)
