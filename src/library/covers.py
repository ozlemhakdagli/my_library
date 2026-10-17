"""Cover colours for book cards.

A book takes the colour of its shelf (klasör) when it has one. Otherwise its
colour comes from a stable hash of its title, so the same title always gets the
same cover. The palette has eight muted tones that keep light cover text readable.
"""

from __future__ import annotations

import hashlib

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
