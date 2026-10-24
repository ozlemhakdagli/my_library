import json

import httpx
import pytest

from library.config import Settings
from library.llm import (
    LLMError,
    chat_json,
    in_library,
    make_client,
    parse_completion,
    parse_filters,
    parse_suggestions,
)


def _settings(**overrides) -> Settings:
    base = dict(port=8765, db_path=":memory:", default_lang="en")
    base.update(overrides)
    return Settings(**base)


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _client_with(handler, settings: Settings) -> httpx.Client:
    return make_client(settings, transport=httpx.MockTransport(handler))


# --- config -----------------------------------------------------------------


def test_config_defaults(monkeypatch):
    for name in ("LIBRARY_LLM_URL", "LIBRARY_LLM_MODEL", "LIBRARY_LLM_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    s = Settings.from_env()
    assert s.llm_url == "http://host.docker.internal:1234/v1"
    assert s.llm_model == ""
    assert s.llm_timeout == 60


def test_config_reads_llm_env(monkeypatch):
    monkeypatch.setenv("LIBRARY_LLM_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("LIBRARY_LLM_MODEL", "qwen-test")
    monkeypatch.setenv("LIBRARY_LLM_TIMEOUT", "12.5")
    s = Settings.from_env()
    assert s.llm_url == "http://localhost:9999/v1"
    assert s.llm_model == "qwen-test"
    assert s.llm_timeout == 12.5


# --- chat_json --------------------------------------------------------------


def test_chat_json_returns_dict_and_sends_expected_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _reply('{"title": "Ada"}')

    settings = _settings(llm_url="http://fake:1234/v1/", llm_model="m1")
    with _client_with(handler, settings) as client:
        result = chat_json(client, settings, "sys", "usr")

    assert result == {"title": "Ada"}
    assert seen["url"] == "http://fake:1234/v1/chat/completions"
    assert seen["body"]["model"] == "m1"
    assert seen["body"]["temperature"] == 0.2
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


def test_chat_json_omits_model_when_empty():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _reply("{}")

    settings = _settings(llm_model="")
    with _client_with(handler, settings) as client:
        chat_json(client, settings, "s", "u")
    assert "model" not in seen["body"]


def test_chat_json_extracts_fenced_block():
    content = 'Tabii, işte sonuç:\n```json\n{"subtitle": "Bir Roman"}\n```\nBaşka bir şey.'
    settings = _settings()
    with _client_with(lambda r: _reply(content), settings) as client:
        assert chat_json(client, settings, "s", "u") == {"subtitle": "Bir Roman"}


def test_chat_json_invalid_content_raises():
    settings = _settings()
    with _client_with(lambda r: _reply("bu bir JSON değil"), settings) as client:
        with pytest.raises(LLMError):
            chat_json(client, settings, "s", "u")


def test_chat_json_non_object_raises():
    settings = _settings()
    with _client_with(lambda r: _reply("[1, 2, 3]"), settings) as client:
        with pytest.raises(LLMError):
            chat_json(client, settings, "s", "u")


def test_chat_json_connect_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    settings = _settings()
    with _client_with(handler, settings) as client:
        with pytest.raises(LLMError):
            chat_json(client, settings, "s", "u")


def test_chat_json_timeout_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    settings = _settings()
    with _client_with(handler, settings) as client:
        with pytest.raises(LLMError):
            chat_json(client, settings, "s", "u")


def test_chat_json_http_500_raises():
    settings = _settings()
    with _client_with(lambda r: httpx.Response(500, text="boom"), settings) as client:
        with pytest.raises(LLMError):
            chat_json(client, settings, "s", "u")


def test_chat_json_missing_choices_raises():
    settings = _settings()
    with _client_with(lambda r: httpx.Response(200, json={"foo": 1}), settings) as client:
        with pytest.raises(LLMError):
            chat_json(client, settings, "s", "u")


# --- parse_filters ----------------------------------------------------------


def test_parse_filters_drops_unknown_keys():
    out = parse_filters({"q": "ahmet", "evil": "DROP TABLE", "shelf": "Roman", "x": 1})
    assert "evil" not in out and "x" not in out
    assert out["q"] == "ahmet"
    assert out["shelf"] == "Roman"


def test_parse_filters_invalid_status_becomes_none():
    assert parse_filters({"status": "bogus"})["status"] is None
    assert parse_filters({"status": "reading"})["status"] == "reading"


def test_parse_filters_caps_type_list_to_five():
    out = parse_filters({"type": [f"t{i}" for i in range(9)]})
    assert out["type"] == ["t0", "t1", "t2", "t3", "t4"]


def test_parse_filters_caps_q_length():
    assert len(parse_filters({"q": "a" * 500})["q"]) == 200


def test_parse_filters_needs_review_bool_only():
    assert parse_filters({"needs_review": True})["needs_review"] is True
    assert "needs_review" not in parse_filters({"needs_review": "yes"})


# --- parse_suggestions ------------------------------------------------------


def test_parse_suggestions_drops_empty_titles():
    obj = {
        "suggestions": [
            {"title": "  ", "author": "X", "reason": "r"},
            {"title": "Kitap A", "author": "Yazar", "reason": "neden"},
        ]
    }
    out = parse_suggestions(obj)
    assert out == [{"title": "Kitap A", "author": "Yazar", "reason": "neden"}]


def test_parse_suggestions_applies_limit():
    obj = {"suggestions": [{"title": f"K{i}", "author": "", "reason": ""} for i in range(10)]}
    assert len(parse_suggestions(obj)) == 5
    assert len(parse_suggestions(obj, limit=2)) == 2


def test_parse_suggestions_missing_list_returns_empty():
    assert parse_suggestions({}) == []


# --- parse_completion -------------------------------------------------------


def test_parse_completion_only_subtitle_and_publisher():
    out = parse_completion({"subtitle": "Alt Başlık", "publisher": "Yayınevi", "title": "x"})
    assert set(out) == {"subtitle", "publisher"}
    assert out == {"subtitle": "Alt Başlık", "publisher": "Yayınevi"}


def test_parse_completion_caps_lengths():
    out = parse_completion({"subtitle": "s" * 400, "publisher": "p" * 300})
    assert len(out["subtitle"]) == 300
    assert len(out["publisher"]) == 200


# --- in_library -------------------------------------------------------------


BOOKS = [
    {"title": "Yapay Zekâ", "authors": ["Stuart Russell"]},
    {"title": "Suç ve Ceza", "authors": ["Fyodor Dostoyevski"]},
]


def test_in_library_matches_accent_and_case_insensitively():
    assert in_library("yapay zeka", "", BOOKS) is True
    assert in_library("YAPAY ZEKA", None, BOOKS) is True


def test_in_library_different_author_does_not_match():
    assert in_library("Yapay Zekâ", "Başka Yazar", BOOKS) is False


def test_in_library_same_author_matches():
    assert in_library("Yapay Zekâ", "Stuart Russell", BOOKS) is True


def test_in_library_unknown_title_does_not_match():
    assert in_library("Olmayan Kitap", "", BOOKS) is False
