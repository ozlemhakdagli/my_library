import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from library.norm import norm

SCHEMA = """
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
    book_id INTEGER NOT NULL REFERENCES book(id),
    file_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    confidence REAL
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
    book_id INTEGER NOT NULL REFERENCES book(id),
    reason TEXT NOT NULL
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


REVIEW_STATUSES = ("ok", "needs review")
UPDATABLE_FIELDS = ("title", "subtitle", "note", "review_status", "publisher", "authors")


@dataclass(frozen=True)
class HistoryEntry:
    field: str
    old_value: str | None
    new_value: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: str | None) -> str | None:
    """Stored form of a free-text value: stripped, empty becomes NULL."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split_authors(names: Sequence[str]) -> list[str]:
    """Drop empty names and duplicates (by norm), keep order."""
    result: list[str] = []
    keys: set[str] = set()
    for name in names:
        text = (name or "").strip()
        key = norm(text)
        if text and key not in keys:
            keys.add(key)
            result.append(text)
    return result


def _check_review_status(value: str) -> None:
    if value not in REVIEW_STATUSES:
        raise ValueError(f"invalid review_status: {value!r}")


def _get_or_create_publisher(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute(
        "SELECT id FROM publisher WHERE norm_name = ? AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (norm(name),),
    ).fetchone()
    if row is not None:
        return row["id"]
    return conn.execute(
        "INSERT INTO publisher (name, norm_name) VALUES (?, ?)", (name, norm(name))
    ).lastrowid


def _get_or_create_author(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute(
        "SELECT id FROM author WHERE norm_name = ? AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (norm(name),),
    ).fetchone()
    if row is not None:
        return row["id"]
    return conn.execute(
        "INSERT INTO author (name, norm_name) VALUES (?, ?)", (name, norm(name))
    ).lastrowid


def _publisher_name(conn: sqlite3.Connection, publisher_id: int | None) -> str | None:
    if publisher_id is None:
        return None
    row = conn.execute(
        "SELECT name FROM publisher WHERE id = ? AND deleted_at IS NULL", (publisher_id,)
    ).fetchone()
    return row["name"] if row is not None else None


def _set_authors(conn: sqlite3.Connection, book_id: int, names: list[str]) -> None:
    conn.execute("DELETE FROM book_author WHERE book_id = ?", (book_id,))
    for position, name in enumerate(names):
        author_id = _get_or_create_author(conn, name)
        conn.execute(
            "INSERT INTO book_author (book_id, author_id, position) VALUES (?, ?, ?)",
            (book_id, author_id, position),
        )


def _authors_of(conn: sqlite3.Connection, book_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT a.name FROM book_author ba JOIN author a ON a.id = ba.author_id "
        "WHERE ba.book_id = ? AND a.deleted_at IS NULL "
        "ORDER BY ba.position, ba.author_id",
        (book_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def _live_book(conn: sqlite3.Connection, book_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM book WHERE id = ? AND deleted_at IS NULL", (book_id,)
    ).fetchone()


def _write_history(
    conn: sqlite3.Connection, book_id: int, entries: list[HistoryEntry], changed_at: str
) -> None:
    for e in entries:
        conn.execute(
            "INSERT INTO history (record_type, record_id, field, old_value, new_value, changed_at) "
            "VALUES ('book', ?, ?, ?, ?, ?)",
            (book_id, e.field, e.old_value, e.new_value, changed_at),
        )


def _book_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    book_id = row["id"]
    status = conn.execute(
        "SELECT status FROM reading_status WHERE book_id = ?", (book_id,)
    ).fetchone()
    loan = conn.execute(
        "SELECT borrower, lent_on, returned_on FROM loan "
        "WHERE book_id = ? AND returned_on IS NULL ORDER BY lent_on DESC, id DESC LIMIT 1",
        (book_id,),
    ).fetchone()
    return {
        "id": book_id,
        "title": row["title"],
        "subtitle": row["subtitle"] or "",
        "authors": _authors_of(conn, book_id),
        "publisher": _publisher_name(conn, row["publisher_id"]) or "",
        "review_status": row["review_status"],
        "note": row["note"] or "",
        "status": status["status"] if status is not None else None,
        "loan": dict(loan) if loan is not None else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def add_book(
    conn: sqlite3.Connection,
    *,
    title: str,
    subtitle: str = "",
    author_names: Sequence[str] = (),
    publisher: str = "",
    note: str = "",
    review_status: str = "ok",
) -> int:
    title_text = _text(title)
    if title_text is None:
        raise ValueError("title is required")
    _check_review_status(review_status)
    names = _split_authors(author_names)
    publisher_text = _text(publisher)
    subtitle_text = _text(subtitle)
    note_text = _text(note)
    ts = _now()

    with conn:
        publisher_id = _get_or_create_publisher(conn, publisher_text) if publisher_text else None
        cur = conn.execute(
            "INSERT INTO book (title, subtitle, norm_title, publisher_id, review_status, note, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title_text,
                subtitle_text,
                norm(title_text),
                publisher_id,
                review_status,
                note_text,
                ts,
                ts,
            ),
        )
        book_id = cur.lastrowid
        _set_authors(conn, book_id, names)
        initial = {
            "title": title_text,
            "subtitle": subtitle_text,
            "note": note_text,
            "review_status": review_status,
            "publisher": publisher_text,
            "authors": "; ".join(names) or None,
        }
        entries = [HistoryEntry(f, None, v) for f, v in initial.items() if v is not None]
        _write_history(conn, book_id, entries, ts)
    return book_id


def get_book(conn: sqlite3.Connection, book_id: int) -> dict | None:
    row = _live_book(conn, book_id)
    if row is None:
        return None
    return _book_to_dict(conn, row)


def update_book(conn: sqlite3.Connection, book_id: int, changes: dict[str, str]) -> list[HistoryEntry]:
    """Apply changes; write one history row per changed field in one transaction.

    `authors` is a single string with names separated by ";".
    Returns the history entries written (empty if nothing changed).
    """
    unknown = set(changes) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")

    ts = _now()
    with conn:
        row = _live_book(conn, book_id)
        if row is None:
            raise ValueError(f"book {book_id} not found")

        columns: dict[str, object] = {}
        entries: list[HistoryEntry] = []

        for field, raw in changes.items():
            if field == "title":
                new = _text(raw)
                if new is None:
                    raise ValueError("title is required")
                if new != row["title"]:
                    columns["title"] = new
                    columns["norm_title"] = norm(new)
                    entries.append(HistoryEntry("title", row["title"], new))
            elif field in ("subtitle", "note"):
                new = _text(raw)
                if new != row[field]:
                    columns[field] = new
                    entries.append(HistoryEntry(field, row[field], new))
            elif field == "review_status":
                _check_review_status(raw)
                if raw != row["review_status"]:
                    columns["review_status"] = raw
                    entries.append(HistoryEntry("review_status", row["review_status"], raw))
            elif field == "publisher":
                new = _text(raw)
                old = _publisher_name(conn, row["publisher_id"])
                if new != old:
                    columns["publisher_id"] = (
                        _get_or_create_publisher(conn, new) if new is not None else None
                    )
                    entries.append(HistoryEntry("publisher", old, new))
            elif field == "authors":
                names = _split_authors(raw.split(";"))
                old_names = _authors_of(conn, book_id)
                if names != old_names:
                    _set_authors(conn, book_id, names)
                    entries.append(
                        HistoryEntry(
                            "authors",
                            "; ".join(old_names) or None,
                            "; ".join(names) or None,
                        )
                    )

        if entries:
            columns["updated_at"] = ts
            assignments = ", ".join(f"{col} = ?" for col in columns)
            conn.execute(
                f"UPDATE book SET {assignments} WHERE id = ?",
                [*columns.values(), book_id],
            )
            _write_history(conn, book_id, entries, ts)
    return entries


def soft_delete_book(conn: sqlite3.Connection, book_id: int) -> None:
    ts = _now()
    with conn:
        if _live_book(conn, book_id) is None:
            return
        conn.execute(
            "UPDATE book SET deleted_at = ?, updated_at = ? WHERE id = ?", (ts, ts, book_id)
        )
        _write_history(conn, book_id, [HistoryEntry("deleted_at", None, ts)], ts)


def _filter_sql(
    *,
    query: str,
    status: str | None,
    loan: str | None,
    publisher: str | None,
    author: str | None,
    needs_review: bool,
) -> tuple[str, str, list[object]]:
    from_sql = (
        "FROM book b "
        "LEFT JOIN publisher p ON p.id = b.publisher_id "
        "LEFT JOIN reading_status rs ON rs.book_id = b.id"
    )
    where = ["b.deleted_at IS NULL"]
    params: list[object] = []

    key = norm(query)
    if key:
        pattern = f"%{key}%"
        where.append(
            "(b.norm_title LIKE ? OR p.norm_name LIKE ? OR EXISTS ("
            "SELECT 1 FROM book_author ba JOIN author a ON a.id = ba.author_id "
            "WHERE ba.book_id = b.id AND a.deleted_at IS NULL AND a.norm_name LIKE ?))"
        )
        params += [pattern, pattern, pattern]
    if status:
        where.append("rs.status = ?")
        params.append(status)
    if loan is not None:
        if loan not in ("out", "in"):
            raise ValueError(f"loan must be 'out' or 'in': {loan!r}")
        exists = "EXISTS" if loan == "out" else "NOT EXISTS"
        where.append(
            f"{exists} (SELECT 1 FROM loan l WHERE l.book_id = b.id AND l.returned_on IS NULL)"
        )
    if publisher:
        where.append("p.norm_name = ?")
        params.append(norm(publisher))
    if author:
        where.append(
            "EXISTS (SELECT 1 FROM book_author ba JOIN author a ON a.id = ba.author_id "
            "WHERE ba.book_id = b.id AND a.deleted_at IS NULL AND a.norm_name = ?)"
        )
        params.append(norm(author))
    if needs_review:
        where.append("b.review_status = 'needs review'")
    return from_sql, " AND ".join(where), params


def list_books(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    status: str | None = None,
    loan: str | None = None,
    publisher: str | None = None,
    author: str | None = None,
    needs_review: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    from_sql, where, params = _filter_sql(
        query=query,
        status=status,
        loan=loan,
        publisher=publisher,
        author=author,
        needs_review=needs_review,
    )
    rows = conn.execute(
        f"SELECT b.* {from_sql} WHERE {where} ORDER BY b.norm_title, b.id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [_book_to_dict(conn, r) for r in rows]


def count_books(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    status: str | None = None,
    loan: str | None = None,
    publisher: str | None = None,
    author: str | None = None,
    needs_review: bool = False,
) -> int:
    from_sql, where, params = _filter_sql(
        query=query,
        status=status,
        loan=loan,
        publisher=publisher,
        author=author,
        needs_review=needs_review,
    )
    row = conn.execute(f"SELECT COUNT(*) AS n {from_sql} WHERE {where}", params).fetchone()
    return row["n"]


READING_STATUSES = ("unread", "reading", "read", "abandoned")


class LoanError(Exception):
    """A loan operation conflicts with the current loan state."""


def _open_loan(conn: sqlite3.Connection, book_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id FROM loan WHERE book_id = ? AND returned_on IS NULL", (book_id,)
    ).fetchone()


def set_reading_status(
    conn: sqlite3.Connection,
    book_id: int,
    status: str,
    started_on: str | None = None,
    finished_on: str | None = None,
) -> None:
    """Set reading status and dates; one history row per changed field."""
    if status not in READING_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    started_text = _text(started_on)
    finished_text = _text(finished_on)
    ts = _now()

    with conn:
        if _live_book(conn, book_id) is None:
            raise ValueError(f"book {book_id} not found")
        old = conn.execute(
            "SELECT status, started_on, finished_on FROM reading_status WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        old_values = (
            {k: old[k] for k in ("status", "started_on", "finished_on")}
            if old is not None
            else {"status": None, "started_on": None, "finished_on": None}
        )
        new_values = {"status": status, "started_on": started_text, "finished_on": finished_text}
        changed = [f for f in new_values if new_values[f] != old_values[f]]
        if not changed:
            return
        conn.execute(
            "INSERT INTO reading_status (book_id, status, started_on, finished_on) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(book_id) DO UPDATE SET status = excluded.status, "
            "started_on = excluded.started_on, finished_on = excluded.finished_on",
            (book_id, status, started_text, finished_text),
        )
        _write_history(
            conn,
            book_id,
            [HistoryEntry(f, old_values[f], new_values[f]) for f in changed],
            ts,
        )


def lend_book(conn: sqlite3.Connection, book_id: int, borrower: str, lent_on: str) -> int:
    """Open a loan for a book. Raises LoanError if the book is already out."""
    borrower_text = _text(borrower)
    if borrower_text is None:
        raise ValueError("borrower is required")
    lent_text = _text(lent_on)
    if lent_text is None:
        raise ValueError("lent_on is required")
    ts = _now()

    with conn:
        if _live_book(conn, book_id) is None:
            raise ValueError(f"book {book_id} not found")
        if _open_loan(conn, book_id) is not None:
            raise LoanError("already lent")
        cur = conn.execute(
            "INSERT INTO loan (book_id, borrower, lent_on, returned_on) VALUES (?, ?, ?, NULL)",
            (book_id, borrower_text, lent_text),
        )
        _write_history(
            conn,
            book_id,
            [
                HistoryEntry("lent_to", None, borrower_text),
                HistoryEntry("lent_on", None, lent_text),
            ],
            ts,
        )
    return cur.lastrowid


def return_book(conn: sqlite3.Connection, loan_id: int, returned_on: str) -> None:
    """Close a loan. Raises LoanError if it is already closed."""
    returned_text = _text(returned_on)
    if returned_text is None:
        raise ValueError("returned_on is required")
    ts = _now()

    with conn:
        loan = conn.execute(
            "SELECT id, book_id, returned_on FROM loan WHERE id = ?", (loan_id,)
        ).fetchone()
        if loan is None:
            raise ValueError(f"loan {loan_id} not found")
        if loan["returned_on"] is not None:
            raise LoanError("already returned")
        conn.execute("UPDATE loan SET returned_on = ? WHERE id = ?", (returned_text, loan_id))
        _write_history(
            conn,
            loan["book_id"],
            [HistoryEntry("returned_on", None, returned_text)],
            ts,
        )


def open_loans(conn: sqlite3.Connection) -> list[dict]:
    """Loans with no return date, oldest first."""
    rows = conn.execute(
        "SELECT l.id AS loan_id, l.book_id, b.title, l.borrower, l.lent_on "
        "FROM loan l JOIN book b ON b.id = l.book_id "
        "WHERE l.returned_on IS NULL ORDER BY l.lent_on, l.id"
    ).fetchall()
    return [dict(r) for r in rows]
