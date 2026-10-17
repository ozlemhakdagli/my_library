import io
import os

import pytest
from PIL import Image

from library import covers

MAX_UPLOAD = 10 * 1024 * 1024


def _image_bytes(fmt, size=(800, 400), color=(0x2A, 0x6F, 0x4E)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def _channel_diff(hex_a, hex_b):
    a = [int(hex_a[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i : i + 2], 16) for i in (1, 3, 5)]
    return max(abs(x - y) for x, y in zip(a, b))


def test_dominant_color_of_solid_image_is_close_to_its_color():
    color = covers.dominant_color(Image.new("RGB", (200, 120), (0x2A, 0x6F, 0x4E)))

    assert color.startswith("#") and color == color.lower() and len(color) == 7
    assert _channel_diff(color, "#2a6f4e") <= 24


def test_dominant_color_falls_back_when_only_white_or_black():
    assert covers.dominant_color(Image.new("RGB", (64, 64), (255, 255, 255))) == "#4a3f6b"
    assert covers.dominant_color(Image.new("RGB", (64, 64), (0, 0, 0))) == "#4a3f6b"


def test_save_cover_writes_jpeg_named_by_book_id(tmp_path):
    cover_dir = tmp_path / "covers"

    file_name, color = covers.save_cover(_image_bytes("PNG"), 12, str(cover_dir))

    assert file_name == "12.jpg"
    assert (cover_dir / "12.jpg").is_file()
    assert _channel_diff(color, "#2a6f4e") <= 24
    with Image.open(cover_dir / "12.jpg") as stored:
        assert stored.format == "JPEG"
        assert max(stored.size) <= 600
        assert max(stored.size) == 600


def test_save_cover_accepts_jpeg_png_webp(tmp_path):
    for fmt in ("JPEG", "PNG", "WEBP"):
        file_name, _ = covers.save_cover(_image_bytes(fmt), 1, str(tmp_path))
        assert file_name == "1.jpg"


def test_save_cover_rejects_invalid_bytes(tmp_path):
    with pytest.raises(ValueError):
        covers.save_cover(b"not an image at all", 1, str(tmp_path))
    assert not (tmp_path / "1.jpg").exists()


def test_save_cover_rejects_other_image_types(tmp_path):
    with pytest.raises(ValueError):
        covers.save_cover(_image_bytes("GIF"), 1, str(tmp_path))


def test_save_cover_rejects_over_10_mb(tmp_path):
    with pytest.raises(ValueError):
        covers.save_cover(b"\0" * (MAX_UPLOAD + 1), 1, str(tmp_path))


def test_save_cover_creates_missing_directory(tmp_path):
    cover_dir = tmp_path / "a" / "b"

    covers.save_cover(_image_bytes("JPEG"), 3, str(cover_dir))

    assert (cover_dir / "3.jpg").is_file()


def test_cover_path_returns_path_for_plain_file_name(tmp_path):
    assert covers.cover_path(str(tmp_path), "12.jpg") == os.path.join(str(tmp_path), "12.jpg")


@pytest.mark.parametrize("name", ["../x.jpg", "a/b.jpg", "/etc/passwd", "..\\x.jpg", "", ".."])
def test_cover_path_rejects_path_components(tmp_path, name):
    with pytest.raises(ValueError):
        covers.cover_path(str(tmp_path), name)
