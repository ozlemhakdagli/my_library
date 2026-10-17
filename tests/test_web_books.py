import sqlite3

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = db.connect(path)
    db.init_schema(conn)
    db.add_book(conn, title="yapay zeka", author_names=["Stuart Russell"], publisher="Pearson")
    db.add_book(conn, title="Lonely Book")
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    return TestClient(create_app(Settings(port=8765, db_path=db_path, default_lang="en")))


def book_id_by_title(db_path, title):
    conn = db.connect(db_path)
    try:
        row = conn.execute("SELECT id FROM book WHERE title = ?", (title,)).fetchone()
        return row["id"]
    finally:
        conn.close()


def load(db_path, book_id):
    conn = db.connect(db_path)
    try:
        return db.get_book(conn, book_id)
    finally:
        conn.close()


def count_rows(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def test_detail_shows_title_and_unknown_for_missing_author_and_publisher(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.get(f"/books/{book_id}")
    assert response.status_code == 200
    assert "Lonely Book" in response.text
    assert "unknown" in response.text


def test_detail_turkish_placeholder(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.get(f"/books/{book_id}", params={"lang": "tr"})
    assert "bilinmiyor" in response.text


def test_detail_missing_book_is_404(client):
    assert client.get("/books/999999").status_code == 404


def test_edit_form_is_prefilled(client, db_path):
    book_id = book_id_by_title(db_path, "yapay zeka")
    response = client.get(f"/books/{book_id}/edit")
    assert response.status_code == 200
    assert 'value="yapay zeka"' in response.text
    assert "Stuart Russell" in response.text


def test_edit_preview_shows_summary_and_saves_nothing(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.post(
        f"/books/{book_id}/edit",
        data={"title": "Changed Title", "action": "preview"},
    )
    assert response.status_code == 200
    assert "Changed Title" in response.text
    assert load(db_path, book_id)["title"] == "Lonely Book"


def test_edit_save_updates_book_and_redirects(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.post(
        f"/books/{book_id}/edit",
        data={"title": "New Title", "authors": "Ada Lovelace", "publisher": "Pearson"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{book_id}"

    detail = client.get(f"/books/{book_id}")
    assert "New Title" in detail.text
    saved = load(db_path, book_id)
    assert saved["title"] == "New Title"
    assert saved["authors"] == ["Ada Lovelace"]
    assert saved["publisher"] == "Pearson"


def test_edit_empty_title_is_422_and_db_unchanged(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.post(f"/books/{book_id}/edit", data={"title": "   "})
    assert response.status_code == 422
    assert load(db_path, book_id)["title"] == "Lonely Book"


def test_edit_title_over_300_chars_is_422_and_db_unchanged(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.post(f"/books/{book_id}/edit", data={"title": "x" * 301})
    assert response.status_code == 422
    assert load(db_path, book_id)["title"] == "Lonely Book"


def test_add_form_renders(client):
    response = client.get("/books/new")
    assert response.status_code == 200
    assert "<form" in response.text


def test_add_creates_book(client, db_path):
    response = client.post(
        "/books/new",
        data={"title": "Fresh Book", "authors": "A Author; B Author"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    book_id = book_id_by_title(db_path, "Fresh Book")
    assert response.headers["location"] == f"/books/{book_id}"
    assert load(db_path, book_id)["authors"] == ["A Author", "B Author"]


def test_add_empty_title_is_422_and_creates_nothing(client, db_path):
    before = count_rows(db_path, "SELECT COUNT(*) FROM book")
    response = client.post("/books/new", data={"title": ""})
    assert response.status_code == 422
    assert count_rows(db_path, "SELECT COUNT(*) FROM book") == before


def test_delete_is_soft_and_hides_book_from_list(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.post(f"/books/{book_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "Lonely Book" not in client.get("/").text
    assert count_rows(db_path, "SELECT COUNT(*) FROM book WHERE id = ?", (book_id,)) == 1
    assert (
        count_rows(
            db_path,
            "SELECT COUNT(*) FROM history WHERE record_id = ? AND field = 'deleted_at'",
            (book_id,),
        )
        == 1
    )


def test_delete_requires_post(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    assert client.get(f"/books/{book_id}/delete").status_code == 405
    assert load(db_path, book_id) is not None


def test_status_invalid_value_is_400(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.post(f"/books/{book_id}/status", data={"status": "lost"})
    assert response.status_code == 400
    assert load(db_path, book_id)["status"] is None


def test_status_valid_value_is_saved(client, db_path):
    book_id = book_id_by_title(db_path, "Lonely Book")
    response = client.post(
        f"/books/{book_id}/status", data={"status": "read"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert load(db_path, book_id)["status"] == "read"
