from datetime import date

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.covers import COVER_PALETTE, book_cover_color, cover_color
from library.web.app import create_app

RIBBON_MARK = "rounded-bl-md"


def test_cover_color_is_deterministic_and_in_palette():
    keys = [f"title {n}" for n in range(200)]
    for key in keys:
        color = cover_color(key)
        assert color in COVER_PALETTE
        assert cover_color(key) == color
    assert len(set(cover_color(key) for key in keys)) == len(COVER_PALETTE)


def test_same_title_gets_same_color():
    assert cover_color("Sapiens") == cover_color("Sapiens")


def test_shelf_color_overrides_title_color():
    assert book_cover_color("Sapiens", "Roman") == cover_color("shelf:Roman")
    assert book_cover_color("Başka", "Roman") == cover_color("shelf:Roman")
    assert book_cover_color("Sapiens", None) == cover_color("Sapiens")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "covers.db")
    conn = db.connect(path)
    db.init_schema(conn)
    read_id = db.add_book(conn, title="Kırmızı Kitap", author_names=["Ayşe Yılmaz"], publisher="Can Yayınları")
    db.set_reading_status(conn, read_id, "read", finished_on="2026-10-01", today=date(2026, 10, 17))
    unread_id = db.add_book(conn, title="Okunmamış Roman", author_names=["Ali Veli"])
    shelf_id = db.add_shelf(conn, "Roman")
    db.set_book_shelf(conn, unread_id, shelf_id)
    type_ids = [db.add_type(conn, name) for name in ("Sesli", "Ansiklopedi", "Çizgi roman")]
    db.set_book_types(conn, read_id, type_ids)
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


def _client(db_path, lang):
    return TestClient(create_app(Settings(port=8765, db_path=db_path, default_lang=lang)))


def test_card_shows_title_author_publisher_and_link(db_path, ids):
    html = _client(db_path, "en").get("/").text
    book_id = ids["Kırmızı Kitap"]
    assert f'href="/books/{book_id}"' in html
    assert "Kırmızı Kitap" in html
    assert "Ayşe Yılmaz" in html
    assert "Can Yayınları" in html
    assert 'aria-label="Kırmızı Kitap, Ayşe Yılmaz"' in html


def test_read_ribbon_with_date_in_english_and_turkish(db_path):
    en = _client(db_path, "en").get("/").text
    tr = _client(db_path, "tr").get("/").text
    assert "Read · 2026-10-01" in en
    assert "Okundu · 2026-10-01" in tr


def test_type_chips_cap_at_two_then_count(db_path):
    html = _client(db_path, "en").get("/").text
    html = html[html.index("<ul class=\"grid grid-cols-2"):]  # results only, not the filter sidebar
    assert "Ansiklopedi" in html
    assert "Çizgi roman" in html
    assert ">Sesli<" not in html
    assert "+1" in html


def test_unread_book_has_no_ribbon(db_path, ids):
    client = _client(db_path, "en")
    html = client.get("/", params={"q": "Okunmamış"}).text
    assert "Okunmamış Roman" in html
    assert RIBBON_MARK not in html


def test_shelf_color_is_used_on_card(db_path, ids):
    html = _client(db_path, "en").get("/", params={"q": "Okunmamış"}).text
    assert f"--cover: {cover_color('shelf:Roman')}" in html


def test_list_page_uses_responsive_grid(db_path):
    html = _client(db_path, "en").get("/").text
    assert "grid-cols-2" in html
    assert "sm:grid-cols-3" in html
    assert "xl:grid-cols-5" in html
