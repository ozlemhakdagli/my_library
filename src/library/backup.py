import csv
import os
import sqlite3
from contextlib import closing
from datetime import datetime

from library import db

CSV_COLUMNS = ("id", "title", "subtitle", "authors", "publisher", "status", "on_loan", "note")


def make_backup(db_path: str, backup_dir: str, now: datetime) -> str:
    """Copy the database into ``backup_dir`` with SQLite's online backup API.

    Returns the full path of the new file, named ``library-YYYYMMDD-HHMMSS.db``.
    """
    os.makedirs(backup_dir, exist_ok=True)
    target = os.path.join(backup_dir, now.strftime("library-%Y%m%d-%H%M%S.db"))
    with closing(sqlite3.connect(db_path)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    return target


def export_csv(conn: sqlite3.Connection, out_path: str) -> int:
    """Write every non-deleted book to ``out_path`` as UTF-8 CSV with a BOM.

    Returns the number of book rows written (header not counted).
    """
    ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM book WHERE deleted_at IS NULL ORDER BY id")
    ]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for book_id in ids:
            book = db.get_book(conn, book_id)
            writer.writerow(
                [
                    book["id"],
                    book["title"],
                    book["subtitle"],
                    "; ".join(book["authors"]),
                    book["publisher"],
                    book["status"] or "",
                    "yes" if book["loan"] is not None else "no",
                    book["note"],
                ]
            )
    return len(ids)
