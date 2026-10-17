import io
import re

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from library import db
from library.config import Settings
from library.web.app import create_app


def _image_bytes(fmt: str, size=(800, 1200), color=(160, 40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


JPEG = _image_bytes("JPEG")
PNG = _image_bytes("PNG")


@pytest.fixture
def paths(tmp_path):
    path = str(tmp_path / "cover_web.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    return {"db": path, "covers": str(tmp_path / "covers")}


@pytest.fixture
def seeded(paths):
    conn = db.connect(paths["db"])
    db.init_schema(conn)
    plain = db.add_book(conn, title="Plain Book", author_names=["Ali Veli"])
    tinted = db.add_book(conn, title="Tinted Book", author_names=["Ayşe Yılmaz"])
    conn.execute("UPDATE book SET cover_color = ? WHERE id = ?", ("#123456", tinted))
    conn.commit()
    conn.close()
    return {"plain": plain, "tinted": tinted}


def _client(paths, lang="en"):
    settings = Settings(
        port=8765,
        db_path=paths["db"],
        default_lang=lang,
        cover_dir=paths["covers"],
    )
    return TestClient(create_app(settings), follow_redirects=False)


def _book_count(paths) -> int:
    conn = db.connect(paths["db"])
    try:
        return conn.execute("SELECT COUNT(*) FROM book").fetchone()[0]
    finally:
        conn.close()


def _cover_row(paths, book_id):
    conn = db.connect(paths["db"])
    try:
        row = conn.execute(
            "SELECT cover_file, cover_color FROM book WHERE id = ?", (book_id,)
        ).fetchone()
        return tuple(row)
    finally:
        conn.close()


def _add_with_cover(client, content, content_type, filename="upload.bin", title="Cover Test"):
    return client.post(
        "/books/new",
        data={"title": title, "authors": "Yazar Bir"},
        files={"cover": (filename, content, content_type)},
    )


# --- config -------------------------------------------------------------


def test_cover_dir_defaults_and_reads_env(monkeypatch):
    monkeypatch.delenv("LIBRARY_COVER_DIR", raising=False)
    assert Settings.from_env().cover_dir == "/data/covers"
    monkeypatch.setenv("LIBRARY_COVER_DIR", "/tmp/elsewhere")
    assert Settings.from_env().cover_dir == "/tmp/elsewhere"


# --- db -----------------------------------------------------------------


def test_set_book_cover_writes_columns_and_history(paths, seeded):
    conn = db.connect(paths["db"])
    try:
        db.set_book_cover(conn, seeded["plain"], "%d.jpg" % seeded["plain"], "#abcdef")
        book = db.get_book(conn, seeded["plain"])
        assert book["cover_file"] == "%d.jpg" % seeded["plain"]
        assert book["cover_color"] == "#abcdef"
        history = [h for h in db.get_history(conn, seeded["plain"]) if h["field"] == "cover"]
        assert len(history) == 1
        assert history[0]["new_value"] == "%d.jpg" % seeded["plain"]
    finally:
        conn.close()


def test_card_extras_carry_cover_fields(paths, seeded):
    conn = db.connect(paths["db"])
    try:
        extras = db.book_card_extras(conn, [seeded["tinted"], seeded["plain"]])
        assert extras[seeded["tinted"]]["cover_color"] == "#123456"
        assert extras[seeded["tinted"]]["cover_file"] is None
        assert extras[seeded["plain"]]["cover_color"] is None
    finally:
        conn.close()


# --- add form -----------------------------------------------------------


def test_new_book_with_jpeg_is_served_as_jpeg(paths):
    client = _client(paths)
    response = _add_with_cover(client, JPEG, "image/jpeg", "photo.jpg")
    assert response.status_code == 303
    book_id = int(response.headers["location"].rsplit("/", 1)[1])

    served = client.get(f"/covers/{book_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"
    file_name, color = _cover_row(paths, book_id)
    assert file_name == f"{book_id}.jpg"
    assert re.fullmatch(r"#[0-9a-f]{6}", color)
    with Image.open(io.BytesIO(served.content)) as img:
        assert max(img.size) <= 600


def test_png_upload_is_accepted(paths):
    client = _client(paths)
    response = _add_with_cover(client, PNG, "image/png", "photo.png")
    assert response.status_code == 303


def test_invalid_cover_is_rejected_and_book_not_added(paths):
    client = _client(paths)
    before = _book_count(paths)
    response = _add_with_cover(client, b"just text, not an image", "text/plain", "notes.txt")
    assert response.status_code == 400
    assert _book_count(paths) == before


def test_gif_upload_is_rejected(paths):
    gif = io.BytesIO()
    Image.new("RGB", (10, 10), (1, 2, 3)).save(gif, format="GIF")
    client = _client(paths)
    before = _book_count(paths)
    response = _add_with_cover(client, gif.getvalue(), "image/gif", "a.gif")
    assert response.status_code == 400
    assert _book_count(paths) == before


def test_empty_file_field_adds_book_without_cover(paths):
    client = _client(paths)
    response = client.post(
        "/books/new",
        data={"title": "No Cover Yet"},
        files={"cover": ("", b"", "application/octet-stream")},
    )
    assert response.status_code == 303
    book_id = int(response.headers["location"].rsplit("/", 1)[1])
    assert _cover_row(paths, book_id)[0] is None
    assert client.get(f"/covers/{book_id}").status_code == 404


# --- replace cover ------------------------------------------------------


def test_replace_cover_writes_history_and_serves_new_image(paths, seeded):
    client = _client(paths)
    book_id = seeded["plain"]
    response = client.post(
        f"/books/{book_id}/cover", files={"cover": ("new.jpg", JPEG, "image/jpeg")}
    )
    assert response.status_code == 303
    assert _cover_row(paths, book_id)[0] == f"{book_id}.jpg"
    assert client.get(f"/covers/{book_id}").status_code == 200

    conn = db.connect(paths["db"])
    try:
        fields = [h["field"] for h in db.get_history(conn, book_id)]
    finally:
        conn.close()
    assert "cover" in fields


def test_replace_cover_with_invalid_file_is_400_and_keeps_old(paths, seeded):
    client = _client(paths)
    book_id = seeded["plain"]
    client.post(f"/books/{book_id}/cover", files={"cover": ("a.jpg", JPEG, "image/jpeg")})
    before = _cover_row(paths, book_id)
    response = client.post(
        f"/books/{book_id}/cover", files={"cover": ("a.txt", b"nope", "text/plain")}
    )
    assert response.status_code == 400
    assert _cover_row(paths, book_id) == before


def test_replace_cover_on_missing_book_is_404(paths):
    client = _client(paths)
    response = client.post("/books/999/cover", files={"cover": ("a.jpg", JPEG, "image/jpeg")})
    assert response.status_code == 404


# --- serving ------------------------------------------------------------


def test_book_without_cover_gives_404(paths, seeded):
    assert _client(paths).get(f"/covers/{seeded['plain']}").status_code == 404


def test_non_numeric_and_traversal_ids_give_404(paths, seeded):
    client = _client(paths)
    assert client.get("/covers/abc").status_code == 404
    assert client.get("/covers/%2E%2E").status_code == 404
    traversal = client.get("/covers/..%2Fsecret.jpg")
    assert traversal.status_code in (400, 404)
    assert traversal.status_code != 200


def test_cover_row_without_file_on_disk_gives_404(paths, seeded):
    conn = db.connect(paths["db"])
    db.set_book_cover(conn, seeded["plain"], "%d.jpg" % seeded["plain"], "#abcdef")
    conn.close()
    assert _client(paths).get(f"/covers/{seeded['plain']}").status_code == 404


# --- cards and pages ----------------------------------------------------


def test_card_shows_cover_image_with_alt_and_lazy_loading(paths):
    client = _client(paths)
    book_id = int(_add_with_cover(client, JPEG, "image/jpeg").headers["location"].rsplit("/", 1)[1])
    html = client.get("/").text
    assert f'<img src="/covers/{book_id}"' in html
    assert 'loading="lazy"' in html
    assert 'alt="Cover Test, Yazar Bir"' in html
    # Title and spine stay on top of the image.
    assert "Cover Test" in html
    assert "bg-ink/30" in html


def test_card_without_cover_file_has_no_image(paths, seeded):
    html = _client(paths).get("/").text
    assert f'<img src="/covers/{seeded["plain"]}"' not in html


def test_cover_color_is_used_when_no_cover_file(paths, seeded):
    html = _client(paths).get("/").text
    assert "--cover: #123456" in html


def test_detail_page_has_cover_change_form_in_turkish(paths, seeded):
    html = _client(paths, "tr").get(f"/books/{seeded['plain']}").text
    assert f'action="/books/{seeded["plain"]}/cover"' in html
    assert 'enctype="multipart/form-data"' in html
    assert "Kapak değiştir" in html


def test_add_form_has_cover_file_field(paths):
    html = _client(paths).get("/books/new").text
    assert 'type="file" name="cover" accept="image/*"' in html
    assert 'enctype="multipart/form-data"' in html


def test_edit_form_has_no_cover_field(paths, seeded):
    html = _client(paths).get(f"/books/{seeded['plain']}/edit").text
    assert 'name="cover"' not in html


def test_new_labels_in_both_languages(paths):
    en = _client(paths, "en").get("/books/new").text
    tr = _client(paths, "tr").get("/books/new").text
    assert "Cover photo" in en
    assert "Kapak fotoğrafı" in tr
