import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app

WEB = Path(__file__).resolve().parent.parent / "src" / "library" / "web"
HX = {"HX-Request": "true"}


@pytest.fixture
def seeded(tmp_path):
    """Four books: shelf and type combinations plus reading statuses. Returns (path, ids)."""
    path = str(tmp_path / "v2.db")
    conn = db.connect(path)
    db.init_schema(conn)
    roman = db.add_shelf(conn, "Roman")
    felsefe = db.add_shelf(conn, "Felsefe")
    tip_x = db.add_type(conn, "Kağıt")
    tip_y = db.add_type(conn, "Dijital")
    tip_z = db.add_type(conn, "Sesli")

    alpha = db.add_book(conn, title="Alpha Title", author_names=["Yazar Bir"])
    bravo = db.add_book(conn, title="Bravo Title")
    charlie = db.add_book(conn, title="Charlie Title")
    delta = db.add_book(conn, title="Delta Title")

    db.set_book_shelf(conn, alpha, roman)
    db.set_book_shelf(conn, bravo, felsefe)
    db.set_book_types(conn, alpha, [tip_x])
    db.set_book_types(conn, bravo, [tip_y])
    db.set_book_types(conn, charlie, [tip_x])
    db.set_book_types(conn, delta, [tip_y, tip_z])

    db.set_reading_status(conn, alpha, "read", "2026-01-02", "2026-01-10")
    db.set_reading_status(conn, bravo, "unread")
    db.set_reading_status(conn, charlie, "unread")
    db.set_reading_status(conn, delta, "read", None, "2026-03-05")
    conn.close()
    return path, {"roman": roman, "felsefe": felsefe, "kagit": tip_x, "dijital": tip_y}


@pytest.fixture
def client(seeded):
    path, _ = seeded
    return TestClient(create_app(Settings(port=8765, db_path=path, default_lang="en")))


def titles_in(text: str) -> set[str]:
    return {name for name in ("Alpha Title", "Bravo Title", "Charlie Title", "Delta Title")
            if name in text}


def test_full_page_links_local_css_and_htmx(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<html" in response.text
    # The href carries a ?v=<version> cache-busting query string.
    assert re.search(r'<link[^>]*href="/static/app\.css\?v=', response.text)
    assert re.search(r'<script[^>]*src="/static/htmx\.min\.js"', response.text)


def test_htmx_request_returns_only_results_fragment(client):
    response = client.get("/", headers=HX)
    assert response.status_code == 200
    assert "<html" not in response.text
    assert "app.css" not in response.text
    assert 'id="results"' in response.text
    assert "Alpha Title" in response.text


def test_filter_form_targets_results_with_htmx(client):
    text = client.get("/").text
    assert 'hx-get="/"' in text
    assert 'hx-target="#results"' in text
    assert 'hx-push-url="true"' in text


def test_shelf_filter_by_id(client, seeded):
    _, ids = seeded
    text = client.get("/", params={"shelf": ids["roman"]}, headers=HX).text
    assert titles_in(text) == {"Alpha Title"}


def test_shelf_filter_none_matches_books_without_shelf(client):
    text = client.get("/", params={"shelf": "none"}, headers=HX).text
    assert titles_in(text) == {"Charlie Title", "Delta Title"}


def test_invalid_shelf_value_is_ignored(client):
    text = client.get("/", params={"shelf": "abc"}, headers=HX).text
    assert titles_in(text) == {"Alpha Title", "Bravo Title", "Charlie Title", "Delta Title"}


def test_multiple_types_match_any_type(client, seeded):
    _, ids = seeded
    text = client.get(
        "/", params={"type": [ids["kagit"], ids["dijital"]]}, headers=HX
    ).text
    assert titles_in(text) == {"Alpha Title", "Bravo Title", "Charlie Title", "Delta Title"}


def test_single_type_filter(client, seeded):
    _, ids = seeded
    text = client.get("/", params={"type": ids["kagit"]}, headers=HX).text
    assert titles_in(text) == {"Alpha Title", "Charlie Title"}


def test_types_are_or_and_status_is_and(client, seeded):
    _, ids = seeded
    # Types kagit OR dijital: Alpha, Bravo, Charlie, Delta. Status read: Alpha, Delta.
    text = client.get(
        "/",
        params={"type": [ids["kagit"], ids["dijital"]], "status": "read"},
        headers=HX,
    ).text
    assert titles_in(text) == {"Alpha Title", "Delta Title"}


def test_shelf_and_status_combine_with_and(client, seeded):
    _, ids = seeded
    text = client.get(
        "/", params={"shelf": ids["felsefe"], "status": "read"}, headers=HX
    ).text
    assert titles_in(text) == set()


def test_card_shows_read_badge_with_finished_date(client):
    text = client.get("/", headers=HX).text
    assert "Read · 2026-01-10" in text
    assert "Read · 2026-03-05" in text


def test_card_shows_shelf_and_type_names(client):
    text = client.get("/", headers=HX).text
    assert "Roman" in text
    assert "Sesli" in text


def test_turkish_filter_labels(client):
    text = client.get("/", params={"lang": "tr"}).text
    assert "Filtreler" in text
    assert "Klasör" in text


def test_mobile_container_has_side_padding_and_no_fixed_wide_widths():
    base = (WEB / "templates" / "base.html").read_text(encoding="utf-8")
    main_tag = re.search(r"<main[^>]*>", base).group(0)
    assert "px-4" in main_tag

    fixed_widths = []
    for template in (WEB / "templates").glob("*.html"):
        content = template.read_text(encoding="utf-8")
        for match in re.finditer(r"(?:min-)?w-\[(\d+)px\]|width:\s*(\d+)px", content):
            width = int(match.group(1) or match.group(2))
            if width > 375:
                fixed_widths.append(f"{template.name}: {match.group(0)}")
    assert fixed_widths == []
