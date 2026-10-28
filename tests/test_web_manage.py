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
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    app = create_app(
        Settings(port=8765, db_path=db_path, default_lang="en"),
        today_fn=lambda: TODAY,
    )
    return TestClient(app, follow_redirects=False)


def _conn(db_path):
    conn = db.connect(db_path)
    return conn


def _shelf_id(db_path, name):
    conn = _conn(db_path)
    try:
        return conn.execute("SELECT id FROM shelf WHERE name = ?", (name,)).fetchone()["id"]
    finally:
        conn.close()


def _type_id(db_path, name):
    conn = _conn(db_path)
    try:
        return conn.execute("SELECT id FROM type WHERE name = ?", (name,)).fetchone()["id"]
    finally:
        conn.close()


def _count(db_path, table):
    conn = _conn(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_shelves_page_is_empty_initially(client):
    response = client.get("/shelves")
    assert response.status_code == 200
    assert "No shelves yet." in response.text


def test_create_shelf_redirects_and_lists_it(client, db_path):
    response = client.post("/shelves", data={"name": "Roman"})
    assert response.status_code == 303
    assert response.headers["location"] == "/shelves"
    assert "Roman" in client.get("/shelves").text
    assert _count(db_path, "shelf") == 1


def test_duplicate_shelf_name_ignoring_case_and_accent_is_409(client, db_path):
    client.post("/shelves", data={"name": "Şiir"})
    response = client.post("/shelves", data={"name": "siir"})
    assert response.status_code == 409
    assert "A shelf with this name already exists." in response.text
    assert _count(db_path, "shelf") == 1


def test_duplicate_shelf_message_in_turkish(client):
    client.post("/shelves", data={"name": "Roman"})
    response = client.post("/shelves?lang=tr", data={"name": "roman"})
    assert response.status_code == 409
    assert "Bu adda bir klasör zaten var." in response.text


def test_rename_shelf(client, db_path):
    client.post("/shelves", data={"name": "Roman"})
    shelf_id = _shelf_id(db_path, "Roman")
    response = client.post(f"/shelves/{shelf_id}/rename", data={"name": "Deneme"})
    assert response.status_code == 303
    assert "Deneme" in client.get("/shelves").text
    assert _shelf_id(db_path, "Deneme") == shelf_id


def test_rename_shelf_to_taken_name_is_409(client, db_path):
    client.post("/shelves", data={"name": "Roman"})
    client.post("/shelves", data={"name": "Deneme"})
    shelf_id = _shelf_id(db_path, "Deneme")
    response = client.post(f"/shelves/{shelf_id}/rename", data={"name": "roman"})
    assert response.status_code == 409
    assert _shelf_id(db_path, "Deneme") == shelf_id


def test_rename_missing_shelf_is_404(client):
    response = client.post("/shelves/9999/rename", data={"name": "Yeni"})
    assert response.status_code == 404


def test_empty_shelf_name_is_422_and_db_unchanged(client, db_path):
    client.post("/shelves", data={"name": "Roman"})
    response = client.post("/shelves", data={"name": "   "})
    assert response.status_code == 422
    assert "The name cannot be empty." in response.text
    assert _count(db_path, "shelf") == 1


def test_empty_rename_is_422_and_name_kept(client, db_path):
    client.post("/shelves", data={"name": "Roman"})
    shelf_id = _shelf_id(db_path, "Roman")
    response = client.post(f"/shelves/{shelf_id}/rename", data={"name": ""})
    assert response.status_code == 422
    assert _shelf_id(db_path, "Roman") == shelf_id


def test_delete_shelf_hides_it_and_keeps_book_link(client, db_path):
    client.post("/shelves", data={"name": "Roman"})
    shelf_id = _shelf_id(db_path, "Roman")
    conn = _conn(db_path)
    book_id = db.add_book(conn, title="Sefiller", author_names=["Victor Hugo"])
    db.set_book_shelf(conn, book_id, shelf_id)
    conn.close()

    response = client.post(f"/shelves/{shelf_id}/delete")
    assert response.status_code == 303
    assert "Roman" not in client.get("/shelves").text

    conn = _conn(db_path)
    try:
        row = conn.execute("SELECT shelf_id FROM book WHERE id = ?", (book_id,)).fetchone()
        assert row["shelf_id"] == shelf_id
    finally:
        conn.close()


def test_shelf_page_shows_book_counts(client, db_path):
    client.post("/shelves", data={"name": "Roman"})
    shelf_id = _shelf_id(db_path, "Roman")
    conn = _conn(db_path)
    for title in ("Sefiller", "Kürk Mantolu Madonna"):
        book_id = db.add_book(conn, title=title, author_names=["Yazar"])
        db.set_book_shelf(conn, book_id, shelf_id)
    conn.close()
    assert "Books: 2" in client.get("/shelves").text


def test_turkish_shelves_page_uses_klasor(client):
    client.post("/shelves", data={"name": "Roman"})
    text = client.get("/shelves", params={"lang": "tr"}).text
    assert "Klasör" in text
    assert "Raf" not in text


def test_create_type_and_duplicate_is_409(client, db_path):
    assert client.post("/types", data={"name": "Sesli"}).status_code == 303
    response = client.post("/types", data={"name": "sesli"})
    assert response.status_code == 409
    assert "A type with this name already exists." in response.text
    assert _count(db_path, "type") == len(db.DEFAULT_TYPES) + 1


def test_rename_and_delete_type(client, db_path):
    client.post("/types", data={"name": "Sesli"})
    type_id = _type_id(db_path, "Sesli")
    assert client.post(f"/types/{type_id}/rename", data={"name": "Sesli Kitap"}).status_code == 303
    assert "Sesli Kitap" in client.get("/types").text

    assert client.post(f"/types/{type_id}/delete").status_code == 303
    assert "Sesli Kitap" not in client.get("/types").text


def test_type_page_shows_book_counts(client, db_path):
    client.post("/types", data={"name": "Sesli"})
    type_id = _type_id(db_path, "Sesli")
    conn = _conn(db_path)
    book_id = db.add_book(conn, title="Sefiller", author_names=["Victor Hugo"])
    db.set_book_types(conn, book_id, [type_id])
    conn.close()
    assert "Books: 1" in client.get("/types").text


def test_empty_type_name_is_422(client, db_path):
    response = client.post("/types", data={"name": ""})
    assert response.status_code == 422
    assert _count(db_path, "type") == len(db.DEFAULT_TYPES)


def test_nav_links_to_shelves_and_types(client):
    text = client.get("/").text
    assert 'href="/shelves"' in text
    assert 'href="/types"' in text
    assert "Shelves" in text and "Types" in text
