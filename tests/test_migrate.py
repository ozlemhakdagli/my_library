import sqlite3

import pytest

from library import migrate
from library.db import connect, init_schema

# Copy of db.SCHEMA as it was in schema v1 (before shelf, type and book.shelf_id).
V1_DDL = """
CREATE TABLE IF NOT EXISTS publisher (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS author (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS book (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    subtitle TEXT,
    norm_title TEXT NOT NULL,
    publisher_id INTEGER REFERENCES publisher(id),
    review_status TEXT NOT NULL DEFAULT 'ok',
    note TEXT,
    created_at TEXT,
    updated_at TEXT,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS book_author (
    book_id INTEGER NOT NULL REFERENCES book(id),
    author_id INTEGER NOT NULL REFERENCES author(id),
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_id, author_id)
);

CREATE TABLE IF NOT EXISTS photo (
    id INTEGER PRIMARY KEY,
    book_id INTEGER REFERENCES book(id),
    file_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    confidence TEXT
);

CREATE TABLE IF NOT EXISTS reading_status (
    book_id INTEGER PRIMARY KEY REFERENCES book(id),
    status TEXT NOT NULL,
    started_on TEXT,
    finished_on TEXT
);

CREATE TABLE IF NOT EXISTS loan (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES book(id),
    borrower TEXT NOT NULL,
    lent_on TEXT NOT NULL,
    returned_on TEXT
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_item (
    id INTEGER PRIMARY KEY,
    book_id INTEGER REFERENCES book(id),
    reason TEXT NOT NULL,
    photo_file TEXT,
    resolved_at TEXT,
    resolution TEXT
);
"""

NEW_TABLES = {"shelf", "type", "book_type"}
BOOK_V1_COLUMNS = (
    "id, title, subtitle, norm_title, publisher_id, review_status, note, "
    "created_at, updated_at, deleted_at"
)


@pytest.fixture
def v1_db(tmp_path):
    """A database file created with the v1 schema and some real-looking data."""
    path = tmp_path / "library_v1.db"
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA foreign_keys = ON")
    raw.executescript(V1_DDL)
    raw.executemany(
        "INSERT INTO book (id, title, norm_title, review_status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "Sefiller", "sefiller", "ok", "2024-01-01T10:00:00+00:00", "2024-01-01T10:00:00+00:00"),
            (2, "Suç ve Ceza", "sucveceza", "ok", "2024-01-02T10:00:00+00:00", "2024-01-02T10:00:00+00:00"),
            (3, "Savaş ve Barış", "savasvebaris", "needs review", "2024-01-03T10:00:00+00:00", "2024-01-03T10:00:00+00:00"),
        ],
    )
    raw.execute(
        "INSERT INTO photo (id, book_id, file_name, kind, confidence) "
        "VALUES (1, 1, 'IMG_0001.jpg', 'cover', 'high')"
    )
    raw.execute(
        "INSERT INTO review_item (id, book_id, reason, photo_file) "
        "VALUES (1, 3, 'low confidence', 'IMG_0002.jpg')"
    )
    raw.commit()
    raw.close()
    return path


@pytest.fixture
def conn(v1_db):
    c = connect(str(v1_db))
    yield c
    c.close()


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows}


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _snapshot(conn):
    return {
        "book": [tuple(r) for r in conn.execute(f"SELECT {BOOK_V1_COLUMNS} FROM book ORDER BY id")],
        "photo": [tuple(r) for r in conn.execute("SELECT * FROM photo ORDER BY id")],
        "review_item": [tuple(r) for r in conn.execute("SELECT * FROM review_item ORDER BY id")],
    }


def _schema(conn):
    return [tuple(r) for r in conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name")]


def test_v1_fixture_has_old_schema_and_data(conn):
    assert NEW_TABLES.isdisjoint(_tables(conn))
    assert "shelf_id" not in _columns(conn, "book")
    snap = _snapshot(conn)
    assert len(snap["book"]) == 3
    assert len(snap["photo"]) == 1
    assert len(snap["review_item"]) == 1


def test_upgrade_adds_new_tables_and_column(conn):
    changes = migrate.upgrade(conn)

    assert changes
    assert NEW_TABLES <= _tables(conn)
    assert "shelf_id" in _columns(conn, "book")


def test_upgrade_keeps_existing_rows(conn):
    before = _snapshot(conn)

    migrate.upgrade(conn)

    assert _snapshot(conn) == before


def test_second_upgrade_changes_nothing(conn):
    migrate.upgrade(conn)
    schema_after_first = _schema(conn)
    data_after_first = _snapshot(conn)

    assert migrate.upgrade(conn) == []

    assert _schema(conn) == schema_after_first
    assert _snapshot(conn) == data_after_first


def test_init_schema_then_upgrade_keeps_data(conn):
    before = _snapshot(conn)

    init_schema(conn)
    migrate.upgrade(conn)

    assert _snapshot(conn) == before
    assert "shelf_id" in _columns(conn, "book")


def test_fresh_database_gets_new_tables_from_init_schema(tmp_path):
    fresh = connect(str(tmp_path / "fresh.db"))
    try:
        init_schema(fresh)
        assert NEW_TABLES <= _tables(fresh)
        assert "shelf_id" in _columns(fresh, "book")
    finally:
        fresh.close()
