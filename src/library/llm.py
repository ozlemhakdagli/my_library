"""Client for a local OpenAI-compatible LLM server (LM Studio).

Model output is untrusted: responses are parsed defensively and nothing
here writes to the database.
"""

import json
import re

import httpx

from library.config import Settings
from library.norm import norm

FILTER_STATUSES = {"unread", "reading", "read", "abandoned"}


class LLMError(Exception):
    """A short, user-displayable description of an LLM failure."""


def make_client(settings: Settings, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=settings.llm_timeout, transport=transport)


def _first_json_object(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def chat_json(client: httpx.Client, settings: Settings, system: str, user: str) -> dict:
    body: dict = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    if settings.llm_model:
        body["model"] = settings.llm_model
    url = settings.llm_url.rstrip("/") + "/chat/completions"

    try:
        response = client.post(url, json=body)
    except httpx.TimeoutException as exc:
        raise LLMError("Yapay zekâ sunucusu zamanında yanıt vermedi.") from exc
    except httpx.HTTPError as exc:
        raise LLMError("Yapay zekâ sunucusuna bağlanılamadı. LM Studio açık mı?") from exc

    if response.status_code >= 400:
        raise LLMError(f"Yapay zekâ sunucusu hata döndürdü (HTTP {response.status_code}).")

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("Yapay zekâ sunucusunun yanıtı beklenen biçimde değil.") from exc

    obj = _first_json_object(content) if isinstance(content, str) else None
    if obj is None:
        raise LLMError("Yapay zekâ yanıtında geçerli bir JSON nesnesi bulunamadı.")
    return obj


def _str_or_none(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()[:limit]
    return value or None


def parse_filters(obj: dict) -> dict:
    out: dict = {}
    if "q" in obj and isinstance(obj["q"], str):
        out["q"] = obj["q"].strip()[:200]
    if "shelf" in obj:
        out["shelf"] = _str_or_none(obj["shelf"], 200)
    if "type" in obj and isinstance(obj["type"], list):
        out["type"] = [t.strip()[:200] for t in obj["type"] if isinstance(t, str) and t.strip()][:5]
    if "status" in obj:
        status = obj["status"]
        out["status"] = status if status in FILTER_STATUSES else None
    if "needs_review" in obj and isinstance(obj["needs_review"], bool):
        out["needs_review"] = obj["needs_review"]
    return out


def parse_suggestions(obj: dict, limit: int = 5) -> list[dict]:
    items = obj.get("suggestions")
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _str_or_none(item.get("title"), 200)
        if not title:
            continue
        out.append(
            {
                "title": title,
                "author": _str_or_none(item.get("author"), 200) or "",
                "reason": _str_or_none(item.get("reason"), 300) or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def parse_completion(obj: dict) -> dict:
    return {
        "subtitle": _str_or_none(obj.get("subtitle"), 300) or "",
        "publisher": _str_or_none(obj.get("publisher"), 200) or "",
    }


def _author_tokens(names) -> set[str]:
    if isinstance(names, str):
        names = [names]
    tokens: set[str] = set()
    for name in names or []:
        tokens.update(t for t in (norm(part) for part in re.split(r"[\s,;.]+", str(name))) if t)
    return tokens


def in_library(title: str, author: str | None, books: list[dict]) -> bool:
    """True when a book with the same normalized title (and a compatible author) exists."""
    wanted_title = norm(title)
    if not wanted_title:
        return False
    wanted_authors = _author_tokens(author) if author else set()
    for book in books:
        if norm(book.get("title")) != wanted_title:
            continue
        if not wanted_authors:
            return True
        if wanted_authors & _author_tokens(book.get("authors")):
            return True
    return False
