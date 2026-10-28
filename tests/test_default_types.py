from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app


def _client(path):
    return TestClient(create_app(Settings(port=8765, db_path=path, default_lang="tr")))


def test_fresh_database_gets_default_types(tmp_path):
    client = _client(str(tmp_path / "fresh.db"))
    page = client.get("/types").text
    for name in db.DEFAULT_TYPES:
        assert name in page


def test_defaults_are_not_reseeded_after_user_deletes_them(tmp_path):
    path = str(tmp_path / "again.db")
    _client(path).get("/types")
    conn = db.connect(path)
    try:
        for row in db.list_types(conn):
            db.delete_type(conn, row["id"])
    finally:
        conn.close()

    _client(path).get("/types")
    conn = db.connect(path)
    try:
        assert db.list_types(conn) == []
    finally:
        conn.close()
