import json

from library import importer
from library.db import connect
from library.importer import main


def _write_raw(raw_dir):
    record = {
        "photo": "IMG_9001.jpg",
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
    }
    (raw_dir / "batch_test.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


def test_cli_prints_counts_and_exits_zero(tmp_path, monkeypatch, capsys):
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_raw(raw)
    db_path = str(tmp_path / "library.db")
    monkeypatch.setattr(importer, "EXPECTED_COUNTS", {"main_books": 1, "review_items": 0, "photos": 1})

    assert main(["--raw", str(raw), "--db", db_path]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["1 books", "0 review items", "1 photos"]


def test_cli_mismatch_exits_nonzero_and_writes_nothing(tmp_path, capsys):
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_raw(raw)
    db_path = str(tmp_path / "library.db")

    assert main(["--raw", str(raw), "--db", db_path]) == 1
    assert "expected 431" in capsys.readouterr().err
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM book").fetchone()[0] == 0
    conn.close()
