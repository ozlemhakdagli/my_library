import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app

HX = {"HX-Request": "true"}
QUICK_LABELS_EN = ("Mark as read", "Start reading", "Abandon")
QUICK_LABELS_TR = ("Okundu olarak işaretle", "Okumaya başla", "Yarım bırak")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "card_polish.db")
    conn = db.connect(path)
    db.init_schema(conn)
    today = date(2026, 10, 17)
    read_id = db.add_book(conn, title="Okunan Kitap", author_names=["Ayşe Yılmaz"])
    db.set_reading_status(conn, read_id, "read", finished_on="2026-10-01", today=today)
    reading_id = db.add_book(conn, title="Okuyan Kitap", author_names=["Can Demir"])
    db.set_reading_status(conn, reading_id, "reading", started_on="2026-10-05", today=today)
    dropped_id = db.add_book(conn, title="Bırakılan Kitap", author_names=["Deniz Kaya"])
    db.set_reading_status(conn, dropped_id, "abandoned", today=today)
    db.add_book(conn, title="Rafsız Kitap", author_names=["Ali Veli"])
    shelved_id = db.add_book(conn, title="Raflı Kitap", author_names=["Ali Veli"])
    db.set_book_shelf(conn, shelved_id, db.add_shelf(conn, "Roman"))
    conn.close()
    return path


def _client(db_path, lang="en"):
    return TestClient(create_app(Settings(port=8765, db_path=db_path, default_lang=lang)))


def _fragment(db_path, lang="en"):
    return _client(db_path, lang).get("/", headers=HX).text


def _cards(html):
    return re.split(r"<li\b", html)[1:]


def _card(html, title):
    return next(card for card in _cards(html) if title in card)


def _status_label(card):
    match = re.search(r'<span data-status-label class="([^"]*)"[^>]*>([^<]*)</span>', card)
    assert match, "status label missing"
    return match.group(1), match.group(2).strip()


def test_list_page_has_no_quick_status_forms(db_path):
    for lang in ("en", "tr"):
        assert "/status/quick" not in _client(db_path, lang).get("/").text
        assert "/status/quick" not in _fragment(db_path, lang)


@pytest.mark.parametrize(("lang", "labels"), [("en", QUICK_LABELS_EN), ("tr", QUICK_LABELS_TR)])
def test_list_cards_have_no_quick_action_buttons(db_path, lang, labels):
    html = _fragment(db_path, lang)
    assert _cards(html)
    for label in labels:
        assert label not in html


def test_unshelved_card_shows_no_shelf_text(db_path):
    en = _card(_fragment(db_path, "en"), "Rafsız Kitap")
    tr = _card(_fragment(db_path, "tr"), "Rafsız Kitap")
    assert "No shelf" not in en
    assert "Shelf" not in en
    assert "Klasör" not in tr
    assert "Klasörsüz" not in tr
    assert "No shelf" not in _fragment(db_path, "en")


def test_shelved_card_shows_only_shelf_name_without_prefix(db_path):
    en = _card(_fragment(db_path, "en"), "Raflı Kitap")
    tr = _card(_fragment(db_path, "tr"), "Raflı Kitap")
    assert re.search(r">\s*Roman\s*<", en)
    assert "Shelf:" not in en
    assert re.search(r">\s*Roman\s*<", tr)
    assert "Klasör:" not in tr


@pytest.mark.parametrize(
    ("title", "lang", "expected"),
    [
        ("Rafsız Kitap", "en", "Not read"),
        ("Rafsız Kitap", "tr", "Okunmadı"),
        ("Okuyan Kitap", "en", "Reading"),
        ("Okuyan Kitap", "tr", "Okuyorum"),
        ("Bırakılan Kitap", "en", "Dropped"),
        ("Bırakılan Kitap", "tr", "Bırakıldı"),
        ("Okunan Kitap", "en", "Read · 2026-10-01"),
        ("Okunan Kitap", "tr", "Okundu · 2026-10-01"),
    ],
)
def test_status_label_under_card_text(db_path, title, lang, expected):
    _, text = _status_label(_card(_fragment(db_path, lang), title))
    assert text == expected


@pytest.mark.parametrize("lang", ["en", "tr"])
def test_status_label_is_single_line(db_path, lang):
    for title in ("Okunan Kitap", "Rafsız Kitap"):
        classes, _ = _status_label(_card(_fragment(db_path, lang), title))
        assert "truncate" in classes.split()
