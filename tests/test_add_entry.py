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
    db.add_book(conn, title="Bir kitap", author_names=["Yazar"])
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    return TestClient(create_app(Settings(port=8765, db_path=db_path, default_lang="en")))


def test_home_page_links_to_add_book(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/books/new"' in response.text


def test_home_page_add_button_text_in_turkish(client):
    response = client.get("/", params={"lang": "tr"})
    assert response.status_code == 200
    assert "Kitap ekle" in response.text


def test_home_page_add_button_text_in_english(client):
    response = client.get("/")
    assert "Add book" in response.text


def test_books_new_page_opens(client):
    response = client.get("/books/new")
    assert response.status_code == 200
