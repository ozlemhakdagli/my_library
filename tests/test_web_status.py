from datetime import date

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app

TODAY = date(2026, 10, 17)


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
        Settings(port=8765, db_path=db_path, default_lang="en"),
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


def _seed(db_path, book_id, **values):
    conn = db.connect(db_path)
    try:
        db.set_reading_status(conn, book_id, values.pop("status"), **values)
    finally:
        conn.close()


def _quick(client, book_id, action, **extra):
    return client.post(f"/books/{book_id}/status/quick", data={"action": action, **extra})


# Step 1 tests: quick buttons and date rules.


def test_mark_as_read_sets_finished_today(client, db_path, book_id):
    response = _quick(client, book_id, "read")
    assert response.status_code == 200
    row = _reading_row(db_path, book_id)
    assert row["status"] == "read"
    assert row["finished_on"] == "2026-10-17"


def test_mark_as_read_keeps_existing_started_on(client, db_path, book_id):
    _seed(db_path, book_id, status="reading", started_on="2026-10-01")
    _quick(client, book_id, "read")
    row = _reading_row(db_path, book_id)
    assert row["started_on"] == "2026-10-01"
    assert row["finished_on"] == "2026-10-17"


def test_start_reading_sets_started_today_when_empty(client, db_path, book_id):
    _quick(client, book_id, "reading")
    row = _reading_row(db_path, book_id)
    assert row["status"] == "reading"
    assert row["started_on"] == "2026-10-17"
    assert row["finished_on"] is None


def test_start_reading_after_finish_is_rejected_by_date_order(client, db_path, book_id):
    # Finished earlier than today, so today as the new started date is rejected.
    _seed(db_path, book_id, status="read", finished_on="2026-09-30")
    response = _quick(client, book_id, "reading")
    assert response.status_code == 400
    row = _reading_row(db_path, book_id)
    assert row["status"] == "read"
    assert row["started_on"] is None
    assert row["finished_on"] == "2026-09-30"


def test_abandon_keeps_dates(client, db_path, book_id):
    _seed(db_path, book_id, status="reading", started_on="2026-10-01")
    _quick(client, book_id, "abandon")
    row = _reading_row(db_path, book_id)
    assert row["status"] == "abandoned"
    assert row["started_on"] == "2026-10-01"
    assert row["finished_on"] is None


def test_invalid_action_is_400_and_changes_nothing(client, db_path, book_id):
    response = _quick(client, book_id, "delete")
    assert response.status_code == 400
    assert _reading_row(db_path, book_id) is None


def test_fragment_shows_badge_in_selected_language(client, book_id):
    en = client.post(
        f"/books/{book_id}/status/quick?lang=en", data={"action": "reading"}
    ).text
    tr = client.post(
        f"/books/{book_id}/status/quick?lang=tr", data={"action": "read"}
    ).text
    assert "Reading" in en
    assert "okundu" in tr


def test_htmx_and_plain_requests_return_same_fragment(client, book_id):
    plain = _quick(client, book_id, "reading").text
    htmx = client.post(
        f"/books/{book_id}/status/quick",
        data={"action": "reading"},
        headers={"HX-Request": "true"},
    ).text
    assert plain == htmx
    assert f'id="status-{book_id}"' in plain


def test_future_finished_date_rejected_by_db_and_db_unchanged(db_path, book_id):
    conn = db.connect(db_path)
    try:
        with pytest.raises(ValueError):
            db.set_reading_status(
                conn, book_id, "read", finished_on="2026-10-18", today=TODAY
            )
        assert conn.execute(
            "SELECT COUNT(*) FROM reading_status WHERE book_id = ?", (book_id,)
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_finished_before_started_rejected_by_db(db_path, book_id):
    conn = db.connect(db_path)
    try:
        db.set_reading_status(conn, book_id, "reading", started_on="2026-10-01", today=TODAY)
        with pytest.raises(ValueError):
            db.set_reading_status(
                conn, book_id, "read", finished_on="2026-09-01", today=TODAY
            )
    finally:
        conn.close()
    row = _reading_row(db_path, book_id)
    assert row["status"] == "reading"
    assert row["finished_on"] is None


def test_detail_form_future_date_is_400_and_unchanged(client, db_path, book_id):
    response = client.post(
        f"/books/{book_id}/status",
        data={"status": "read", "started_on": "", "finished_on": "2026-10-18"},
    )
    assert response.status_code == 400
    assert _reading_row(db_path, book_id) is None


def test_list_and_detail_pages_show_quick_buttons(client, book_id):
    detail = client.get(f"/books/{book_id}").text
    listing = client.get("/").text
    assert f"/books/{book_id}/status/quick" in detail
    assert f"/books/{book_id}/status/quick" in listing
