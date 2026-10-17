import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app

WEB = Path(__file__).resolve().parent.parent / "src" / "library" / "web"
TEMPLATES = WEB / "templates"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "detail.db")
    conn = db.connect(path)
    db.init_schema(conn)
    book_id = db.add_book(conn, title="Kırmızı Kitap", author_names=["Ayşe Yılmaz"], publisher="Can Yayınları")
    other_id = db.add_book(conn, title="Okunmamış Roman", author_names=["Ali Veli"])
    shelf_id = db.add_shelf(conn, "Roman")
    db.set_book_shelf(conn, book_id, shelf_id)
    db.set_book_types(conn, book_id, [db.add_type(conn, "Sesli")])
    db.set_reading_status(conn, book_id, "read", finished_on="2026-10-01", today=date(2026, 10, 17))
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def ids(db_path):
    conn = db.connect(db_path)
    try:
        rows = conn.execute("SELECT id, title FROM book ORDER BY id").fetchall()
        return {row["title"]: row["id"] for row in rows}
    finally:
        conn.close()


def _client(db_path, lang="en"):
    return TestClient(create_app(Settings(port=8765, db_path=db_path, default_lang=lang)))


def _set_status(db_path, book_id, status):
    conn = db.connect(db_path)
    try:
        db.set_reading_status(conn, book_id, status, today=date(2026, 10, 17))
        conn.commit()
    finally:
        conn.close()


def test_detail_cover_has_title_and_author_label(db_path, ids):
    html = _client(db_path).get(f"/books/{ids['Kırmızı Kitap']}").text
    assert 'role="img" aria-label="Kırmızı Kitap, Ayşe Yılmaz"' in html


def test_detail_segmented_control_has_four_options_and_pressed_state(db_path, ids):
    book_id = ids["Kırmızı Kitap"]
    html = _client(db_path).get(f"/books/{book_id}").text
    assert f'action="/books/{book_id}/status"' in html
    for value in ("unread", "reading", "read", "abandoned"):
        assert f'name="status" value="{value}"' in html
    assert len(re.findall(r'name="status" value="[a-z]+" aria-pressed="', html)) == 4
    assert re.search(r'value="read" aria-pressed="true"', html)
    assert re.search(r'value="unread" aria-pressed="false"', html)


def test_finished_date_field_shown_only_when_read(db_path, ids):
    book_id = ids["Kırmızı Kitap"]
    client = _client(db_path)
    assert 'name="finished_on"' in client.get(f"/books/{book_id}").text

    _set_status(db_path, book_id, "reading")
    html = client.get(f"/books/{book_id}").text
    assert 'name="started_on"' in html
    assert 'name="finished_on"' not in html

    _set_status(db_path, book_id, "abandoned")
    html = client.get(f"/books/{book_id}").text
    assert 'name="started_on"' not in html
    assert 'name="finished_on"' not in html


def test_detail_status_control_posts_to_status_endpoint_only(db_path, ids):
    book_id = ids["Okunmamış Roman"]
    html = _client(db_path).get(f"/books/{book_id}").text
    assert f'action="/books/{book_id}/status"' in html
    assert "/status/quick" not in html
    # The status badge is gone; the segmented control already shows the state.
    assert "rounded-full bg-surface px-2 py-0.5 text-xs text-ink" not in html


def test_detail_edit_and_delete_buttons(db_path, ids):
    book_id = ids["Kırmızı Kitap"]
    html = _client(db_path).get(f"/books/{book_id}").text
    assert f'href="/books/{book_id}/edit' in html
    assert f'action="/books/{book_id}/delete"' in html
    assert "confirm(" in html


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_secondary_pages_return_200_with_serif_title(db_path, lang):
    client = _client(db_path, lang)
    for path in ("/loans", "/review", "/shelves", "/types", "/reading", "/settings", "/books/new"):
        response = client.get(path, params={"lang": lang})
        assert response.status_code == 200, path
        assert re.search(r'<h1 class="font-serif"', response.text), path


def test_templates_have_no_hardcoded_hex_colours_except_documented_cover_ink():
    # The cover text colour lives in tailwind.input.css as a documented token,
    # so no template should contain a hex colour at all.
    offenders = []
    for template in TEMPLATES.rglob("*.html"):
        for match in HEX.finditer(template.read_text(encoding="utf-8")):
            offenders.append(f"{template.name}: {match.group(0)}")
    assert offenders == []


def test_cover_ink_token_is_documented_in_css():
    css = (WEB / "static" / "tailwind.input.css").read_text(encoding="utf-8")
    assert "--cover-ink: #faf6ee;" in css
    assert "Fixed on purpose" in css
