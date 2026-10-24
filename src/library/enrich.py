"""Fill missing book types from Open Library subjects. Only title and author are sent."""

import time
from dataclasses import dataclass

import httpx

from library import db
from library.llm import LLMError, chat_json
from library.norm import norm

SEARCH_URL = "https://openlibrary.org/search.json"
USER_AGENT = "library-enrich/1.0 (personal library; contact: local)"

# English subject keywords -> Turkish type names. Longer keywords are checked first.
SUBJECT_TYPES = {
    "science fiction": "Bilim Kurgu",
    "fiction": "Roman",
    "novel": "Roman",
    "poetry": "Şiir",
    "poems": "Şiir",
    "history": "Tarih",
    "biography": "Biyografi",
    "autobiography": "Biyografi",
    "psychology": "Psikoloji",
    "philosophy": "Felsefe",
    "business": "İş",
    "management": "İş",
    "economics": "Ekonomi",
    "artificial intelligence": "Yapay Zekâ",
    "computer": "Bilgisayar",
    "data": "Veri",
    "mathematics": "Matematik",
    "science": "Bilim",
    "religion": "Din",
    "politic": "Siyaset",
    "sociology": "Sosyoloji",
    "health": "Sağlık",
    "cooking": "Yemek",
    "art": "Sanat",
    "travel": "Gezi",
    "juvenile": "Çocuk",
    "children": "Çocuk",
    "education": "Eğitim",
    "self-help": "Kişisel Gelişim",
    "personal growth": "Kişisel Gelişim",
    "mystery": "Gerilim",
    "thriller": "Gerilim",
    "horror": "Korku",
    "romance": "Aşk",
    "drama": "Tiyatro",
    "essay": "Deneme",
}
MAX_TYPES_PER_BOOK = 2
ALLOWED_TYPES = sorted(set(SUBJECT_TYPES.values()))


class TooManyRequests(Exception):
    """Raised when the lookup service refuses more requests for now."""


@dataclass
class EnrichReport:
    checked: int = 0
    updated: int = 0
    no_match: int = 0
    stopped_early: bool = False


def types_for_subjects(subjects: list[str]) -> list[str]:
    """Map subject strings to Turkish type names, most specific keyword first, without duplicates."""
    found: list[str] = []
    keywords = sorted(SUBJECT_TYPES, key=len, reverse=True)
    for subject in subjects:
        lowered = subject.lower()
        for keyword in keywords:
            if keyword in lowered:
                name = SUBJECT_TYPES[keyword]
                if name not in found:
                    found.append(name)
                break
        if len(found) >= MAX_TYPES_PER_BOOK:
            break
    return found[:MAX_TYPES_PER_BOOK]


def lookup_subjects(client: httpx.Client, title: str, author: str | None) -> list[str]:
    """Subjects of the first Open Library record whose title matches. Empty when nothing matches."""
    params = {"title": title, "limit": "5", "fields": "title,author_name,subject"}
    if author:
        params["author"] = author
    response = client.get(SEARCH_URL, params=params, headers={"User-Agent": USER_AGENT})
    if response.status_code == 429 or response.status_code >= 500:
        raise TooManyRequests(str(response.status_code))
    if response.status_code >= 400:
        return []
    wanted = norm(title)
    for doc in response.json().get("docs", []):
        found = norm(doc.get("title", ""))
        if found and (found == wanted or found.startswith(wanted)):
            return doc.get("subject", []) or []
    return []


def classify_with_model(llm_client, settings, title: str, authors: list[str]) -> list[str]:
    """Ask the local model to pick types from ALLOWED_TYPES only. Unknown answers are dropped."""
    system = (
        "You classify books by genre. Choose at most two names from this list only: "
        + ", ".join(ALLOWED_TYPES)
        + '. Reply with one JSON object and nothing else: {"types": ["..."]}. '
        'If you do not know the book, reply {"types": []}.'
    )
    user = f"Title: {title}\nAuthor: {', '.join(authors) or 'unknown'}"
    obj = chat_json(llm_client, settings, system, user)
    raw = obj.get("types")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, str) and item in ALLOWED_TYPES and item not in names:
            names.append(item)
    return names[:MAX_TYPES_PER_BOOK]


def enrich_types(
    conn,
    client: httpx.Client,
    delay: float = 1.0,
    sleep=time.sleep,
    classify=None,
    limit: int | None = None,
) -> EnrichReport:
    """Give books without a type the types their subjects suggest, else the model's pick.

    Safe to run again. classify(title, authors) -> list[str] is optional.
    """
    report = EnrichReport()
    for book in db.books_without_types(conn)[: limit or None]:
        report.checked += 1
        author = book["authors"][0] if book["authors"] else None
        try:
            subjects = lookup_subjects(client, book["title"], author)
        except (TooManyRequests, httpx.HTTPError):
            report.stopped_early = True
            break
        names = types_for_subjects(subjects)
        if not names and classify is not None:
            try:
                names = classify(book["title"], book["authors"])
            except (LLMError, httpx.HTTPError):
                names = []
        names = [n for n in names if n in ALLOWED_TYPES][:MAX_TYPES_PER_BOOK]
        if not names:
            report.no_match += 1
        else:
            type_ids = [db.ensure_type(conn, name) for name in names]
            db.attach_book_types(conn, book["id"], type_ids)
            report.updated += 1
        sleep(delay)
    return report


def main() -> None:
    from library.config import Settings

    settings = Settings.from_env()
    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    import argparse

    from library.llm import make_client

    parser = argparse.ArgumentParser(description="Fill missing book types.")
    parser.add_argument("--limit", type=int, default=None, help="process at most this many books")
    parser.add_argument("--no-model", action="store_true", help="do not ask the local model")
    args = parser.parse_args()
    llm_client = make_client(settings)
    classify = None if args.no_model else (
        lambda title, authors: classify_with_model(llm_client, settings, title, authors)
    )
    with httpx.Client(timeout=15.0) as client:
        report = enrich_types(conn, client, classify=classify, limit=args.limit)
    conn.close()
    print(
        f"checked={report.checked} updated={report.updated} "
        f"no_match={report.no_match} stopped_early={report.stopped_early}"
    )


if __name__ == "__main__":
    main()
