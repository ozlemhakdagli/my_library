"""Idempotent import of data/raw/*.jsonl into the library database.

Books, photos and review items are written in one transaction. The final
counts are checked before commit; on mismatch everything is rolled back.
The raw files are only read.
"""
import glob
import json
import os
import sqlite3
from dataclasses import dataclass

from library import db, merge
from library.merge import UNREADABLE_TITLE, Book, MergeResult, RawBook, group_books
from library.norm import norm

EXPECTED_COUNTS = {"main_books": 431, "review_items": 78, "photos": 410}

UNREADABLE_REASON = "unreadable"
REASON_EN = {
    "Düşük güven": "low confidence",
    "Orta güven": "medium confidence",
    "Yazar eksik": "author missing",
}


class ImportCountMismatch(Exception):
    """Import counts differ from the expected counts. Nothing is committed."""


@dataclass(frozen=True)
class ImportReport:
    main_books: int
    review_items: int
    photos: int
    merged_records: int
    unreadable: int


def check_counts(report: ImportReport, expected: dict[str, int]) -> None:
    diffs = [
        f"{key}: expected {want}, got {getattr(report, key)}"
        for key, want in expected.items()
        if getattr(report, key) != want
    ]
    if diffs:
        raise ImportCountMismatch("; ".join(diffs))


def load_records(raw_dir: str) -> list[RawBook]:
    """All book entries from data/raw/*.jsonl, files in sorted order."""
    records: list[RawBook] = []
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                photo_rec = json.loads(line)
                for b in photo_rec.get("books") or []:
                    records.append(RawBook(
                        title=b.get("title", ""),
                        subtitle=b.get("subtitle", ""),
                        author=b.get("author", ""),
                        publisher=b.get("publisher", ""),
                        kind=b.get("kind", ""),
                        confidence=b.get("confidence", ""),
                        note=b.get("note", ""),
                        photo=photo_rec["photo"],
                        photo_note=photo_rec.get("photo_note", ""),
                    ))
    return records


def _report(records: list[RawBook], result: MergeResult) -> ImportReport:
    return ImportReport(
        main_books=len(result.main),
        review_items=len(result.review),
        photos=len({r.photo for r in records}),
        merged_records=len(result.merged),
        unreadable=result.unreadable,
    )


def _existing_snapshot(conn: sqlite3.Connection) -> tuple[dict[int, str], set[str]]:
    """State before this run: {book id: norm of its originally imported title}, and all photo file names.

    The original title is the first history row for `title` (written at creation, old_value NULL),
    so editing a title later does not make the book look new.
    Soft-deleted books are included, so a deleted book is not re-created.
    """
    origin: dict[int, str] = {}
    rows = conn.execute(
        "SELECT record_id, new_value FROM history WHERE record_type = 'book' "
        "AND field = 'title' AND old_value IS NULL ORDER BY id"
    ).fetchall()
    for row in rows:
        origin.setdefault(row["record_id"], norm(row["new_value"] or ""))
    files = {row["file_name"] for row in conn.execute("SELECT file_name FROM photo")}
    return origin, files


def _insert_book(conn: sqlite3.Connection, book: Book, ts: str) -> int:
    title = book.title.strip()
    publisher_text = db._text(book.publisher)
    subtitle_text = db._text(book.subtitle)
    note_text = db._text(book.note)
    publisher_id = db._get_or_create_publisher(conn, publisher_text) if publisher_text else None
    review_status = "needs review" if merge._control_reasons(book) else "ok"
    cur = conn.execute(
        "INSERT INTO book (title, subtitle, norm_title, publisher_id, review_status, note, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (title, subtitle_text, norm(title), publisher_id, review_status, note_text, ts, ts),
    )
    book_id = cur.lastrowid
    names = db._split_authors([book.author])
    db._set_authors(conn, book_id, names)
    initial = {
        "title": title,
        "subtitle": subtitle_text,
        "note": note_text,
        "review_status": review_status,
        "publisher": publisher_text,
        "authors": "; ".join(names) or None,
    }
    entries = [db.HistoryEntry(f, None, v) for f, v in initial.items() if v is not None]
    db._write_history(conn, book_id, entries, ts)
    return book_id


