import io
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from library import db, ocr
from library.config import Settings
from library.web.app import create_app


# suggest_title_author -------------------------------------------------------


def test_single_title_line():
    assert ocr.suggest_title_author("Suç ve Ceza") == ("Suç ve Ceza", "")


def test_title_and_author_lines():
    assert ocr.suggest_title_author("1984\nGEORGE ORWELL\nCan") == ("1984", "GEORGE ORWELL")


def test_title_case_author_when_no_capitals():
    text = "Yüzyıl Yalnızlığı\nGabriel García Márquez\nSayfa 12"
    assert ocr.suggest_title_author(text) == ("Yüzyıl Yalnızlığı", "Gabriel García Márquez")


def test_digit_only_lines_give_no_suggestion():
    assert ocr.suggest_title_author("12\n345 6\n--\n7") == ("", "")


def test_empty_text_gives_no_suggestion():
    assert ocr.suggest_title_author("") == ("", "")
    assert ocr.suggest_title_author("  \n\n   \n") == ("", "")


def test_whitespace_is_cleaned():
    text = "  Suç   ve\tCeza  \n  FYODOR    DOSTOYEVSKİ \n"
    assert ocr.suggest_title_author(text) == ("Suç ve Ceza", "FYODOR DOSTOYEVSKİ")


def test_all_caps_title_with_all_caps_author():
    text = "SUÇ VE CEZA\nFYODOR DOSTOYEVSKİ"
    assert ocr.suggest_title_author(text) == ("SUÇ VE CEZA", "FYODOR DOSTOYEVSKİ")


# ocr_text -------------------------------------------------------------------


def test_ocr_text_empty_when_tesseract_missing(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("tesseract")

    monkeypatch.setattr(ocr.subprocess, "run", missing)
    assert ocr.ocr_text(b"not really an image") == ""


def test_ocr_text_empty_on_tesseract_failure(monkeypatch):
    def failing(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(ocr.subprocess, "run", failing)
    assert ocr.ocr_text(b"x") == ""


def test_ocr_text_passes_image_on_stdin(monkeypatch):
    calls = []

    def fake(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="1984\n".encode(), stderr=b"")

    monkeypatch.setattr(ocr.subprocess, "run", fake)
    assert ocr.ocr_text(b"IMG", languages="tur+eng") == "1984\n"
    args, kwargs = calls[0]
    assert args[:3] == ["tesseract", "stdin", "stdout"]
    assert args[args.index("-l") + 1] == "tur+eng"
    assert args[args.index("--psm") + 1] == "6"
    assert kwargs["input"] == b"IMG"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract is not installed")
def test_ocr_text_reads_rendered_text():
    font = ImageFont.load_default(size=64)
    img = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(img).text((30, 60), "GEORGE ORWELL", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert "ORWELL" in ocr.ocr_text(buf.getvalue()).upper()


# POST /books/ocr ------------------------------------------------------------


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), (160, 40, 40)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def paths(tmp_path):
    path = str(tmp_path / "ocr.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    return {"db": path, "covers": str(tmp_path / "covers")}


def _client(paths):
    settings = Settings(port=8765, db_path=paths["db"], default_lang="en", cover_dir=paths["covers"])
    return TestClient(create_app(settings), follow_redirects=False)


def _book_count(paths) -> int:
    conn = db.connect(paths["db"])
    try:
        return conn.execute("SELECT COUNT(*) FROM book").fetchone()[0]
    finally:
        conn.close()


def _field_value(html: str, name: str) -> str:
    marker = f'name="{name}"'
    start = html.index(marker)
    value_start = html.index('value="', start) + len('value="')
    return html[value_start : html.index('"', value_start)]


def test_ocr_rejects_invalid_cover_with_400(paths):
    client = _client(paths)
    response = client.post(
        "/books/ocr",
        files={"cover": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert _book_count(paths) == 0


def test_ocr_without_cover_is_400(paths):
    response = _client(paths).post("/books/ocr", data={"title": "x"})
    assert response.status_code == 400


def test_ocr_fills_form_with_suggestions_and_saves_nothing(paths, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_text", lambda image, languages="tur+eng": "1984\nGEORGE ORWELL\nCan")
    client = _client(paths)
    before = _book_count(paths)

    response = client.post(
        "/books/ocr",
        files={"cover": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
        data={"title": "", "authors": ""},
    )

    assert response.status_code == 200
    html = response.text
    assert _field_value(html, "title") == "1984"
    assert _field_value(html, "authors") == "GEORGE ORWELL"
    assert "Suggested from the cover photo" in html
    assert _book_count(paths) == before


def test_ocr_keeps_typed_values_when_no_suggestion(paths, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_text", lambda image, languages="tur+eng": "")
    response = _client(paths).post(
        "/books/ocr",
        files={"cover": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
        data={"title": "Elle Yazılan", "authors": "Ali Veli"},
    )
    assert response.status_code == 200
    assert _field_value(response.text, "title") == "Elle Yazılan"
    assert _field_value(response.text, "authors") == "Ali Veli"
    assert _book_count(paths) == 0


def test_add_form_marks_multipart_fill_button(paths):
    response = _client(paths).get("/books/new")
    assert response.status_code == 200
    assert 'hx-post="/books/ocr"' in response.text
    assert 'hx-encoding="multipart/form-data"' in response.text
    assert 'id="book-fields"' in response.text
