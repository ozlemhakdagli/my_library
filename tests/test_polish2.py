import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app

TODAY = date(2026, 10, 17)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "src" / "library" / "web" / "templates"
HX = {"HX-Request": "true"}
LONG_TITLE = "Aile Şirketleri, Değerler ve Kurumsallaşma Adımları"


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "polish2.db")
    conn = db.connect(path)
    db.init_schema(conn)
    db.add_book(conn, title=LONG_TITLE, author_names=["Yazar"])
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    app = create_app(
        Settings(port=8765, db_path=db_path, default_lang="en"),
        today_fn=lambda: TODAY,
    )
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def book_id(db_path):
    conn = db.connect(db_path)
    try:
        return conn.execute("SELECT id FROM book").fetchone()["id"]
    finally:
        conn.close()


def _reading_row(db_path, book_id):
    conn = db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, started_on, finished_on FROM reading_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


# 1. Long titles on covers must be allowed to break inside a word.


def test_cover_title_element_breaks_long_words():
    source = (TEMPLATES / "_cover.html").read_text(encoding="utf-8")
    match = re.search(r'class="([^"]*)"[^>]*>\s*\{\{ book\.title \}\}', source)
    assert match is not None, "cover title element not found"
    classes = match.group(1).split()
    assert "[overflow-wrap:anywhere]" in classes or "break-words" in classes


# 2. HTMX status posts return only the status fragment.


def test_htmx_status_post_returns_fragment_only(client, db_path, book_id):
    response = client.post(f"/books/{book_id}/status", data={"status": "reading"}, headers=HX)
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body
    assert f'id="status-{book_id}"' in body
    assert _reading_row(db_path, book_id)["status"] == "reading"


def test_htmx_fragment_has_strip_buttons_and_date_fields(client, book_id):
    response = client.post(f"/books/{book_id}/status", data={"status": "read"}, headers=HX)
    body = response.text
    assert body.count(f'hx-post="/books/{book_id}/status"') >= 4
    assert 'name="finished_on"' in body
    assert 'name="started_on"' in body


def test_htmx_invalid_date_returns_400_fragment(client, book_id):
    response = client.post(
        f"/books/{book_id}/status",
        data={"status": "read", "finished_on": "2099-01-01"},
        headers=HX,
    )
    assert response.status_code == 400
    assert "<html" not in response.text
    assert f'id="status-{book_id}"' in response.text


def test_htmx_unknown_book_returns_404(client):
    response = client.post("/books/999999/status", data={"status": "reading"}, headers=HX)
    assert response.status_code == 404


# 3. Plain form posts keep the old redirect behaviour.


def test_plain_status_post_still_redirects(client, db_path, book_id):
    response = client.post(f"/books/{book_id}/status", data={"status": "reading"})
    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{book_id}"
    assert _reading_row(db_path, book_id)["status"] == "reading"


def test_plain_invalid_date_still_400(client, book_id):
    response = client.post(
        f"/books/{book_id}/status",
        data={"status": "read", "finished_on": "2099-01-01"},
    )
    assert response.status_code == 400


def test_detail_page_status_buttons_use_htmx(client, book_id):
    response = client.get(f"/books/{book_id}")
    assert response.status_code == 200
    assert f'hx-post="/books/{book_id}/status"' in response.text
