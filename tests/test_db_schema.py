import sqlite3

import pytest

from library.db import connect, init_schema

EXPECTED_TABLES = {
    "book",
    "author",
    "book_author",
    "publisher",
    "photo",
    "reading_status",
    "loan",
    "history",
    "review_item",
}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def test_init_schema_creates_all_tables(conn):
    init_schema(conn)
    assert EXPECTED_TABLES <= _tables(conn)


def test_init_schema_is_idempotent(conn):
    init_schema(conn)
    init_schema(conn)
    assert EXPECTED_TABLES <= _tables(conn)


def test_book_author_rejects_missing_book(conn):
    init_schema(conn)
    conn.execute("INSERT INTO author (id, name, norm_name) VALUES (1, 'A', 'a')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO book_author (book_id, author_id, position) VALUES (999, 1, 0)")


def test_book_has_soft_delete_and_review_status_defaults(conn):
    init_schema(conn)
    conn.execute("INSERT INTO book (id, title, norm_title) VALUES (1, 'T', 't')")
    row = conn.execute("SELECT review_status, deleted_at FROM book WHERE id = 1").fetchone()
    assert row["review_status"] == "ok"
    assert row["deleted_at"] is None


def test_author_and_publisher_have_deleted_at(conn):
    init_schema(conn)
    for table in ("author", "publisher"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert "deleted_at" in cols, table


def test_review_item_reason_is_required(conn):
    init_schema(conn)
    conn.execute("INSERT INTO book (id, title, norm_title) VALUES (1, 'T', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO review_item (book_id, reason) VALUES (1, NULL)")


def test_connect_sets_row_factory_foreign_keys_and_wal(tmp_path):
    c = connect(str(tmp_path / "lib.db"))
    try:
        assert c.row_factory is sqlite3.Row
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        c.close()