def _write_books(conn: sqlite3.Connection, result: MergeResult, ts: str) -> dict[int, int]:
    """Returns {id(Book): book row id} for every main book, new or already present."""
    ids: dict[int, int] = {}
    origin, files = _existing_snapshot(conn)
    claimed: set[int] = set()
    for book in result.main:
        key = norm(book.title)
        has_photo = any(f in files for f in book.photos)
        match = next(
            (bid for bid in sorted(origin)
             if bid not in claimed and origin[bid] == key and has_photo),
            None,
        )
        if match is not None:
            claimed.add(match)
            ids[id(book)] = match
        else:
            ids[id(book)] = _insert_book(conn, book, ts)
    return ids


def _write_photos(
    conn: sqlite3.Connection, records: list[RawBook], result: MergeResult, ids: dict[int, int]
) -> None:
    """One photo row per distinct file name.

    The row links to the book of the first readable record with that file. A file
    that only appears on unreadable records gets book_id NULL.
    """
    book_of_record: dict[int, int] = {}
    for book in result.main:
        for member in book.members:
            book_of_record[id(member)] = ids[id(book)]

    chosen: dict[str, RawBook] = {}
    for r in records:
        cur = chosen.get(r.photo)
        if cur is None or (cur.title == UNREADABLE_TITLE and r.title != UNREADABLE_TITLE):
            chosen[r.photo] = r

    existing = {row["file_name"] for row in conn.execute("SELECT file_name FROM photo")}
    for file_name, r in chosen.items():
        if file_name in existing:
            continue
        book_id = None if r.title == UNREADABLE_TITLE else book_of_record[id(r)]
        conn.execute(
            "INSERT INTO photo (book_id, file_name, kind, confidence) VALUES (?, ?, ?, ?)",
            (book_id, file_name, r.kind, r.confidence),
        )


def _review_reason(reasons: list[str]) -> str:
    return ", ".join(REASON_EN.get(part.strip(), part.strip()) for part in reasons)


def _write_review(
    conn: sqlite3.Connection, records: list[RawBook], result: MergeResult, ids: dict[int, int]
) -> None:
    for book in result.main:
        reasons = merge._control_reasons(book)
        if not reasons:
            continue
        book_id = ids[id(book)]
        if conn.execute("SELECT 1 FROM review_item WHERE book_id = ?", (book_id,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO review_item (book_id, reason, photo_file) VALUES (?, ?, NULL)",
            (book_id, _review_reason(reasons)),
        )

    # One review row per unreadable record. Add only the rows still missing for each photo.
    unreadable_per_photo: dict[str, int] = {}
    for r in records:
        if r.title == UNREADABLE_TITLE:
            unreadable_per_photo[r.photo] = unreadable_per_photo.get(r.photo, 0) + 1
    for photo, wanted in unreadable_per_photo.items():
        have = conn.execute(
            "SELECT COUNT(*) AS n FROM review_item WHERE book_id IS NULL AND photo_file = ?",
            (photo,),
        ).fetchone()["n"]
        for _ in range(wanted - have):
            conn.execute(
                "INSERT INTO review_item (book_id, reason, photo_file) VALUES (NULL, ?, ?)",
                (UNREADABLE_REASON, photo),
            )


def import_raw(
    conn: sqlite3.Connection, raw_dir: str, expected: dict[str, int] | None = None
) -> ImportReport:
    """Import all raw records into the database. Safe to run again.

    If `expected` is given, the counts are checked before commit. On mismatch,
    ImportCountMismatch is raised and nothing is written.
    """
    db.init_schema(conn)
    records = load_records(raw_dir)
    result = group_books(records)
    report = _report(records, result)
    ts = db._now()
    try:
        ids = _write_books(conn, result, ts)
        _write_photos(conn, records, result, ids)
        _write_review(conn, records, result, ids)
        if expected is not None:
            check_counts(report, expected)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return report
