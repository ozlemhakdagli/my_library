import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app

WEB = Path(__file__).resolve().parent.parent / "src" / "library" / "web"


@pytest.fixture
def seeded(tmp_path):
    """Live books with known statuses, plus one soft-deleted read book and an open loan on it."""
    path = str(tmp_path / "reading.db")
    conn = db.connect(path)
    db.init_schema(conn)

    read_2024_a = db.add_book(conn, title="Okunan Bir")
    read_2024_b = db.add_book(conn, title="Okunan Iki")
    read_2025 = db.add_book(conn, title="Okunan Uc")
    reading = db.add_book(conn, title="Suren Kitap")
    abandoned = db.add_book(conn, title="Birakilan")
    unread = db.add_book(conn, title="Hic Baslanmamis")
    deleted = db.add_book(conn, title="Silinen Kitap")

    db.set_reading_status(conn, read_2024_a, "read", "2024-01-05", "2024-03-01")
    db.set_reading_status(conn, read_2024_b, "read", "2024-10-01", "2024-11-20")
    db.set_reading_status(conn, read_2025, "read", "2025-04-01", "2025-05-02")
    db.set_reading_status(conn, reading, "reading", "2026-01-05")
    db.set_reading_status(conn, abandoned, "abandoned")
    # `unread` has no status row at all.
    db.set_reading_status(conn, deleted, "read", "2025-05-01", "2025-06-01")

    db.lend_book(conn, read_2024_a, "Ayse Yilmaz", "2026-01-02")
    db.lend_book(conn, deleted, "Mehmet Kaya", "2026-01-03")
    db.soft_delete_book(conn, deleted)
    conn.close()
    return path


@pytest.fixture
def client(seeded):
    app = create_app(Settings(port=8765, db_path=seeded, default_lang="en"))
    return TestClient(app, follow_redirects=False)


def test_reading_counts_match_seeded_statuses(seeded):
    conn = db.connect(seeded)
    try:
        counts = db.reading_counts(conn)
    finally:
        conn.close()
    # Soft-deleted book is excluded; a book without a status row counts as unread.
    assert counts == {"unread": 1, "reading": 1, "read": 3, "abandoned": 1}


def test_finished_per_year_groups_by_finished_on_year(seeded):
    conn = db.connect(seeded)
    try:
        years = db.finished_per_year(conn)
    finally:
        conn.close()
    assert years == [(2024, 2), (2025, 1)]


def test_reading_page_shows_counts_and_years(client):
    response = client.get("/reading")
    assert response.status_code == 200
    # /reading was migrated to the editorial redesign (2026-10-28): "section", not the
    # old boxed-card layout.
    assert "section" in response.text
    assert "Reading" in response.text
    assert "2024" in response.text
    assert "Finished per year" in response.text


def test_reading_page_is_translated(client):
    response = client.get("/reading?lang=tr")
    assert response.status_code == 200
    assert "Yıllara göre bitirilen kitaplar" in response.text
    assert "Duruma göre kitaplar" in response.text


def test_reading_page_empty_years_message(tmp_path):
    path = str(tmp_path / "empty.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    client = TestClient(create_app(Settings(port=8765, db_path=path, default_lang="en")))
    response = client.get("/reading")
    assert response.status_code == 200
    assert "No finished books yet." in response.text


@pytest.mark.parametrize("path", ["/loans", "/review", "/settings"])
def test_secondary_pages_use_new_layout(client, path):
    # All three were migrated to the editorial redesign (2026-10-28): .section/.panel
    # replaced the old boxed-card layout.
    response = client.get(path)
    assert response.status_code == 200
    assert "section" in response.text


def test_loans_hide_deleted_books(client):
    response = client.get("/loans")
    assert response.status_code == 200
    assert "Ayse Yilmaz" in response.text
    assert "Mehmet Kaya" not in response.text
    assert "Silinen Kitap" not in response.text


def test_nav_has_all_sections(client):
    response = client.get("/")
    for label in ("Books", "Reading", "Shelves", "Types", "Loans", "Review", "Settings"):
        assert f">{label}</a>" in response.text


def test_app_has_no_raw_sql():
    source = (WEB / "app.py").read_text(encoding="utf-8")
    assert re.search(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", source) is None
    assert "conn.execute" not in source


def test_style_css_removed_and_base_loads_only_app_css():
    assert not (WEB / "static" / "style.css").exists()
    base = (WEB / "templates" / "base.html").read_text(encoding="utf-8")
    assert "/static/app.css" in base
    assert "style.css" not in base
