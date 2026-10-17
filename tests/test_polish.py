import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.i18n import translate
from library.web.app import create_app

TODAY = date(2026, 10, 17)
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "library"
TEMPLATES = SRC / "web" / "templates"
HTMX = {"HX-Request": "true"}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = db.connect(path)
    db.init_schema(conn)
    db.add_book(conn, title="Sefiller", author_names=["Victor Hugo"])
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    app = create_app(
        Settings(port=8765, db_path=db_path, default_lang="tr"),
        today_fn=lambda: TODAY,
    )
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def book_id(db_path):
    conn = db.connect(db_path)
    try:
        return conn.execute("SELECT id FROM book WHERE title = 'Sefiller'").fetchone()["id"]
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


def _seed(db_path, book_id, status, **dates):
    conn = db.connect(db_path)
    try:
        db.set_reading_status(conn, book_id, status, today=TODAY, **dates)
    finally:
        conn.close()


# 1. "Okunmadı" filter counts books without a reading_status row.


def test_unread_filter_includes_books_without_status_row(db_path):
    conn = db.connect(db_path)
    try:
        db.add_book(conn, title="Satirsiz", author_names=["Yazar"])
        read_id = db.add_book(conn, title="Okunmus", author_names=["Yazar"])
        db.set_reading_status(conn, read_id, "read", today=TODAY)

        titles = [b["title"] for b in db.list_books(conn, status="unread", limit=1000)]
        assert "Satirsiz" in titles
        assert "Okunmus" not in titles
        assert db.count_books(conn, status="unread") == db.reading_counts(conn)["unread"]
        assert len(titles) == db.reading_counts(conn)["unread"]
    finally:
        conn.close()


# 2. Starting to read again begins a new reading round.


def test_restart_finished_book_clears_finished_and_sets_started_today(db_path, book_id):
    _seed(db_path, book_id, "reading", started_on="2026-01-01")
    _seed(db_path, book_id, "read", finished_on="2026-02-01")
    conn = db.connect(db_path)
    try:
        db.set_reading_status(conn, book_id, "reading", today=TODAY)
    finally:
        conn.close()
    row = _reading_row(db_path, book_id)
    assert row["status"] == "reading"
    assert row["finished_on"] is None
    assert row["started_on"] == "2026-10-17"
    conn = db.connect(db_path)
    try:
        old = conn.execute(
            "SELECT old_value FROM history WHERE record_id = ? AND field = 'finished_on' "
            "AND new_value IS NULL",
            (book_id,),
        ).fetchall()
    finally:
        conn.close()
    assert [r["old_value"] for r in old] == ["2026-02-01"]


def test_quick_start_reading_after_finish_is_200(client, db_path, book_id):
    _seed(db_path, book_id, "read", finished_on="2026-09-30")
    response = client.post(f"/books/{book_id}/status/quick", data={"action": "reading"})
    assert response.status_code == 200
    row = _reading_row(db_path, book_id)
    assert row["status"] == "reading"
    assert row["finished_on"] is None
    assert row["started_on"] == "2026-10-17"


def test_detail_form_reading_keeps_future_date_rule(client, db_path, book_id):
    response = client.post(
        f"/books/{book_id}/status",
        data={"status": "reading", "started_on": "2026-10-18", "finished_on": ""},
    )
    assert response.status_code == 400
    assert _reading_row(db_path, book_id) is None


def test_detail_form_read_keeps_finished_before_started_rule(client, db_path, book_id):
    response = client.post(
        f"/books/{book_id}/status",
        data={"status": "read", "started_on": "2026-10-01", "finished_on": "2026-09-01"},
    )
    assert response.status_code == 400
    assert _reading_row(db_path, book_id) is None


# 3. HTMX error responses are swapped so the user sees them.


def test_base_template_swaps_4xx_htmx_responses():
    text = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "htmx:beforeSwap" in text
    assert re.search(r"shouldSwap\s*=\s*true", text)
    assert re.search(r"isError\s*=\s*false", text)
    assert re.search(r"400.*409.*422|409.*422", text, re.S)


def test_htmx_invalid_quick_action_returns_error_fragment(client, db_path, book_id):
    response = client.post(
        f"/books/{book_id}/status/quick", data={"action": "delete"}, headers=HTMX
    )
    assert response.status_code == 400
    assert f'id="status-{book_id}"' in response.text
    assert "<html" not in response.text
    assert "HX-Refresh" not in response.headers


def test_htmx_invalid_shelf_returns_error_fragment(client, book_id):
    response = client.post(
        f"/books/{book_id}/shelf", data={"shelf_id": "abc"}, headers=HTMX
    )
    assert response.status_code == 400
    assert 'id="shelf-block"' in response.text
    assert "<html" not in response.text
    assert translate("tr", "err_invalid") in response.text


def test_htmx_invalid_types_returns_error_fragment(client, book_id):
    response = client.post(
        f"/books/{book_id}/types", data={"type_id": "abc"}, headers=HTMX
    )
    assert response.status_code == 400
    assert 'id="types-block"' in response.text
    assert "<html" not in response.text
    assert translate("tr", "err_invalid") in response.text


# 4. Changes made through HTMX refresh the book page, so the history table is current.


def test_htmx_shelf_change_refreshes_book_page(client, db_path, book_id):
    conn = db.connect(db_path)
    try:
        shelf_id = db.add_shelf(conn, "Roman")
    finally:
        conn.close()
    response = client.post(f"/books/{book_id}/shelf", data={"shelf_id": str(shelf_id)}, headers=HTMX)
    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") == "true"


def test_htmx_type_change_refreshes_book_page(client, db_path, book_id):
    conn = db.connect(db_path)
    try:
        type_id = db.add_type(conn, "Sesli")
    finally:
        conn.close()
    response = client.post(f"/books/{book_id}/types", data={"type_id": str(type_id)}, headers=HTMX)
    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") == "true"


def test_htmx_quick_status_refreshes_book_page(client, book_id):
    response = client.post(
        f"/books/{book_id}/status/quick", data={"action": "reading"}, headers=HTMX
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") == "true"


# 5. Turkish terminology: "Klasör" and "Tür", never "Raf".


def test_no_raf_term_in_source_or_templates():
    files = [*SRC.rglob("*.py"), *TEMPLATES.glob("*.html")]
    offenders = [
        str(path) for path in files if re.search(r"\bRaf", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_turkish_terms_for_shelf_and_type():
    assert translate("tr", "nav_shelves") == "Klasörler"
    assert translate("tr", "field_shelf") == "Klasör"
    assert translate("tr", "hf_type") == "Tür"
    assert translate("tr", "nav_types") == "Türler"
