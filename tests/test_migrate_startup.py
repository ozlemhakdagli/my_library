import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from library.config import Settings
from library.web.app import create_app
from test_migrate import V1_DDL

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _make_v1_db(path: Path) -> None:
    raw = sqlite3.connect(path)
    raw.executescript(V1_DDL)
    raw.execute(
        "INSERT INTO book (id, title, norm_title, review_status, created_at, updated_at) "
        "VALUES (1, 'Sefiller', 'sefiller', 'ok', '2024-01-01T10:00:00+00:00', '2024-01-01T10:00:00+00:00')"
    )
    raw.commit()
    raw.close()


def _book_columns(path: Path) -> set[str]:
    raw = sqlite3.connect(path)
    try:
        return {r[1] for r in raw.execute("PRAGMA table_info(book)")}
    finally:
        raw.close()


def test_old_database_is_migrated_on_app_startup(tmp_path):
    db_path = tmp_path / "library.db"
    _make_v1_db(db_path)
    settings = Settings(port=8765, db_path=str(db_path), default_lang="en", backup_dir=str(tmp_path / "backups"))

    client = TestClient(create_app(settings))
    response = client.get("/")

    assert response.status_code == 200
    assert "shelf_id" in _book_columns(db_path)


def test_migrate_cli_upgrades_database_and_reports_changes(tmp_path):
    db_path = tmp_path / "library.db"
    _make_v1_db(db_path)
    env = {**os.environ, "LIBRARY_DB": str(db_path), "PYTHONPATH": str(SRC_DIR)}

    first = subprocess.run(
        [sys.executable, "-m", "library.migrate"], env=env, capture_output=True, text=True, timeout=60
    )
    second = subprocess.run(
        [sys.executable, "-m", "library.migrate"], env=env, capture_output=True, text=True, timeout=60
    )

    assert first.returncode == 0, first.stderr
    assert "table:shelf" in first.stdout
    assert "column:book.shelf_id" in first.stdout
    assert "shelf_id" in _book_columns(db_path)
    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == "no changes"
