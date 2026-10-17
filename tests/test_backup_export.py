import csv
import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from library import db
from library.backup import export_csv, make_backup
from library.config import Settings
from library.web.app import create_app

NOW = datetime(2026, 10, 17, 21, 5, 9)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "library.db")
    conn = db.connect(path)
    db.init_schema(conn)
    db.add_book(
        conn,
        title="Çığlık ve İş",
        subtitle="Ömer",
        author_names=["Ömer Seyfettin", "Şükrü Saracoğlu"],
        publisher="Ğüşiöç Yayınevi",
        note="ş ğ ı İ",
    )
    db.add_book(conn, title="Silinecek Kitap")
    db.add_book(conn, title="Lonely Book")
    conn.close()
    return path


def _delete_by_title(db_path, title):
    conn = db.connect(db_path)
    try:
        book_id = conn.execute("SELECT id FROM book WHERE title = ?", (title,)).fetchone()["id"]
        db.soft_delete_book(conn, book_id)
    finally:
        conn.close()


def _read_csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def test_make_backup_file_contains_books(db_path, tmp_path):
    backup_dir = str(tmp_path / "backups")
    path = make_backup(db_path, backup_dir, NOW)

    assert path == str(tmp_path / "backups" / "library-20261017-210509.db")
    conn = sqlite3.connect(path)
    try:
        titles = {r[0] for r in conn.execute("SELECT title FROM book")}
    finally:
        conn.close()
    assert "Lonely Book" in titles


def test_export_csv_has_bom_header_and_row_count(db_path, tmp_path):
    out = str(tmp_path / "books.csv")
    conn = db.connect(db_path)
    try:
        count = export_csv(conn, out)
    finally:
        conn.close()

    assert count == 3
    with open(out, "rb") as fh:
        assert fh.read(3) == b"\xef\xbb\xbf"
    rows = _read_csv_rows(out)
    assert rows[0] == ["id", "title", "subtitle", "authors", "publisher", "status", "on_loan", "note"]
    assert len(rows) == 4


def test_export_csv_excludes_deleted_books(db_path, tmp_path):
    _delete_by_title(db_path, "Silinecek Kitap")
    out = str(tmp_path / "books.csv")
    conn = db.connect(db_path)
    try:
        count = export_csv(conn, out)
    finally:
        conn.close()

    rows = _read_csv_rows(out)
    titles = [r[1] for r in rows[1:]]
    assert count == 2
    assert "Silinecek Kitap" not in titles
    assert len(rows) == 3


def test_export_csv_keeps_turkish_characters(db_path, tmp_path):
    out = str(tmp_path / "books.csv")
    conn = db.connect(db_path)
    try:
        export_csv(conn, out)
    finally:
        conn.close()

    row = next(r for r in _read_csv_rows(out) if r[1] == "Çığlık ve İş")
    assert row[2] == "Ömer"
    assert row[3] == "Ömer Seyfettin; Şükrü Saracoğlu"
    assert row[4] == "Ğüşiöç Yayınevi"
    assert row[7] == "ş ğ ı İ"


def test_export_csv_on_loan_column(db_path, tmp_path):
    conn = db.connect(db_path)
    try:
        book_id = conn.execute("SELECT id FROM book WHERE title = 'Lonely Book'").fetchone()["id"]
        db.lend_book(conn, book_id, "Ali", "2026-10-01")
        out = str(tmp_path / "books.csv")
        export_csv(conn, out)
    finally:
        conn.close()

    row = next(r for r in _read_csv_rows(out) if r[1] == "Lonely Book")
    assert row[6] == "yes"


@pytest.fixture
def client(db_path, tmp_path):
    settings = Settings(
        port=8765,
        db_path=db_path,
        default_lang="en",
        backup_dir=str(tmp_path / "backups"),
    )
    return TestClient(create_app(settings))


def test_export_csv_endpoint(client):
    response = client.get("/settings/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    first_line = response.content.decode("utf-8-sig").splitlines()[0]
    assert first_line == "id,title,subtitle,authors,publisher,status,on_loan,note"


def test_settings_page_renders_in_both_languages(client):
    en = client.get("/settings")
    assert en.status_code == 200
    assert "Backup" in en.text
    tr = client.get("/settings?lang=tr")
    assert tr.status_code == 200
    assert "Yedek" in tr.text


def test_backup_endpoint_writes_file_and_shows_path(client, tmp_path):
    response = client.post("/settings/backup")
    assert response.status_code == 200
    backups = list((tmp_path / "backups").glob("library-*.db"))
    assert len(backups) == 1
    assert str(backups[0]) in response.text


def test_language_valid_value_sets_cookie(client):
    response = client.post("/settings/language", data={"lang": "tr"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/settings")
    assert "lang=tr" in response.headers["set-cookie"]


def test_language_invalid_value_is_rejected(client):
    response = client.post("/settings/language", data={"lang": "fr"}, follow_redirects=False)
    assert response.status_code == 400
    assert "lang=" not in response.headers.get("set-cookie", "")
