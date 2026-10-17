import json
from pathlib import Path

import pytest

from library import db
from library.db import connect, init_schema
from library.importer import (
    EXPECTED_COUNTS,
    ImportCountMismatch,
    ImportReport,
    check_counts,
    import_raw,
)

REAL_RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

BATCH_01 = [
    {
        "photo": "IMG_0001.jpg",
        "photo_note": "",
        "books": [
            {
                "title": "Kürk Mantolu Madonna",
                "subtitle": "",
                "author": "Sabahattin Ali",
                "publisher": "Yapı Kredi",
                "kind": "cover",
                "confidence": "high",
                "note": "",
            }
        ],
    },
    {
        "photo": "IMG_0002.jpg",
        "photo_note": "sol kenar",
        "books": [
            {
                "title": "[okunamadı]",
                "subtitle": "",
                "author": "",
                "publisher": "",
                "kind": "spine",
                "confidence": "low",
                "note": "",
            }
        ],
    },
]

BATCH_02 = [
    {
        "photo": "IMG_0003.jpg",
        "photo_note": "",
        "books": [
            {
                "title": "Yapay Zeka",
                "subtitle": "",
                "author": "",
                "publisher": "",
                "kind": "cover",
                "confidence": "medium",
                "note": "",
            }
        ],
    },
    {
        "photo": "IMG_0004.jpg",
        "photo_note": "",
        "books": [
            {
                "title": "kürk mantolu madonna",
                "subtitle": "",
                "author": "Sabahattin Ali",
                "publisher": "Yapı Kredi",
                "kind": "spine",
                "confidence": "high",
                "note": "",
            }
        ],
    },
]

EXPECTED_FIXTURE_COUNTS = {"main_books": 2, "review_items": 2, "photos": 4}


def _write_batch(path: Path, name: str, records: list[dict]) -> None:
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    (path / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def raw_dir(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    _write_batch(d, "batch_01.jsonl", BATCH_01)
    _write_batch(d, "batch_02.jsonl", BATCH_02)
    return d


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "lib.db"))
    init_schema(c)
    yield c
    c.close()


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def test_import_report_counts(conn, raw_dir):
    report = import_raw(conn, str(raw_dir))
    assert report == ImportReport(
        main_books=2, review_items=2, photos=4, merged_records=1, unreadable=1
    )


def test_unreadable_record_becomes_review_item_not_book(conn, raw_dir):
    import_raw(conn, str(raw_dir))
    titles = {r["title"] for r in conn.execute("SELECT title FROM book")}
    assert titles == {"Kürk Mantolu Madonna", "Yapay Zeka"}

    review = conn.execute(
        "SELECT book_id, photo_file, reason FROM review_item WHERE photo_file = 'IMG_0002.jpg'"
    ).fetchall()
    assert len(review) == 1
    assert review[0]["book_id"] is None
    assert review[0]["reason"] == "unreadable"

    photo = conn.execute(
        "SELECT book_id FROM photo WHERE file_name = 'IMG_0002.jpg'"
    ).fetchone()
    assert photo is not None
    assert photo["book_id"] is None


def test_importing_twice_creates_no_duplicates(conn, raw_dir):
    first = import_raw(conn, str(raw_dir))
    before = (_count(conn, "book"), _count(conn, "photo"), _count(conn, "review_item"))
    second = import_raw(conn, str(raw_dir))
    after = (_count(conn, "book"), _count(conn, "photo"), _count(conn, "review_item"))
    assert first == second
    assert before == after
    assert after == (2, 4, 2)


def test_title_edited_in_app_is_not_duplicated_on_reimport(conn, raw_dir):
    import_raw(conn, str(raw_dir))
    book_id = conn.execute(
        "SELECT id FROM book WHERE title = 'Kürk Mantolu Madonna'"
    ).fetchone()["id"]
    db.update_book(conn, book_id, {"title": "Kürk Mantolu Madonna (düzeltilmiş)"})

    import_raw(conn, str(raw_dir))
    assert _count(conn, "book") == 2
    assert _count(conn, "photo") == 4


def test_import_after_first_batch_only_completes_without_duplicates(tmp_path, conn):
    partial = tmp_path / "partial"
    partial.mkdir()
    _write_batch(partial, "batch_01.jsonl", BATCH_01)
    import_raw(conn, str(partial))

    full = tmp_path / "full"
    full.mkdir()
    _write_batch(full, "batch_01.jsonl", BATCH_01)
    _write_batch(full, "batch_02.jsonl", BATCH_02)
    report = import_raw(conn, str(full))

    assert report.main_books == 2
    assert _count(conn, "book") == 2
    assert _count(conn, "photo") == 4
    assert _count(conn, "review_item") == 2
    kurk_photos = {
        r["file_name"]
        for r in conn.execute(
            "SELECT p.file_name FROM photo p JOIN book b ON b.id = p.book_id "
            "WHERE b.title = 'Kürk Mantolu Madonna'"
        )
    }
    assert kurk_photos == {"IMG_0001.jpg", "IMG_0004.jpg"}


def test_check_counts_raises_on_difference():
    report = ImportReport(main_books=2, review_items=2, photos=4, merged_records=1, unreadable=1)
    check_counts(report, EXPECTED_FIXTURE_COUNTS)
    with pytest.raises(ImportCountMismatch):
        check_counts(report, {"main_books": 3})


def test_count_mismatch_rolls_back_everything(conn, raw_dir):
    with pytest.raises(ImportCountMismatch):
        import_raw(conn, str(raw_dir), expected={"main_books": 3, "review_items": 2, "photos": 4})
    assert _count(conn, "book") == 0
    assert _count(conn, "photo") == 0
    assert _count(conn, "review_item") == 0
    assert _count(conn, "history") == 0


def test_import_with_matching_expected_counts_commits(conn, raw_dir):
    import_raw(conn, str(raw_dir), expected=EXPECTED_FIXTURE_COUNTS)
    assert _count(conn, "book") == 2


@pytest.mark.skipif(not REAL_RAW.is_dir(), reason="data/raw not present")
def test_real_raw_data_matches_expected_counts(tmp_path):
    # Read-only use of data/raw: the importer never writes there.
    db_path = tmp_path / "real.db"
    c = connect(str(db_path))
    try:
        init_schema(c)
        report = import_raw(c, str(REAL_RAW), expected=EXPECTED_COUNTS)
        assert report.main_books == 431
        assert report.review_items == 78
        assert report.photos == 410
        assert _count(c, "book") == 431
        assert _count(c, "photo") == 410
        assert _count(c, "review_item") == 78
        again = import_raw(c, str(REAL_RAW), expected=EXPECTED_COUNTS)
        assert again == report
        assert _count(c, "book") == 431
    finally:
        c.close()
