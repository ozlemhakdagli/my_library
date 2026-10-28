import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone

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

CREATE TABLE IF NOT EXISTS shelf (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    created_at TEXT,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS type (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    created_at TEXT,
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
    deleted_at TEXT,
    shelf_id INTEGER REFERENCES shelf(id),
    cover_file TEXT,
    cover_color TEXT
);

CREATE TABLE IF NOT EXISTS book_type (
    book_id INTEGER NOT NULL REFERENCES book(id),
    type_id INTEGER NOT NULL REFERENCES type(id),
    PRIMARY KEY (book_id, type_id)
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

# Columns added after the first schema version; databases created earlier get them via ALTER.
_REVIEW_ITEM_ADDED_COLUMNS = ("resolved_at", "resolution")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


DEFAULT_TYPES = (
    "Roman",
    "Öykü",
    "Şiir",
    "Deneme",
    "Tarih",
    "Felsefe",
    "Bilim",
    "Psikoloji",
    "Ekonomi",
    "Sanat",
    "Biyografi",
    "Çocuk ve Gençlik",
)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(review_item)")}
    for column in _REVIEW_ITEM_ADDED_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE review_item ADD COLUMN {column} TEXT")
    conn.commit()


def seed_default_types(conn: sqlite3.Connection) -> None:
    """Add DEFAULT_TYPES only when the type table has never had a row, so deleted defaults stay deleted."""
    if conn.execute("SELECT COUNT(*) FROM type").fetchone()[0] == 0:
        for name in DEFAULT_TYPES:
            add_type(conn, name)


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
        "SELECT status, started_on, finished_on FROM reading_status WHERE book_id = ?",
        (book_id,),
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
        "started_on": status["started_on"] if status is not None else None,
        "finished_on": status["finished_on"] if status is not None else None,
        "loan": dict(loan) if loan is not None else None,
        "cover_file": row["cover_file"],
        "cover_color": row["cover_color"],
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
    shelf_id: int | None = None,
    no_shelf: bool = False,
    type_ids: Sequence[int] | None = None,
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
    if status == "unread":
        # A book without a reading_status row is unread (see reading_counts).
        where.append("(rs.status IS NULL OR rs.status = 'unread')")
    elif status:
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
    if no_shelf:
        where.append("b.shelf_id IS NULL")
    elif shelf_id is not None:
        where.append("b.shelf_id = ?")
        params.append(shelf_id)
    if type_ids:
        # Any of the given types (OR); combined with the other filters by AND.
        marks = ", ".join("?" for _ in type_ids)
        where.append(
            "EXISTS (SELECT 1 FROM book_type bt WHERE bt.book_id = b.id "
            f"AND bt.type_id IN ({marks}))"
        )
        params += [int(t) for t in type_ids]
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
    shelf_id: int | None = None,
    no_shelf: bool = False,
    type_ids: Sequence[int] | None = None,
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
        shelf_id=shelf_id,
        no_shelf=no_shelf,
        type_ids=type_ids,
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
    shelf_id: int | None = None,
    no_shelf: bool = False,
    type_ids: Sequence[int] | None = None,
) -> int:
    from_sql, where, params = _filter_sql(
        query=query,
        status=status,
        loan=loan,
        publisher=publisher,
        author=author,
        needs_review=needs_review,
        shelf_id=shelf_id,
        no_shelf=no_shelf,
        type_ids=type_ids,
    )
    row = conn.execute(f"SELECT COUNT(*) AS n {from_sql} WHERE {where}", params).fetchone()
    return row["n"]


READING_STATUSES = ("unread", "reading", "read", "abandoned")


class LoanError(Exception):
    """A loan operation conflicts with the current loan state."""


class ReadingDateError(ValueError):
    """A reading date is invalid. ``code`` is the i18n message key for it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _parse_reading_date(value: str, today: date | None = None) -> date:
    """Parse a YYYY-MM-DD date. With ``today``, also reject dates after it."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ReadingDateError("err_invalid_date") from None
    if today is not None and parsed > today:
        raise ReadingDateError("err_future_date")
    return parsed


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
    today: date | None = None,
) -> None:
    """Set reading status and dates; one history row per changed field.

    An empty or missing date keeps the stored value. Given dates must be
    YYYY-MM-DD and not after ``today`` (default: the current date). The
    finished date may not be earlier than the started date. Invalid dates
    raise ``ReadingDateError`` (a ``ValueError``) and nothing is written.
    """
    if status not in READING_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    started_text = _text(started_on)
    finished_text = _text(finished_on)
    if today is None:
        today = date.today()
    for given in (started_text, finished_text):
        if given is not None:
            _parse_reading_date(given, today)
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
        new_values = {
            "status": status,
            "started_on": started_text if started_text is not None else old_values["started_on"],
            "finished_on": (
                finished_text if finished_text is not None else old_values["finished_on"]
            ),
        }
        if status == "reading":
            # Reading again starts a new round: the old finish date stays in history.
            new_values["finished_on"] = None
            if old_values["status"] != "reading" and started_text is None:
                new_values["started_on"] = today.isoformat()
        if new_values["started_on"] and new_values["finished_on"]:
            started_day = _parse_reading_date(new_values["started_on"])
            finished_day = _parse_reading_date(new_values["finished_on"])
            if finished_day < started_day:
                raise ReadingDateError("err_finished_before_started")
        changed = [f for f in new_values if new_values[f] != old_values[f]]
        if not changed:
            return
        conn.execute(
            "INSERT INTO reading_status (book_id, status, started_on, finished_on) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(book_id) DO UPDATE SET status = excluded.status, "
            "started_on = excluded.started_on, finished_on = excluded.finished_on",
            (book_id, status, new_values["started_on"], new_values["finished_on"]),
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
        "WHERE l.returned_on IS NULL AND b.deleted_at IS NULL ORDER BY l.lent_on, l.id"
    ).fetchall()
    return [dict(r) for r in rows]


