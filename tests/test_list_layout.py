import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.i18n import DICTIONARIES
from library.web.app import create_app

WEB = Path(__file__).resolve().parent.parent / "src" / "library" / "web"
TEMPLATES = ["base.html", "list.html", "_results.html"]
HX = {"HX-Request": "true"}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "layout.db")
    conn = db.connect(path)
    db.init_schema(conn)
    db.add_book(conn, title="yapay zeka", author_names=["Stuart Russell"], publisher="Pearson")
    db.add_book(conn, title="Lonely Book")
    conn.close()
    return path


def _client(db_path, lang="en"):
    return TestClient(create_app(Settings(port=8765, db_path=db_path, default_lang=lang)))


def _template_text():
    return "\n".join((WEB / "templates" / name).read_text(encoding="utf-8") for name in TEMPLATES)


def test_filter_panel_is_details_drawer(db_path):
    html = _client(db_path).get("/").text
    assert re.search(r'<details[^>]*class="[^"]*filter-panel', html)
    assert "<summary" in html
    assert "lg:hidden" in html


def test_filter_panel_is_sticky_on_wide_screens(db_path):
    html = _client(db_path).get("/").text
    assert "lg:sticky" in html


def test_search_field_is_round_and_named_q(db_path):
    html = _client(db_path).get("/").text
    assert re.search(r'<input type="search" name="q"', html)
    assert "rounded-full" in html
    assert "<svg" in html


def test_filter_form_targets_results(db_path):
    html = _client(db_path).get("/").text
    form = re.search(r'<form id="filters"[^>]*>', html).group(0)
    assert 'hx-get="/"' in form
    assert 'hx-target="#results"' in form
    assert 'hx-push-url="true"' in form


def test_htmx_request_returns_only_fragment(db_path):
    text = _client(db_path).get("/", headers=HX).text
    assert "<html" not in text
    assert "<details" not in text
    assert "app.css" not in text
    assert 'id="results"' in text
    assert "yapay zeka" in text


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "No books match these filters."), ("tr", "Bu filtrelerle eşleşen kitap yok.")],
)
def test_empty_state_text_in_both_languages(db_path, lang, expected):
    text = _client(db_path, lang).get("/", params={"q": "zzz-no-match"}, headers=HX).text
    assert expected in text
    assert "yapay zeka" not in text


def test_active_filter_chips_and_count(db_path):
    text = _client(db_path).get("/", params={"q": "yapay", "loan": "1"}, headers=HX).text
    assert "Active filters · 2 selected" in text
    assert "Search: yapay" in text
    assert "Loan" in text


def test_pagination_uses_outline_pills(tmp_path):
    path = str(tmp_path / "many.db")
    conn = db.connect(path)
    db.init_schema(conn)
    for i in range(51):
        db.add_book(conn, title=f"Book {i:03d}")
    conn.close()
    html = _client(path).get("/").text
    assert "rounded-full border border-accent" in html
    assert "Next" in html


def test_turkish_labels_render(db_path):
    html = _client(db_path, "tr").get("/").text
    assert "Filtreler" in html
    assert "Kitaplar" in html
    assert 'name="q"' in html


def test_layout_templates_use_no_hardcoded_colors():
    text = _template_text()
    palette = (
        r"\b(?:bg|text|border|ring|outline|fill|stroke|divide|accent|shadow|from|to|via|placeholder|decoration)-"
        r"(?:black|white|gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|"
        r"sky|blue|indigo|violet|purple|fuchsia|pink|rose)(?:-\d{2,3})?\b"
    )
    assert not re.search(palette, text)
    assert not re.search(r"-\[(?:#|rgb|hsl)", text)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", text)
    assert "style=" not in text


def test_layout_templates_use_theme_tokens():
    text = _template_text()
    for token in ("bg-bg", "bg-surface", "text-ink", "text-muted", "border-line", "bg-accent"):
        assert re.search(rf"\b{token}\b", text), f"theme token not used: {token}"


def test_layout_labels_exist_in_both_languages():
    keys = set()
    for name in TEMPLATES:
        keys.update(re.findall(r'\bt\(\s*"([a-z_]+)"', (WEB / "templates" / name).read_text(encoding="utf-8")))
        keys.update(re.findall(r'\bt\(\s*"([a-z_]+)"\s*~', (WEB / "templates" / name).read_text(encoding="utf-8")))
    for key in keys:
        if key.startswith("status_") or key.startswith("theme_"):
            continue
        assert key in DICTIONARIES["en"], f"missing en key: {key}"
        assert key in DICTIONARIES["tr"], f"missing tr key: {key}"
