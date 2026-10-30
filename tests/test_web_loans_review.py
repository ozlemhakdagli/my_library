import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.importer import import_raw
from library.web.app import create_app

REAL_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = db.connect(path)
    db.init_schema(conn)
    db.add_book(conn, title="Sefiller", author_names=["Victor Hugo"])
    db.add_book(conn, title="Needs Check", review_status="needs review")
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    app = create_app(Settings(port=8765, db_path=db_path, default_lang="en"))
    return TestClient(app, follow_redirects=False)


def _book_id(db_path, title):
    conn = db.connect(db_path)
    try:
        return conn.execute("SELECT id FROM book WHERE title = ?", (title,)).fetchone()["id"]
    finally:
        conn.close()


def _count(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def _add_unreadable(db_path, photo):
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO review_item (book_id, reason, photo_file) VALUES (NULL, 'unreadable', ?)",
            (photo,),
        )
        conn.commit()
    finally:
        conn.close()


def _review_item_id(db_path, book_id):
    conn = db.connect(db_path)
    try:
        return conn.execute(
            "SELECT id FROM review_item WHERE book_id = ?", (book_id,)
        ).fetchone()["id"]
    finally:
        conn.close()


def _open_loan_id(db_path, book_id):
    conn = db.connect(db_path)
    try:
        return db.open_loans(conn)[0]["loan_id"]
    finally:
        conn.close()


def test_lend_then_book_is_listed_and_return_removes_it(client, db_path):
    book_id = _book_id(db_path, "Sefiller")
    response = client.post(
        "/loans",
        data={"book_id": book_id, "borrower": "Ayşe", "lent_on": "2026-10-01"},
    )
    assert response.status_code == 303
    listing = client.get("/loans")
    assert listing.status_code == 200
    assert "Sefiller" in listing.text
    assert "Ayşe" in listing.text

    loan_id = _open_loan_id(db_path, book_id)
    response = client.post(f"/loans/{loan_id}/return", data={"returned_on": "2026-10-10"})
    assert response.status_code == 303
    listing = client.get("/loans")
    assert "Ayşe" not in listing.text
    assert "No books are out." in listing.text


def test_lending_twice_returns_409_and_writes_no_second_loan(client, db_path):
    book_id = _book_id(db_path, "Sefiller")
    data = {"book_id": book_id, "borrower": "Ayşe", "lent_on": "2026-10-01"}
    assert client.post("/loans", data=data).status_code == 303

    response = client.post("/loans", data={**data, "borrower": "Mehmet"})
    assert response.status_code == 409
    assert "already on loan" in response.text
    assert _count(db_path, "SELECT COUNT(*) FROM loan WHERE book_id = ?", (book_id,)) == 1


def test_returning_twice_returns_409(client, db_path):
    book_id = _book_id(db_path, "Sefiller")
    client.post("/loans", data={"book_id": book_id, "borrower": "Ayşe", "lent_on": "2026-10-01"})
    loan_id = _open_loan_id(db_path, book_id)
    assert client.post(f"/loans/{loan_id}/return", data={"returned_on": "2026-10-05"}).status_code == 303

    response = client.post(f"/loans/{loan_id}/return", data={"returned_on": "2026-10-06"})
    assert response.status_code == 409
    assert _count(db_path, "SELECT returned_on FROM loan WHERE id = ?", (loan_id,)) == "2026-10-05"


def test_unreadable_review_item_has_no_correct_button(client, db_path):
    _add_unreadable(db_path, "IMG_9999.jpg")
    book_id = _book_id(db_path, "Needs Check")
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO review_item (book_id, reason, photo_file) VALUES (?, 'author missing', NULL)",
            (book_id,),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/review")
    assert response.status_code == 200
    assert "[unreadable]" in response.text
    assert "IMG_9999.jpg" in response.text
    # Only the book-linked item gets a link to its edit page.
    assert response.text.count(f"/books/{book_id}/edit") == 1
    assert response.text.count("/edit") == 1


def test_not_a_book_closes_item_but_keeps_book_and_history(client, db_path):
    book_id = _book_id(db_path, "Needs Check")
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO review_item (book_id, reason, photo_file) VALUES (?, 'low confidence', NULL)",
            (book_id,),
        )
        conn.commit()
    finally:
        conn.close()
    item_id = _review_item_id(db_path, book_id)

    response = client.post(f"/review/{item_id}", data={"action": "not_a_book"})
    assert response.status_code == 303
    assert f'data-review-id="{item_id}"' not in client.get("/review").text

    conn = db.connect(db_path)
    try:
        book = db.get_book(conn, book_id)
        assert book is not None
        assert book["title"] == "Needs Check"
        history = db.get_history(conn, book_id)
        assert any(h["field"] == "review_resolution" and h["new_value"] == "not_a_book" for h in history)
    finally:
        conn.close()
    assert _count(db_path, "SELECT COUNT(*) FROM review_item WHERE id = ?", (item_id,)) == 1


def test_confirm_sets_book_review_status_ok(client, db_path):
    book_id = _book_id(db_path, "Needs Check")
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO review_item (book_id, reason, photo_file) VALUES (?, 'low confidence', NULL)",
            (book_id,),
        )
        conn.commit()
    finally:
        conn.close()
    item_id = _review_item_id(db_path, book_id)

    assert client.post(f"/review/{item_id}", data={"action": "confirm"}).status_code == 303
    conn = db.connect(db_path)
    try:
        assert db.get_book(conn, book_id)["review_status"] == "ok"
    finally:
        conn.close()


def test_invalid_review_action_is_rejected(client, db_path):
    _add_unreadable(db_path, "IMG_1.jpg")
    item_id = _count(db_path, "SELECT id FROM review_item LIMIT 1")
    response = client.post(f"/review/{item_id}", data={"action": "delete"})
    assert response.status_code == 400
    assert _count(db_path, "SELECT COUNT(*) FROM review_item WHERE resolved_at IS NULL") == 1


def test_review_list_turkish_labels(client, db_path):
    _add_unreadable(db_path, "IMG_2.jpg")
    response = client.get("/review?lang=tr")
    assert "[okunamadı]" in response.text
    assert "İnceleme kuyruğu" in response.text


@pytest.mark.skipif(not any(REAL_RAW.glob("*.jsonl")), reason="data/raw has no export files")
def test_real_data_review_queue_has_78_items(tmp_path):
    path = str(tmp_path / "real.db")
    conn = db.connect(path)
    try:
        db.init_schema(conn)
        import_raw(conn, str(REAL_RAW))
        assert len(db.list_review_items(conn, limit=1000)) == 78
    finally:
        conn.close()

    client = TestClient(
        create_app(Settings(port=8765, db_path=path, default_lang="en")),
        follow_redirects=False,
    )
    first = client.get("/review")
    second = client.get("/review?page=2")
    assert len(re.findall(r'data-review-id="\d+"', first.text)) == 10
    assert len(re.findall(r'data-review-id="\d+"', second.text)) == 10
