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
    db.add_book(conn, title="<script>alert(1)</script>")
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    return TestClient(create_app(Settings(port=8765, db_path=db_path, default_lang="en")))


def test_list_page_shows_book_title(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "yapay zeka" in response.text


def test_search_is_accent_and_case_insensitive(client):
    response = client.get("/", params={"q": "Yapay Zekâ"})
    assert response.status_code == 200
    assert "yapay zeka" in response.text
    assert "Lonely Book" not in response.text


def test_turkish_language_and_cookie(client):
    response = client.get("/", params={"lang": "tr"})
    assert response.status_code == 200
    assert "Kitaplar" in response.text
    assert client.cookies.get("lang") == "tr"


def test_cookie_selects_language_without_query(client):
    client.cookies.set("lang", "tr")
    response = client.get("/")
    assert "Kitaplar" in response.text


def test_missing_author_and_publisher_render_unknown(client):
    response = client.get("/", params={"q": "Lonely"})
    assert response.status_code == 200
    assert "Lonely Book" in response.text
    assert "unknown" in response.text


def test_title_is_html_escaped(client):
    response = client.get("/")
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_filter_by_publisher(client):
    response = client.get("/", params={"publisher": "pearson"})
    assert "yapay zeka" in response.text
    assert "Lonely Book" not in response.text


def test_pagination_is_15_per_page(tmp_path):
    path = str(tmp_path / "many.db")
    conn = db.connect(path)
    db.init_schema(conn)
    for i in range(16):
        db.add_book(conn, title=f"Book {i:03d}")
    conn.close()
    client = TestClient(create_app(Settings(port=8765, db_path=path, default_lang="en")))

    first = client.get("/")
    assert first.text.count('<li class="flex min-w-0 flex-col') == 15
    assert "1 / 2" in first.text

    second = client.get("/", params={"page": 2})
    assert second.text.count('<li class="flex min-w-0 flex-col') == 1