def get_history(conn: sqlite3.Connection, book_id: int) -> list[dict]:
    """Change history of a book, newest first."""
    rows = conn.execute(
        "SELECT field, old_value, new_value, changed_at FROM history "
        "WHERE record_type = 'book' AND record_id = ? ORDER BY changed_at DESC, id DESC",
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_photos(conn: sqlite3.Connection, book_id: int) -> list[dict]:
    """Photo file names of a book, in import order. Only names are stored, never paths."""
    rows = conn.execute(
        "SELECT file_name, kind, confidence FROM photo WHERE book_id = ? ORDER BY id",
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_loans(conn: sqlite3.Connection, book_id: int) -> list[dict]:
    """All loans of a book, newest first, including returned ones."""
    rows = conn.execute(
        "SELECT borrower, lent_on, returned_on FROM loan "
        "WHERE book_id = ? ORDER BY lent_on DESC, id DESC",
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


REVIEW_ACTIONS = ("confirm", "not_a_book")


class ReviewError(Exception):
    """A review item was already resolved."""


def list_review_items(conn: sqlite3.Connection, limit: int = 50, offset: int = 0) -> list[dict]:
    """Open review items, oldest first.

    `title` is the book's title, or None for an unreadable record (book_id is None);
    the caller shows the translated label for that case.
    """
    rows = conn.execute(
        "SELECT r.id, r.book_id, r.photo_file, r.reason, b.title "
        "FROM review_item r LEFT JOIN book b ON b.id = r.book_id "
        "WHERE r.resolved_at IS NULL ORDER BY r.id LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_review_item(conn: sqlite3.Connection, item_id: int, action: str) -> None:
    """Close a review item and record the action in history.

    "confirm" sets a linked book's review_status to "ok". "not_a_book" closes the
    item only; the book row is kept. Nothing is physically deleted.
    """
    if action not in REVIEW_ACTIONS:
        raise ValueError(f"invalid review action: {action!r}")
    ts = _now()

    with conn:
        item = conn.execute(
            "SELECT id, book_id, resolved_at FROM review_item WHERE id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise LookupError(f"review item {item_id} not found")
        if item["resolved_at"] is not None:
            raise ReviewError("already resolved")
        book_id = item["book_id"]

        if book_id is not None and action == "confirm":
            book = conn.execute(
                "SELECT review_status FROM book WHERE id = ?", (book_id,)
            ).fetchone()
            if book is not None and book["review_status"] != "ok":
                conn.execute(
                    "UPDATE book SET review_status = 'ok', updated_at = ? WHERE id = ?",
                    (ts, book_id),
                )
                _write_history(
                    conn,
                    book_id,
                    [HistoryEntry("review_status", book["review_status"], "ok")],
                    ts,
                )

        conn.execute(
            "UPDATE review_item SET resolved_at = ?, resolution = ? WHERE id = ?",
            (ts, action, item_id),
        )
        conn.execute(
            "INSERT INTO history (record_type, record_id, field, old_value, new_value, changed_at) "
            "VALUES ('review_item', ?, 'resolution', NULL, ?, ?)",
            (item_id, action, ts),
        )
        if book_id is not None:
            _write_history(conn, book_id, [HistoryEntry("review_resolution", None, action)], ts)


class NameTakenError(Exception):
    """A non-deleted shelf or type already has this name (compared by norm_name)."""


def _clean_name(name: str) -> tuple[str, str]:
    """Stored form of a shelf or type name and its comparison key."""
    text = _text(name)
    if text is None or not norm(text):
        raise ValueError("name is required")
    return text, norm(text)


def _live_named(conn: sqlite3.Connection, table: str, row_id: int) -> sqlite3.Row:
    """Row of `shelf` or `type` that is not deleted. `table` is internal, never user input."""
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ? AND deleted_at IS NULL", (row_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"{table} {row_id} not found")
    return row


def _ensure_name_free(conn: sqlite3.Connection, table: str, key: str, own_id: int | None) -> None:
    row = conn.execute(
        f"SELECT id FROM {table} WHERE norm_name = ? AND deleted_at IS NULL AND id IS NOT ?",
        (key, own_id),
    ).fetchone()
    if row is not None:
        raise NameTakenError(key)


def _name_of(conn: sqlite3.Connection, table: str, row_id: int | None) -> str | None:
    """Name of a shelf or type, deleted or not, for history values."""
    if row_id is None:
        return None
    row = conn.execute(f"SELECT name FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return row["name"] if row is not None else None


def add_shelf(conn: sqlite3.Connection, name: str) -> int:
    text, key = _clean_name(name)
    ts = _now()
    with conn:
        _ensure_name_free(conn, "shelf", key, None)
        cur = conn.execute(
            "INSERT INTO shelf (name, norm_name, created_at) VALUES (?, ?, ?)", (text, key, ts)
        )
    return cur.lastrowid


def rename_shelf(conn: sqlite3.Connection, shelf_id: int, name: str) -> None:
    text, key = _clean_name(name)
    with conn:
        row = _live_named(conn, "shelf", shelf_id)
        _ensure_name_free(conn, "shelf", key, shelf_id)
        if text != row["name"]:
            conn.execute(
                "UPDATE shelf SET name = ?, norm_name = ? WHERE id = ?", (text, key, shelf_id)
            )


def delete_shelf(conn: sqlite3.Connection, shelf_id: int) -> None:
    """Soft delete. Books keep their shelf_id; the shelf is hidden from lists and pickers."""
    ts = _now()
    with conn:
        _live_named(conn, "shelf", shelf_id)
        conn.execute("UPDATE shelf SET deleted_at = ? WHERE id = ?", (ts, shelf_id))


def list_shelves(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.id, s.name, COUNT(b.id) AS book_count "
        "FROM shelf s LEFT JOIN book b ON b.shelf_id = s.id AND b.deleted_at IS NULL "
        "WHERE s.deleted_at IS NULL GROUP BY s.id ORDER BY s.norm_name, s.id"
    ).fetchall()
    return [dict(r) for r in rows]


def add_type(conn: sqlite3.Connection, name: str) -> int:
    text, key = _clean_name(name)
    ts = _now()
    with conn:
        _ensure_name_free(conn, "type", key, None)
        cur = conn.execute(
            "INSERT INTO type (name, norm_name, created_at) VALUES (?, ?, ?)", (text, key, ts)
        )
    return cur.lastrowid


def rename_type(conn: sqlite3.Connection, type_id: int, name: str) -> None:
    text, key = _clean_name(name)
    with conn:
        row = _live_named(conn, "type", type_id)
        _ensure_name_free(conn, "type", key, type_id)
        if text != row["name"]:
            conn.execute(
                "UPDATE type SET name = ?, norm_name = ? WHERE id = ?", (text, key, type_id)
            )


def delete_type(conn: sqlite3.Connection, type_id: int) -> None:
    """Soft delete. Existing book links stay; the type is hidden from lists and pickers."""
    ts = _now()
    with conn:
        _live_named(conn, "type", type_id)
        conn.execute("UPDATE type SET deleted_at = ? WHERE id = ?", (ts, type_id))


def list_types(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT t.id, t.name, COUNT(b.id) AS book_count "
        "FROM type t "
        "LEFT JOIN book_type bt ON bt.type_id = t.id "
        "LEFT JOIN book b ON b.id = bt.book_id AND b.deleted_at IS NULL "
        "WHERE t.deleted_at IS NULL GROUP BY t.id ORDER BY t.norm_name, t.id"
    ).fetchall()
    return [dict(r) for r in rows]


def set_book_shelf(conn: sqlite3.Connection, book_id: int, shelf_id: int | None) -> None:
    """Set or clear (None) a book's shelf. Writes one 'shelf' history row on change only."""
    ts = _now()
    with conn:
        book = _live_book(conn, book_id)
        if book is None:
            raise ValueError(f"book {book_id} not found")
        new_name = None
        if shelf_id is not None:
            new_name = _live_named(conn, "shelf", shelf_id)["name"]
        if book["shelf_id"] == shelf_id:
            return
        old_name = _name_of(conn, "shelf", book["shelf_id"])
        conn.execute(
            "UPDATE book SET shelf_id = ?, updated_at = ? WHERE id = ?", (shelf_id, ts, book_id)
        )
        _write_history(conn, book_id, [HistoryEntry("shelf", old_name, new_name)], ts)


def set_book_cover(
    conn: sqlite3.Connection, book_id: int, cover_file: str, cover_color: str
) -> None:
    """Store a book's cover file name and colour. Always writes one 'cover' history row."""
    ts = _now()
    with conn:
        book = _live_book(conn, book_id)
        if book is None:
            raise ValueError(f"book {book_id} not found")
        conn.execute(
            "UPDATE book SET cover_file = ?, cover_color = ?, updated_at = ? WHERE id = ?",
            (cover_file, cover_color, ts, book_id),
        )
        _write_history(
            conn, book_id, [HistoryEntry("cover", book["cover_file"], cover_file)], ts
        )


def set_book_types(conn: sqlite3.Connection, book_id: int, type_ids: list[int]) -> None:
    """Replace a book's live types with `type_ids`. One 'type' history row per added or removed type.

    Links to types that were soft-deleted earlier are left as they are.
    Writes nothing when the set is unchanged.
    """
    wanted_ids = list(dict.fromkeys(int(t) for t in type_ids))
    ts = _now()
    with conn:
        if _live_book(conn, book_id) is None:
            raise ValueError(f"book {book_id} not found")
        wanted = {tid: _live_named(conn, "type", tid)["name"] for tid in wanted_ids}
        current = {
            r["type_id"]: r["name"]
            for r in conn.execute(
                "SELECT bt.type_id, t.name FROM book_type bt JOIN type t ON t.id = bt.type_id "
                "WHERE bt.book_id = ? AND t.deleted_at IS NULL",
                (book_id,),
            ).fetchall()
        }
        removed = [tid for tid in current if tid not in wanted]
        added = [tid for tid in wanted if tid not in current]
        if not removed and not added:
            return
        for tid in removed:
            conn.execute(
                "DELETE FROM book_type WHERE book_id = ? AND type_id = ?", (book_id, tid)
            )
        for tid in added:
            conn.execute(
                "INSERT INTO book_type (book_id, type_id) VALUES (?, ?)", (book_id, tid)
            )
        entries = [HistoryEntry("type", current[tid], None) for tid in removed] + [
            HistoryEntry("type", None, wanted[tid]) for tid in added
        ]
        conn.execute("UPDATE book SET updated_at = ? WHERE id = ?", (ts, book_id))
        _write_history(conn, book_id, entries, ts)


def get_reading_status(conn: sqlite3.Connection, book_id: int) -> dict | None:
    """Stored reading status row of a book, or None when it has none yet."""
    row = conn.execute(
        "SELECT status, started_on, finished_on FROM reading_status WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def book_card_extras(conn: sqlite3.Connection, book_ids: Sequence[int]) -> dict[int, dict]:
    """Shelf name, live type names, finished date and cover fields for cards, keyed by book id.

    Kept apart from list_books, which only takes filter parameters.
    """
    extras: dict[int, dict] = {
        book_id: {
            "shelf": None,
            "types": [],
            "finished_on": None,
            "cover_file": None,
            "cover_color": None,
        }
        for book_id in book_ids
    }
    if not book_ids:
        return extras
    marks = ", ".join("?" for _ in book_ids)
    for row in conn.execute(
        f"SELECT id, cover_file, cover_color FROM book WHERE id IN ({marks})",
        list(book_ids),
    ):
        extras[row["id"]]["cover_file"] = row["cover_file"]
        extras[row["id"]]["cover_color"] = row["cover_color"]
    for row in conn.execute(
        f"SELECT b.id, s.name FROM book b JOIN shelf s ON s.id = b.shelf_id "
        f"WHERE b.id IN ({marks})",
        list(book_ids),
    ):
        extras[row["id"]]["shelf"] = row["name"]
    for row in conn.execute(
        "SELECT bt.book_id, t.name FROM book_type bt JOIN type t ON t.id = bt.type_id "
        f"WHERE t.deleted_at IS NULL AND bt.book_id IN ({marks}) ORDER BY t.norm_name, t.id",
        list(book_ids),
    ):
        extras[row["book_id"]]["types"].append(row["name"])
    for row in conn.execute(
        f"SELECT book_id, finished_on FROM reading_status WHERE book_id IN ({marks})",
        list(book_ids),
    ):
        extras[row["book_id"]]["finished_on"] = row["finished_on"]
    return extras


def get_book_shelf_and_types(conn: sqlite3.Connection, book_id: int) -> dict:
    """Shelf id and type chips of a book. A deleted shelf or deleted types are left out."""
    shelf_row = conn.execute(
        "SELECT b.shelf_id FROM book b JOIN shelf s ON s.id = b.shelf_id AND s.deleted_at IS NULL "
        "WHERE b.id = ?",
        (book_id,),
    ).fetchone()
    chips = [
        dict(row)
        for row in conn.execute(
            "SELECT t.id, t.name FROM book_type bt JOIN type t ON t.id = bt.type_id "
            "WHERE bt.book_id = ? AND t.deleted_at IS NULL ORDER BY t.norm_name, t.id",
            (book_id,),
        )
    ]
    return {
        "shelf_id": shelf_row["shelf_id"] if shelf_row is not None else None,
        "chips": chips,
    }


def reading_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Live books per reading status. A book without a status row counts as 'unread'."""
    counts = {status: 0 for status in READING_STATUSES}
    rows = conn.execute(
        "SELECT COALESCE(rs.status, 'unread') AS status, COUNT(*) AS n FROM book b "
        "LEFT JOIN reading_status rs ON rs.book_id = b.id "
        "WHERE b.deleted_at IS NULL GROUP BY 1"
    ).fetchall()
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + row["n"]
    return counts


def finished_per_year(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    """(year, count) of live books with status 'read' and a finished date, oldest year first."""
    rows = conn.execute(
        "SELECT CAST(substr(rs.finished_on, 1, 4) AS INTEGER) AS year, COUNT(*) AS n "
        "FROM reading_status rs JOIN book b ON b.id = rs.book_id "
        "WHERE b.deleted_at IS NULL AND rs.status = 'read' AND rs.finished_on IS NOT NULL "
        "GROUP BY year ORDER BY year"
    ).fetchall()
    return [(row["year"], row["n"]) for row in rows]


def count_books_by_type(conn: sqlite3.Connection) -> tuple[list[tuple[str, int]], int, int]:
    """Live books per live type (largest first), books with no type, and total live books."""
    rows = conn.execute(
        """
        SELECT t.name, COUNT(b.id) AS n
        FROM type t
        LEFT JOIN book_type bt ON bt.type_id = t.id
        LEFT JOIN book b ON b.id = bt.book_id AND b.deleted_at IS NULL
        WHERE t.deleted_at IS NULL
        GROUP BY t.id
        ORDER BY n DESC, t.name
        """
    ).fetchall()
    untyped = conn.execute(
        """
        SELECT COUNT(*) FROM book b
        WHERE b.deleted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM book_type bt WHERE bt.book_id = b.id)
        """
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM book WHERE deleted_at IS NULL").fetchone()[0]
    return [(row[0], row[1]) for row in rows], untyped, total


def books_without_types(conn: sqlite3.Connection) -> list[dict]:
    """Live books that have no type yet, with their titles and authors."""
    rows = conn.execute(
        """
        SELECT b.id, b.title FROM book b
        WHERE b.deleted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM book_type bt WHERE bt.book_id = b.id)
        ORDER BY b.id
        """
    ).fetchall()
    result = []
    for row in rows:
        authors = [
            a[0]
            for a in conn.execute(
                """
                SELECT a.name FROM book_author ba JOIN author a ON a.id = ba.author_id
                WHERE ba.book_id = ? ORDER BY ba.position
                """,
                (row[0],),
            ).fetchall()
        ]
        result.append({"id": row[0], "title": row[1], "authors": authors})
    return result


def ensure_type(conn: sqlite3.Connection, name: str) -> int:
    """Return the id of the live type with this name, creating it when missing."""
    key = norm(name)
    for row in conn.execute("SELECT id, norm_name FROM type WHERE deleted_at IS NULL").fetchall():
        if row[1] == key:
            return row[0]
    with conn:
        cursor = conn.execute(
            "INSERT INTO type (name, norm_name, created_at) VALUES (?, ?, ?)",
            (name, key, _now()),
        )
    return cursor.lastrowid


def attach_book_types(conn: sqlite3.Connection, book_id: int, type_ids: list[int]) -> None:
    """Add types to a book (existing links are kept). One history row per newly added type."""
    with conn:
        for type_id in type_ids:
            exists = conn.execute(
                "SELECT 1 FROM book_type WHERE book_id = ? AND type_id = ?", (book_id, type_id)
            ).fetchone()
            if exists:
                continue
            conn.execute("INSERT INTO book_type (book_id, type_id) VALUES (?, ?)", (book_id, type_id))
            name = conn.execute("SELECT name FROM type WHERE id = ?", (type_id,)).fetchone()[0]
            conn.execute(
                """
                INSERT INTO history (record_type, record_id, field, old_value, new_value, changed_at)
                VALUES ('book', ?, 'type', NULL, ?, ?)
                """,
                (book_id, name, _now()),
            )
