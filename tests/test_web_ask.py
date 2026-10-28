import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.i18n import translate
from library.web.app import create_app

TODAY = date(2026, 10, 24)


def _reply(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _fake_llm(*contents: str):
    """Transport that answers each call with the next content string, recording requests."""
    queue = list(contents)
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        content = queue.pop(0)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler), seen


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = db.connect(path)
    db.init_schema(conn)
    db.add_book(conn, title="Beyoğlu Rapsodisi", author_names=["Ahmet Ümit"])
    db.add_book(conn, title="Sefiller", author_names=["Victor Hugo"])
    conn.close()
    return path


def _client(db_path, transport=None):
    app = create_app(
        Settings(port=8765, db_path=db_path, default_lang="en"),
        today_fn=lambda: TODAY,
        llm_transport=transport,
    )
    return TestClient(app, follow_redirects=False)


def _book_count(db_path) -> int:
    conn = db.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM book").fetchone()[0]
    finally:
        conn.close()


def test_ask_filters_search_and_returns_answer(db_path):
    transport, seen = _fake_llm(
        _reply({"q": "Ahmet Ümit", "shelf": None, "type": [], "status": None, "needs_review": False}),
        _reply({"answer": "Beyoğlu Rapsodisi, Ahmet Ümit tarafından yazılmış."}),
    )
    client = _client(db_path, transport)

    response = client.post("/ask", data={"question": "Ahmet Ümit'ten kitaplar?"})

    assert response.status_code == 200
    assert "Beyoğlu Rapsodisi" in response.text
    assert "Sefiller" not in response.text
    assert "Beyoğlu Rapsodisi, Ahmet Ümit tarafından yazılmış." in response.text
    assert len(seen) == 2
    assert "Ahmet Ümit'ten kitaplar?" in seen[1]["messages"][1]["content"]
    assert "Beyoğlu Rapsodisi" in seen[1]["messages"][1]["content"]


def test_ask_never_writes_model_output_to_database(db_path):
    transport, _ = _fake_llm(
        _reply({"q": "x", "shelf": "new shelf", "type": ["Roman"], "status": "read", "needs_review": True}),
        _reply({"answer": "DROP TABLE book; ok"}),
    )
    before = _book_count(db_path)

    response = _client(db_path, transport).post("/ask", data={"question": "x"})

    assert response.status_code == 200
    assert _book_count(db_path) == before
    conn = db.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM shelf").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM type").fetchone()[0] == 0
    finally:
        conn.close()


def test_unreachable_llm_shows_message_and_200(db_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _client(db_path, httpx.MockTransport(handler))

    response = client.post("/ask", data={"question": "Kitaplarım?"})

    assert response.status_code == 200
    assert translate("en", "ask_error_unavailable") in response.text
    assert 'class="font-semibold text-ink"' not in response.text


def test_summary_failure_still_lists_matching_books(db_path):
    transport, _ = _fake_llm(
        _reply({"q": "Victor Hugo", "shelf": None, "type": [], "status": None, "needs_review": False}),
        "bu bir JSON değil",
    )

    response = _client(db_path, transport).post("/ask", data={"question": "Victor Hugo?"})

    assert response.status_code == 200
    assert translate("en", "ask_error_summary") in response.text
    assert "Sefiller" in response.text
    assert "Beyoğlu Rapsodisi" not in response.text


def test_question_over_500_characters_is_422(db_path):
    transport, seen = _fake_llm()

    response = _client(db_path, transport).post("/ask", data={"question": "a" * 501})

    assert response.status_code == 422
    assert seen == []


def test_question_of_500_characters_is_accepted(db_path):
    transport, seen = _fake_llm(
        _reply({"q": "", "shelf": None, "type": [], "status": None, "needs_review": False}),
        _reply({"answer": "Kayıt yok."}),
    )

    response = _client(db_path, transport).post("/ask", data={"question": "a" * 500})

    assert response.status_code == 200
    assert len(seen) == 2


def test_get_ask_page_has_question_form(db_path):
    response = _client(db_path).get("/ask")

    assert response.status_code == 200
    assert 'name="question"' in response.text
    assert 'action="/ask"' in response.text


def test_htmx_post_returns_result_fragment_only(db_path):
    transport, _ = _fake_llm(
        _reply({"q": "Victor Hugo", "shelf": None, "type": [], "status": None, "needs_review": False}),
        _reply({"answer": "Sefiller, Victor Hugo tarafından yazılmış."}),
    )

    response = _client(db_path, transport).post(
        "/ask", data={"question": "Victor Hugo?"}, headers={"HX-Request": "true"}
    )

    assert response.status_code == 200
    assert "Sefiller, Victor Hugo tarafından yazılmış." in response.text
    assert "<html" not in response.text
    assert "<form" not in response.text


def test_nav_does_not_link_to_ask(db_path):
    # The /ask page still works (used by the floating assistant), but it has no nav entry:
    # the floating assistant on every page replaces it.
    html = _client(db_path).get("/").text

    assert 'href="/ask"' not in html


def test_ask_page_title_differs_by_language():
    assert translate("tr", "title_ask") != translate("en", "title_ask")
