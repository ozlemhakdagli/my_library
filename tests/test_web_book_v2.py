import re

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app

HX = {"HX-Request": "true"}


@pytest.fixture
def seeded(tmp_path):
    """Alpha has a shelf, one type and a finished date; bravo has nothing assigned."""
    path = str(tmp_path / "book_v2.db")
    conn = db.connect(path)
    db.init_schema(conn)
    roman = db.add_shelf(conn, "Roman")
    felsefe = db.add_shelf(conn, "Felsefe")
    kagit = db.add_type(conn, "Kağıt")
    dijital = db.add_type(conn, "Dijital")
    alpha = db.add_book(conn, title="Alpha Title", author_names=["Yazar Bir"])
    bravo = db.add_book(conn, title="Bravo Title")
    db.set_book_shelf(conn, alpha, roman)
    db.set_book_types(conn, alpha, [kagit])
    db.set_reading_status(conn, alpha, "read", "2026-01-02", "2026-01-10")
    conn.close()
    ids = {
        "alpha": alpha,
        "bravo": bravo,
        "roman": roman,
        "felsefe": felsefe,
        "kagit": kagit,
        "dijital": dijital,
    }
    return path, ids


@pytest.fixture
def client(seeded):
    path, _ = seeded
    return TestClient(create_app(Settings(port=8765, db_path=path, default_lang="en")))


def db_shelf(path, book_id):
    conn = db.connect(path)
    try:
        return conn.execute("SELECT shelf_id FROM book WHERE id = ?", (book_id,)).fetchone()[0]
    finally:
        conn.close()


def db_types(path, book_id):
    conn = db.connect(path)
    try:
        return {row[0] for row in conn.execute(
            "SELECT type_id FROM book_type WHERE book_id = ?", (book_id,)
        )}
    finally:
        conn.close()


def test_assign_shelf_and_read_it_back(client, seeded):
    path, ids = seeded
    response = client.post(
        f"/books/{ids['bravo']}/shelf",
        data={"shelf_id": str(ids["roman"])},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/books/{ids['bravo']}"
    assert db_shelf(path, ids["bravo"]) == ids["roman"]
    page = client.get(f"/books/{ids['bravo']}").text
    assert re.search(rf'value="{ids["roman"]}" selected', page)


def test_clearing_shelf_shows_no_shelf(client, seeded):
    path, ids = seeded
    client.post(f"/books/{ids['alpha']}/shelf", data={"shelf_id": ""})
    assert db_shelf(path, ids["alpha"]) is None
    page = client.get(f"/books/{ids['alpha']}").text
    assert 'value="" selected>No shelf' in page


def test_book_without_shelf_shows_no_shelf_in_turkish(client, seeded):
    _, ids = seeded
    response = client.get(f"/books/{ids['bravo']}", params={"lang": "tr"})
    assert "Klasör yok" in response.text


def test_setting_types_replaces_the_set(client, seeded):
    path, ids = seeded
    client.post(f"/books/{ids['alpha']}/types", data={"type_id": [str(ids["dijital"])]})
    assert db_types(path, ids["alpha"]) == {ids["dijital"]}
    page = client.get(f"/books/{ids['alpha']}").text
    assert 'class="chip">Dijital' in page
    assert 'class="chip">Kağıt' not in page

    client.post(
        f"/books/{ids['alpha']}/types",
        data={"type_id": [str(ids["kagit"]), str(ids["dijital"])]},
    )
    assert db_types(path, ids["alpha"]) == {ids["kagit"], ids["dijital"]}


def test_htmx_requests_return_only_the_changed_block(client, seeded):
    _, ids = seeded
    shelf = client.post(
        f"/books/{ids['bravo']}/shelf", data={"shelf_id": str(ids["felsefe"])}, headers=HX
    )
    assert shelf.status_code == 200
    assert "<html" not in shelf.text
    assert 'id="shelf-block"' in shelf.text

    types = client.post(
        f"/books/{ids['bravo']}/types", data={"type_id": [str(ids["dijital"])]}, headers=HX
    )
    assert types.status_code == 200
    assert "<html" not in types.text
    assert 'id="types-block"' in types.text


def test_history_lists_shelf_and_type_changes(client, seeded):
    _, ids = seeded
    client.post(f"/books/{ids['bravo']}/shelf", data={"shelf_id": str(ids["felsefe"])})
    client.post(f"/books/{ids['bravo']}/types", data={"type_id": [str(ids["dijital"])]})
    page = client.get(f"/books/{ids['bravo']}").text
    assert "<td>Shelf</td>" in page
    assert "<td>Felsefe</td>" in page
    assert "<td>Type</td>" in page
    assert "<td>Dijital</td>" in page


def test_book_without_types_shows_only_the_add_picker(client, seeded):
    _, ids = seeded
    page = client.get(f"/books/{ids['bravo']}").text
    assert 'class="chip"' not in page
    assert "+ Add type" in page
    assert 'name="type_id"' in page


def test_deleted_shelf_and_type_are_not_offered(client, seeded):
    path, ids = seeded
    conn = db.connect(path)
    db.delete_shelf(conn, ids["felsefe"])
    db.delete_type(conn, ids["dijital"])
    conn.close()
    page = client.get(f"/books/{ids['bravo']}").text
    assert f'value="{ids["felsefe"]}"' not in page
    assert f'value="{ids["dijital"]}"' not in page


def test_status_badge_shows_finished_date(client, seeded):
    _, ids = seeded
    page = client.get(f"/books/{ids['alpha']}").text
    assert "Read · 2026-01-10" in page


def test_get_book_exposes_started_and_finished_dates(seeded):
    path, ids = seeded
    conn = db.connect(path)
    try:
        book = db.get_book(conn, ids["alpha"])
    finally:
        conn.close()
    assert book["started_on"] == "2026-01-02"
    assert book["finished_on"] == "2026-01-10"
    assert book["status"] == "read"
    assert book["title"] == "Alpha Title"


def test_invalid_shelf_or_type_input_is_rejected(client, seeded):
    _, ids = seeded
    assert client.post(f"/books/{ids['alpha']}/shelf", data={"shelf_id": "abc"}).status_code == 400
    assert client.post(
        f"/books/{ids['alpha']}/types", data={"type_id": ["abc"]}
    ).status_code == 400
    assert client.post("/books/999999/shelf", data={"shelf_id": ""}).status_code == 404
