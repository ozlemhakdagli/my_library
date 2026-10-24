import json

import httpx
import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.i18n import translate
from library.web.app import create_app


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _fake_llm(*contents: str, status: int = 200):
    """Transport that answers each call with the next content string, recording requests."""
    queue = list(contents)
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": "boom"})
        content = queue.pop(0)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler), seen


@pytest.fixture
def seeded(tmp_path):
    path = str(tmp_path / "book_llm.db")
    conn = db.connect(path)
    db.init_schema(conn)
    ids = {
        "sefiller": db.add_book(conn, title="Sefiller", author_names=["Victor Hugo"]),
        "beyoglu": db.add_book(conn, title="Beyoğlu Rapsodisi", author_names=["Ahmet Ümit"]),
    }
    conn.close()
    ids["path"] = path
    return ids


def _client(path, transport=None):
    app = create_app(
        Settings(port=8765, db_path=path, default_lang="en"),
        llm_transport=transport,
    )
    return TestClient(app, follow_redirects=False)


def _book_rows(path) -> list[dict]:
    conn = db.connect(path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM book ORDER BY id").fetchall()]
    finally:
        conn.close()


def _book_count(path) -> int:
    return len(_book_rows(path))


def _book(path, book_id: int) -> dict:
    conn = db.connect(path)
    try:
        return db.get_book(conn, book_id)
    finally:
        conn.close()


# --- suggestions on the book page -------------------------------------------------


def test_suggest_keeps_at_most_five_suggestions(seeded):
    suggestions = [{"title": f"Alfa Öneri {i}", "author": "Yazar", "reason": "Benzer"} for i in range(1, 8)]
    transport, _ = _fake_llm(_reply({"suggestions": suggestions}))
    client = _client(seeded["path"], transport)

    response = client.post(f"/books/{seeded['beyoglu']}/suggest", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "Alfa Öneri 5" in response.text
    assert "Alfa Öneri 6" not in response.text


def test_suggest_marks_books_already_in_library(seeded):
    transport, _ = _fake_llm(
        _reply(
            {
                "suggestions": [
                    {"title": "Sefiller", "author": "Victor Hugo", "reason": "Klasik roman"},
                    {"title": "Yepyeni Kitap", "author": "Kimse", "reason": "Yakın tema"},
                ]
            }
        )
    )
    client = _client(seeded["path"], transport)

    response = client.post(f"/books/{seeded['beyoglu']}/suggest?lang=en", headers={"HX-Request": "true"})

    badge = translate("en", "suggest_in_library")
    assert response.status_code == 200
    assert response.text.count(badge) == 1
    assert f'href="/books/{seeded["sefiller"]}"' in response.text
    assert "Klasik roman" in response.text
    assert "Yakın tema" in response.text


def test_suggest_does_not_create_books(seeded):
    transport, _ = _fake_llm(
        _reply({"suggestions": [{"title": "Hayali Kitap", "author": "Kimse", "reason": "x"}]})
    )
    client = _client(seeded["path"], transport)
    before = _book_rows(seeded["path"])

    client.post(f"/books/{seeded['beyoglu']}/suggest", headers={"HX-Request": "true"})

    assert _book_rows(seeded["path"]) == before


def test_suggest_prompt_contains_book_details(seeded):
    transport, seen = _fake_llm(_reply({"suggestions": []}))
    client = _client(seeded["path"], transport)

    client.post(f"/books/{seeded['beyoglu']}/suggest", headers={"HX-Request": "true"})

    user_message = seen[0]["messages"][1]["content"]
    assert "Beyoğlu Rapsodisi" in user_message
    assert "Ahmet Ümit" in user_message


def test_suggest_llm_error_returns_200_and_keeps_book(seeded):
    transport, _ = _fake_llm(status=500)
    client = _client(seeded["path"], transport)
    before = _book_rows(seeded["path"])

    response = client.post(
        f"/books/{seeded['beyoglu']}/suggest?lang=en", headers={"HX-Request": "true"}
    )

    assert response.status_code == 200
    assert translate("en", "suggest_error") in response.text
    assert _book_rows(seeded["path"]) == before


def test_suggest_unknown_book_is_404(seeded):
    client = _client(seeded["path"], _fake_llm()[0])

    response = client.post("/books/9999/suggest", headers={"HX-Request": "true"})

    assert response.status_code == 404


def test_book_page_shows_suggest_button(seeded):
    client = _client(seeded["path"], _fake_llm()[0])

    response = client.get(f"/books/{seeded['beyoglu']}?lang=en")

    assert response.status_code == 200
    assert translate("en", "suggest_btn") in response.text
    assert f'action="/books/{seeded["beyoglu"]}/suggest"' in response.text


# --- metadata completion on the edit page -----------------------------------------


def test_complete_returns_suggestion_without_changing_book(seeded):
    transport, _ = _fake_llm(_reply({"subtitle": "Bir Aşk Romanı", "publisher": "Can Yayınları"}))
    client = _client(seeded["path"], transport)
    before = _book_rows(seeded["path"])

    response = client.post(
        f"/books/{seeded['beyoglu']}/complete?lang=en",
        data={"title": "Beyoğlu Rapsodisi", "authors": "Ahmet Ümit", "subtitle": "", "publisher": ""},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Bir Aşk Romanı" in response.text
    assert "Can Yayınları" in response.text
    assert translate("en", "suggestion_tag") in response.text
    assert _book_rows(seeded["path"]) == before


def test_complete_prompt_forbids_invention(seeded):
    transport, seen = _fake_llm(_reply({"subtitle": "", "publisher": ""}))
    client = _client(seeded["path"], transport)

    client.post(
        f"/books/{seeded['beyoglu']}/complete",
        data={"title": "Beyoğlu Rapsodisi", "authors": "Ahmet Ümit", "subtitle": "", "publisher": ""},
        headers={"HX-Request": "true"},
    )

    system_message = seen[0]["messages"][0]["content"]
    assert "invent" in system_message.lower()
    assert "title" in system_message and "author" in system_message


def test_complete_only_offers_blank_fields(seeded):
    transport, _ = _fake_llm(_reply({"subtitle": "Yeni Alt Başlık", "publisher": "Yeni Yayınevi"}))
    client = _client(seeded["path"], transport)

    response = client.post(
        f"/books/{seeded['beyoglu']}/complete",
        data={"title": "Beyoğlu Rapsodisi", "authors": "Ahmet Ümit", "subtitle": "Dolu", "publisher": ""},
        headers={"HX-Request": "true"},
    )

    assert "Yeni Alt Başlık" not in response.text
    assert "Yeni Yayınevi" in response.text


def test_apply_fills_form_fields_without_saving(seeded):
    client = _client(seeded["path"], _fake_llm()[0])
    before = _book_rows(seeded["path"])

    response = client.post(
        f"/books/{seeded['beyoglu']}/complete/apply",
        data={
            "title": "Beyoğlu Rapsodisi",
            "authors": "Ahmet Ümit",
            "subtitle": "",
            "publisher": "",
            "note": "",
            "review_status": "ok",
            "suggested_subtitle": "Bir Aşk Romanı",
            "suggested_publisher": "Can Yayınları",
            "apply": ["subtitle"],
        },
    )

    assert response.status_code == 200
    assert 'value="Bir Aşk Romanı"' in response.text
    assert "Can Yayınları" not in response.text.split('name="publisher"')[1].split(">")[0]
    assert _book_rows(seeded["path"]) == before


def test_apply_then_save_updates_book(seeded):
    client = _client(seeded["path"], _fake_llm()[0])

    response = client.post(
        f"/books/{seeded['beyoglu']}/edit",
        data={
            "title": "Beyoğlu Rapsodisi",
            "subtitle": "Bir Aşk Romanı",
            "authors": "Ahmet Ümit",
            "publisher": "Can Yayınları",
            "note": "",
            "review_status": "ok",
            "action": "save",
        },
    )

    assert response.status_code == 303
    book = _book(seeded["path"], seeded["beyoglu"])
    assert book["subtitle"] == "Bir Aşk Romanı"
    assert book["publisher"] == "Can Yayınları"


def test_complete_llm_error_returns_200_and_keeps_book(seeded):
    transport, _ = _fake_llm(status=500)
    client = _client(seeded["path"], transport)
    before = _book_rows(seeded["path"])

    response = client.post(
        f"/books/{seeded['beyoglu']}/complete?lang=en",
        data={"title": "Beyoğlu Rapsodisi", "authors": "Ahmet Ümit", "subtitle": "", "publisher": ""},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert translate("en", "complete_error") in response.text
    assert _book_rows(seeded["path"]) == before


def test_complete_unknown_book_is_404(seeded):
    client = _client(seeded["path"], _fake_llm()[0])

    response = client.post(
        "/books/9999/complete",
        data={"title": "X", "authors": "", "subtitle": "", "publisher": ""},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 404


def test_apply_unknown_book_is_404(seeded):
    client = _client(seeded["path"], _fake_llm()[0])

    response = client.post("/books/9999/complete/apply", data={"title": "X"})

    assert response.status_code == 404


def test_edit_page_shows_completion_button_only_when_fields_blank(seeded):
    client = _client(seeded["path"], _fake_llm()[0])

    blank = client.get(f"/books/{seeded['beyoglu']}/edit?lang=en")
    assert translate("en", "complete_btn") in blank.text

    conn = db.connect(seeded["path"])
    db.update_book(
        conn,
        seeded["beyoglu"],
        {"subtitle": "Alt", "publisher": "Yayın", "authors": "Ahmet Ümit", "title": "Beyoğlu Rapsodisi"},
    )
    conn.close()
    filled = client.get(f"/books/{seeded['beyoglu']}/edit?lang=en")
    assert translate("en", "complete_btn") not in filled.text


def test_suggest_and_complete_texts_are_translated(seeded):
    for key in ("suggest_btn", "suggest_in_library", "suggest_error", "complete_btn", "complete_error",
                "suggestion_tag", "complete_apply"):
        assert translate("en", key) != key
        assert translate("tr", key) != key


def test_complete_without_htmx_renders_full_edit_page(seeded):
    transport, _ = _fake_llm(_reply({"subtitle": "Bir Aşk Romanı", "publisher": ""}))
    client = _client(seeded["path"], transport)

    response = client.post(
        f"/books/{seeded['beyoglu']}/complete?lang=en",
        data={"title": "Beyoğlu Rapsodisi", "authors": "Ahmet Ümit", "subtitle": "", "publisher": ""},
    )

    assert response.status_code == 200
    assert "<html" in response.text
    assert "Bir Aşk Romanı" in response.text
    assert f'action="/books/{seeded["beyoglu"]}/complete/apply"' in response.text
