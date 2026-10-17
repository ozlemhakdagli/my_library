"""In-place upgrade of an existing library database to the current schema.

Every step is guarded, so running upgrade() again on an up-to-date database changes
nothing. Rows are never deleted, moved or renamed. The DDL below is frozen on purpose:
a migration must keep producing the same result even after db.SCHEMA changes later.
"""

import sqlite3
from pathlib import Path

from library import db
from library.config import Settings

_NEW_TABLES: tuple[tuple[str, str], ...] = (
    (
        "shelf",
        "CREATE TABLE IF NOT EXISTS shelf (\n"
        "    id INTEGER PRIMARY KEY,\n"
        "    name TEXT NOT NULL,\n"
        "    norm_name TEXT NOT NULL,\n"
        "    created_at TEXT,\n"
        "    deleted_at TEXT\n"
        ")",
    ),
    (
        "type",
        "CREATE TABLE IF NOT EXISTS type (\n"
        "    id INTEGER PRIMARY KEY,\n"
        "    name TEXT NOT NULL,\n"
        "    norm_name TEXT NOT NULL,\n"
        "    created_at TEXT,\n"
        "    deleted_at TEXT\n"
        ")",
    ),
    (
        "book_type",
        "CREATE TABLE IF NOT EXISTS book_type (\n"
        "    book_id INTEGER NOT NULL REFERENCES book(id),\n"
        "    type_id INTEGER NOT NULL REFERENCES type(id),\n"
        "    PRIMARY KEY (book_id, type_id)\n"
        ")",
    ),
)

_BOOK_SHELF_COLUMN = "shelf_id"
_BOOK_SHELF_DDL = "ALTER TABLE book ADD COLUMN shelf_id INTEGER REFERENCES shelf(id)"

_BOOK_COVER_DDL: tuple[tuple[str, str], ...] = (
    ("cover_file", "ALTER TABLE book ADD COLUMN cover_file TEXT"),
    ("cover_color", "ALTER TABLE book ADD COLUMN cover_color TEXT"),
)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(conn: sqlite3.Connection) -> list[str]:
    """Bring the schema up to date in one transaction.

    Returns the names of the changes applied, e.g. "table:shelf" or "column:book.shelf_id".
    Returns an empty list when the database is already current. A transaction that is
    open on `conn` is committed first, because the schema change needs its own.
    """
    if conn.in_transaction:
        conn.commit()

    changes: list[str] = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        tables = _table_names(conn)
        for name, ddl in _NEW_TABLES:
            if name not in tables:
                conn.execute(ddl)
                changes.append(f"table:{name}")

        if "book" in tables:
            book_columns = _column_names(conn, "book")
            if _BOOK_SHELF_COLUMN not in book_columns:
                conn.execute(_BOOK_SHELF_DDL)
                changes.append(f"column:book.{_BOOK_SHELF_COLUMN}")
            for column, ddl in _BOOK_COVER_DDL:
                if column not in book_columns:
                    conn.execute(ddl)
                    changes.append(f"column:book.{column}")

        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return changes


if __name__ == "__main__":
    settings = Settings.from_env()
    if not Path(settings.db_path).exists():
        raise SystemExit(f"database not found: {settings.db_path}")
    conn = db.connect(settings.db_path)
    try:
        changes = upgrade(conn)
    finally:
        conn.close()
    print("\n".join(changes) if changes else "no changes")
