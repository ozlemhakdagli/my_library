from library import migrate
from library.db import connect, init_schema


def _pre_cover_db(path):
    """A database as it looked before the cover columns: current schema minus book.cover_*."""
    conn = connect(str(path))
    init_schema(conn)
    conn.execute("ALTER TABLE book DROP COLUMN cover_file")
    conn.execute("ALTER TABLE book DROP COLUMN cover_color")
    conn.execute(
        "INSERT INTO book (title, norm_title, review_status) VALUES ('Sefiller', 'sefiller', 'ok')"
    )
    conn.commit()
    return conn


def _book_columns(conn):
    return {r["name"] for r in conn.execute("PRAGMA table_info(book)")}


def test_upgrade_adds_cover_columns_and_keeps_rows(tmp_path):
    conn = _pre_cover_db(tmp_path / "library.db")
    assert "cover_file" not in _book_columns(conn)

    changes = migrate.upgrade(conn)

    assert changes == ["column:book.cover_file", "column:book.cover_color"]
    assert {"cover_file", "cover_color"} <= _book_columns(conn)
    row = conn.execute("SELECT title, cover_file, cover_color FROM book").fetchone()
    assert row["title"] == "Sefiller"
    assert row["cover_file"] is None
    assert row["cover_color"] is None
    conn.close()


def test_upgrade_is_idempotent_for_cover_columns(tmp_path):
    conn = _pre_cover_db(tmp_path / "library.db")
    migrate.upgrade(conn)

    assert migrate.upgrade(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM book").fetchone()[0] == 1
    conn.close()


def test_fresh_schema_already_has_cover_columns(tmp_path):
    conn = connect(str(tmp_path / "fresh.db"))
    init_schema(conn)

    assert {"cover_file", "cover_color"} <= _book_columns(conn)
    assert migrate.upgrade(conn) == []
    conn.close()
