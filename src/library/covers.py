"""Cover colours for book cards.

A book takes the colour of its shelf (klasör) when it has one. Otherwise its
colour comes from a stable hash of its title, so the same title always gets the
same cover. The palette has eight muted tones that keep light cover text readable.
"""

from __future__ import annotations

import hashlib
import io
import os

from PIL import Image, ImageOps

COVER_PALETTE: tuple[str, ...] = (
    "#5b2e2a",
    "#2f4a3f",
    "#2c3e5c",
    "#6b4f2a",
    "#4a3f6b",
    "#3d5a5a",
    "#7a3b4e",
    "#4f5a2a",
)


def cover_color(key: str) -> str:
    """Return the palette colour for ``key``. Stable across runs and processes."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return COVER_PALETTE[int.from_bytes(digest[:4], "big") % len(COVER_PALETTE)]


def book_cover_color(title: str, shelf: str | None) -> str:
    """Cover colour of a book: its shelf's colour when it has a shelf, else its title's.

    ``shelf`` is the shelf name (shelf names are unique among live shelves).
    """
    if shelf:
        return cover_color(f"shelf:{shelf}")
    return cover_color(title)


# Cover photos. Files are always stored as "<book_id>.jpg" under the cover directory;
# the client's file name is never used on disk.

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SIDE = 600
JPEG_QUALITY = 85
PHOTO_FALLBACK_COLOR = "#4a3f6b"
_ACCEPTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
_PALETTE_SIZE = 5
_SAMPLE_SIDE = 64


def _open_cover(image_bytes: bytes) -> Image.Image:
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("cover image is larger than 10 MB")
    try:
        img = Image.open(io.BytesIO(image_bytes))
        fmt = img.format
        img.load()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("cover is not a readable image") from exc
    if fmt not in _ACCEPTED_FORMATS:
        raise ValueError(f"unsupported cover image type: {fmt}")
    return img


def dominant_color(img: Image.Image) -> str:
    """Most frequent color that is neither near-white nor near-black, as lowercase hex."""
    sample = img.convert("RGB")
    sample.thumbnail((_SAMPLE_SIDE, _SAMPLE_SIDE))
    quantized = sample.quantize(
        colors=_PALETTE_SIZE, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    palette = quantized.getpalette() or []
    for _count, index in sorted(quantized.getcolors() or [], reverse=True):
        rgb = tuple(palette[index * 3 : index * 3 + 3])
        if len(rgb) == 3 and min(rgb) < 235 and max(rgb) > 25:
            return "#{:02x}{:02x}{:02x}".format(*rgb)
    return PHOTO_FALLBACK_COLOR


def cover_path(cover_dir: str, file_name: str) -> str:
    """Path of a stored cover. Accepts a bare file name only."""
    if (
        not file_name
        or file_name in (".", "..")
        or "/" in file_name
        or "\\" in file_name
        or os.path.basename(file_name) != file_name
    ):
        raise ValueError(f"invalid cover file name: {file_name!r}")
    return os.path.join(cover_dir, file_name)


def save_cover(image_bytes: bytes, book_id: int, cover_dir: str) -> tuple[str, str]:
    """Validate, resize and store an uploaded cover.

    Returns (file_name, hex color). Raises ValueError for an unsupported, unreadable or
    oversized upload; nothing is written in that case.
    """
    img = ImageOps.exif_transpose(_open_cover(image_bytes)).convert("RGB")
    color = dominant_color(img)
    img.thumbnail((MAX_SIDE, MAX_SIDE))

    file_name = f"{book_id}.jpg"
    path = cover_path(cover_dir, file_name)
    os.makedirs(cover_dir, exist_ok=True)
    img.save(path, format="JPEG", quality=JPEG_QUALITY)
    return file_name, color
