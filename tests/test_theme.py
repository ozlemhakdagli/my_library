import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.web.app import create_app

WEB = Path(__file__).resolve().parent.parent / "src" / "library" / "web"


@pytest.fixture
def client(tmp_path):
    path = str(tmp_path / "theme.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    return TestClient(create_app(Settings(port=8765, db_path=path, default_lang="en")))


def html_tag(text: str) -> str:
    match = re.search(r"<html[^>]*>", text)
    assert match, "no <html> tag"
    return match.group(0)


def test_no_cookie_means_system_without_class(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "class=" not in html_tag(response.text)


def test_dark_cookie_sets_dark_class(client):
    response = client.get("/", headers={"Cookie": "theme=dark"})
    assert 'class="dark"' in html_tag(response.text)


def test_light_cookie_sets_light_class(client):
    response = client.get("/", headers={"Cookie": "theme=light"})
    assert 'class="light"' in html_tag(response.text)


def test_system_cookie_sets_no_class(client):
    response = client.get("/", headers={"Cookie": "theme=system"})
    assert "class=" not in html_tag(response.text)


@pytest.mark.parametrize("value", ["blue", "DARK", ""])
def test_invalid_cookie_falls_back_to_system(client, value):
    response = client.get("/", headers={"Cookie": f"theme={value}"})
    assert "class=" not in html_tag(response.text)


def test_theme_class_applies_on_other_pages(client):
    response = client.get("/settings", headers={"Cookie": "theme=dark"})
    assert 'class="dark"' in html_tag(response.text)


def test_post_theme_sets_cookie_and_redirects(client):
    response = client.post("/settings/theme", data={"theme": "dark"}, follow_redirects=False)
    assert response.status_code == 303
    assert "theme=dark" in response.headers["set-cookie"]


def test_post_theme_returns_to_referring_page(client):
    response = client.post(
        "/settings/theme",
        data={"theme": "light"},
        headers={"Referer": "http://testserver/reading?lang=tr"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/reading?lang=tr"


def test_post_theme_ignores_foreign_referer(client):
    response = client.post(
        "/settings/theme",
        data={"theme": "light"},
        headers={"Referer": "https://evil.example/x"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


@pytest.mark.parametrize("value", ["blue", ""])
def test_post_invalid_theme_is_400(client, value):
    response = client.post("/settings/theme", data={"theme": value}, follow_redirects=False)
    assert response.status_code == 400
    assert "set-cookie" not in response.headers


def test_nav_theme_labels_in_english(client):
    text = client.get("/?lang=en").text
    for label in ("Light", "Dark", "System"):
        assert f">{label}</button>" in text


def test_nav_theme_labels_in_turkish(client):
    text = client.get("/?lang=tr").text
    for label in ("Açık", "Koyu", "Sistem"):
        assert f">{label}</button>" in text


def test_app_css_defines_accent_token():
    css = (WEB / "static" / "app.css").read_text(encoding="utf-8")
    assert "--accent:" in css
    assert ":root.dark" in css
