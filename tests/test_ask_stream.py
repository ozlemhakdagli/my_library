import json

import httpx
import pytest
from fastapi.testclient import TestClient

from library import db
from library.config import Settings
from library.llm import LLMError, make_client, stream_chat
from library.web.app import create_app


def _sse(*payloads: dict) -> str:
    lines = [f"data: {json.dumps(p, ensure_ascii=False)}\n\n" for p in payloads]
    lines.append("data: [DONE]\n\n")
    return "".join(lines)


def _chunk(**delta) -> dict:
    return {"choices": [{"delta": delta}]}


def _settings(db_path) -> Settings:
    return Settings(port=8765, db_path=db_path, default_lang="en")


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = db.connect(path)
    db.init_schema(conn)
    db.add_book(conn, title="Beyoğlu Rapsodisi", author_names=["Ahmet Ümit"])
    conn.close()
    return path


def test_stream_chat_yields_thinking_then_content(db_path):
    body = _sse(
        _chunk(reasoning_content="Looking at the question. "),
        _chunk(reasoning_content="Filters needed."),
        _chunk(content='{"q": "Ümit"}'),
    )
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"}))
    client = make_client(_settings(db_path), transport=transport)
    pieces = list(stream_chat(client, _settings(db_path), "system", "user"))
    assert pieces == [
        ("thinking", "Looking at the question. "),
        ("thinking", "Filters needed."),
        ("content", '{"q": "Ümit"}'),
    ]


def test_stream_chat_http_error_raises(db_path):
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    client = make_client(_settings(db_path), transport=transport)
    with pytest.raises(LLMError):
        list(stream_chat(client, _settings(db_path), "system", "user"))


def test_ask_stream_emits_steps_thinking_answer_books_done(db_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            body = _sse(_chunk(reasoning_content="Think. "), _chunk(content='{"q": "Ahmet"}'))
        else:
            body = _sse(_chunk(content="One book "), _chunk(content="matches."))
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    app = create_app(_settings(db_path), llm_transport=httpx.MockTransport(handler))
    client = TestClient(app)
    response = client.post("/ask/stream", data={"question": "Ahmet Ümit?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = []
    for block in response.text.split("\n\n"):
        name = next((l[6:].strip() for l in block.split("\n") if l.startswith("event:")), None)
        if name:
            events.append(name)
    assert events[0] == "step"
    assert "thinking" in events
    assert "answer" in events
    assert events.index("table") > events.index("answer")
    assert events[-1] == "done"
    assert "Beyoğlu Rapsodisi" in response.text


def test_ask_stream_reports_unavailable_server(db_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = TestClient(create_app(_settings(db_path), llm_transport=httpx.MockTransport(handler)))
    response = client.post("/ask/stream", data={"question": "anything"})
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "event: done" in response.text


def test_ask_page_contains_live_panel_and_script(db_path):
    client = TestClient(create_app(_settings(db_path)))
    html = client.get("/ask").text
    assert 'id="ask-live"' in html
    assert 'data-stream="/ask/stream"' in html
    assert "/static/ask.js" in html


def test_floating_assistant_is_on_every_page(db_path):
    client = TestClient(create_app(_settings(db_path)))
    for path in ("/", "/reading", "/ask"):
        html = client.get(path).text
        assert 'id="assistant-toggle"' in html, path
        assert 'data-endpoint="/ask/stream"' in html, path
        assert "/static/assistant.js" in html, path


def test_count_books_by_type_counts_live_books_only(tmp_path):
    path = str(tmp_path / "counts.db")
    conn = db.connect(path)
    db.init_schema(conn)
    roman = db.add_type(conn, "Roman")
    science = db.add_type(conn, "Bilim")
    a = db.add_book(conn, title="A")
    b = db.add_book(conn, title="B")
    db.add_book(conn, title="C-no-type")
    gone = db.add_book(conn, title="Deleted")
    db.set_book_types(conn, a, [roman, science])
    db.set_book_types(conn, b, [roman])
    db.set_book_types(conn, gone, [science])
    db.soft_delete_book(conn, gone)
    rows, untyped, total = db.count_books_by_type(conn)
    assert dict(rows) == {"Roman": 2, "Bilim": 1}
    assert untyped == 1
    assert total == 3
    conn.close()


def test_types_question_sends_counts_to_the_summary(db_path):
    conn = db.connect(db_path)
    roman = db.add_type(conn, "Roman")
    book_id = db.add_book(conn, title="Kitap")
    db.set_book_types(conn, book_id, [roman])
    conn.close()

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            body = _sse(_chunk(content='{"aggregate": "types"}'))
        else:
            body = _sse(_chunk(content="Roman: 1"))
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = TestClient(create_app(_settings(db_path), llm_transport=httpx.MockTransport(handler)))
    response = client.post("/ask/stream", data={"question": "Türlerin dağılımı nedir?"})
    assert response.status_code == 200
    summary_user_message = calls[1]["messages"][1]["content"]
    assert "Roman: 1" in summary_user_message
    assert "Books per type" in summary_user_message
    assert "event: table" in response.text
    assert "Books per type" not in response.text


def test_summary_input_marks_books_without_status_as_unread():
    from library.web.app import _ask_summary_input

    books = [{"title": "Gece Yarısı Kütüphanesi", "authors": ["Matt Haig"], "status": None}]
    text = _ask_summary_input("gece yarısı kütüphanesi okudu mu", books)
    assert "status: unread" in text
    assert "none" not in text
