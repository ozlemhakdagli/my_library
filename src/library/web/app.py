import math
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field, ValidationError, field_validator

from library import db, migrate
from library.backup import export_csv, make_backup
from library.config import Settings
from library import covers, ocr
from library.covers import book_cover_color, save_cover
from library.db import (
    READING_STATUSES,
    LoanError,
    NameTakenError,
    ReadingDateError,
    ReviewError,
)
from library.i18n import SUPPORTED_LANGS, resolve_lang, translate
from library.llm import (
    LLMError,
    chat_json,
    in_library,
    make_client,
    parse_completion,
    parse_filters,
    parse_suggestions,
)
from library.norm import norm

WEB_DIR = Path(__file__).parent
PAGE_SIZE = 50
ASK_MAX_LENGTH = 500
ASK_RESULT_LIMIT = 20
ASK_ANSWER_LIMIT = 500
ASK_PROMPT_NAMES = 50
SUGGEST_LIMIT = 5

# Editable form fields and the label key shown for each in change summaries.
EDITABLE_FIELDS = (
    ("title", "field_title"),
    ("subtitle", "field_subtitle"),
    ("authors", "field_authors"),
    ("publisher", "field_publisher"),
    ("note", "field_note"),
    ("review_status", "needs_review"),
)


class BookInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    subtitle: str = Field(default="", max_length=300)
    authors: str = Field(default="", max_length=1000)
    publisher: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=5000)
    review_status: Literal["ok", "needs review"] = "ok"

    @field_validator("*", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def _author_names(authors: str) -> list[str]:
    return [name.strip() for name in authors.split(";") if name.strip()]


def _values_from_book(book: dict) -> dict[str, str]:
    return {
        "title": book["title"],
        "subtitle": book["subtitle"],
        "authors": "; ".join(book["authors"]),
        "publisher": book["publisher"],
        "note": book["note"],
        "review_status": book["review_status"],
    }


def _change_summary(current: dict, new: BookInput, t: Callable[..., str]) -> list[dict[str, str]]:
    """Fields whose posted value differs from the stored value, for display."""
    old_values = _values_from_book(current)
    new_values = new.model_dump()
    rows = []
    for field, label_key in EDITABLE_FIELDS:
        if field == "authors":
            changed = _author_names(old_values[field]) != _author_names(new_values[field])
        else:
            changed = old_values[field] != new_values[field]
        if not changed:
            continue
        old_shown, new_shown = old_values[field], new_values[field]
        if field in ("authors", "publisher"):
            old_shown = old_shown or t("unknown")
            new_shown = new_shown or t("unknown")
        rows.append({"label": t(label_key), "old": old_shown, "new": new_shown})
    return rows

THEMES: tuple[str, ...] = ("light", "dark", "system")
THEME_COOKIE = "theme"
THEME_MAX_AGE = 60 * 60 * 24 * 365


def resolve_theme(value: str | None) -> str:
    """Return the theme from the cookie value; anything unknown means "system"."""
    return value if value in THEMES else "system"


def _theme_of(request: Request) -> str:
    return resolve_theme(request.cookies.get(THEME_COOKIE))


def _theme_class(request: Request) -> str:
    """Class for <html>: "light" or "dark" when chosen, empty for "system"."""
    theme = _theme_of(request)
    return "" if theme == "system" else theme


templates = Jinja2Templates(
    env=Environment(
        loader=FileSystemLoader(WEB_DIR / "templates"),
        autoescape=select_autoescape(["html"]),
    )
)
templates.env.globals["theme_of"] = _theme_of
templates.env.globals["theme_class"] = _theme_class


def _upgrade_existing_db(db_path: str) -> None:
    """Bring an existing database file up to the current schema. A missing file is left alone."""
    if not Path(db_path).exists():
        return
    conn = db.connect(db_path)
    try:
        migrate.upgrade(conn)
    finally:
        conn.close()


@contextmanager
def _open_db(settings: Settings) -> Iterator:
    # Opened inside the route handler, not in a dependency: FastAPI may run
    # dependencies and endpoints in different threads, and sqlite3 connections
    # cannot be shared across threads.
    conn = db.connect(settings.db_path)
    try:
        db.init_schema(conn)
        yield conn
    finally:
        conn.close()


def _shelf_param(value: str) -> tuple[int | None, bool]:
    """Shelf filter from the query: (shelf id, no_shelf). Empty or invalid means no filter."""
    if value == "none":
        return None, True
    if value.isdigit():
        return int(value), False
    return None, False


def _type_params(values: list[str]) -> list[int]:
    return [int(value) for value in values if value.isdigit()]


def _assignments(conn: sqlite3.Connection, book_id: int) -> dict:
    """Shelf id, type chips and picker choices of a book."""
    found = db.get_book_shelf_and_types(conn, book_id)
    chip_ids = {chip["id"] for chip in found["chips"]}
    return {
        "shelf_id": found["shelf_id"],
        "shelves": db.list_shelves(conn),
        "chips": found["chips"],
        "addable": [row for row in db.list_types(conn) if row["id"] not in chip_ids],
    }


def _card_cover(book: dict, shelf_name: str | None) -> None:
    """Cover colour of a book: its own colour when it has one, else shelf or title colour."""
    book["cover"] = book.get("cover_color") or book_cover_color(book["title"], shelf_name)


def _cover_upload_bytes(upload: UploadFile | None) -> bytes | None:
    """Bytes of an uploaded cover, or None when no file was chosen (an empty file field)."""
    if upload is None:
        return None
    # One byte past the limit is read so that an oversized upload is detected.
    data = upload.file.read(covers.MAX_UPLOAD_BYTES + 1)
    if not data and not upload.filename:
        return None
    return data


def _check_cover(photo: bytes | None) -> None:
    """Raise ValueError unless `photo` is a readable JPEG, PNG or WEBP image within the size limit."""
    if photo is None:
        raise ValueError("no cover file")
    covers._open_cover(photo)


# Quick status action -> reading status it sets.
QUICK_STATUS_ACTIONS = {"read": "read", "reading": "reading", "abandon": "abandoned"}


def _ask_filter_prompt(shelves: list[dict], types: list[dict]) -> str:
    shelf_names = ", ".join(s["name"] for s in shelves[:ASK_PROMPT_NAMES]) or "none"
    type_names = ", ".join(t["name"] for t in types[:ASK_PROMPT_NAMES]) or "none"
    return (
        "You turn a question about a personal book library into search filters. "
        "Reply with one JSON object and nothing else. Keys: "
        'q (string: title or author words to search, "" if none), '
        "shelf (string: a shelf name, or null), "
        "type (array of type names, [] if none), "
        'status (one of "unread", "reading", "read", "abandoned", or null), '
        "needs_review (boolean). "
        f"Known shelves: {shelf_names}. Known types: {type_names}. "
        "Use a known name exactly when it matches."
    )


def _ask_summary_prompt(language: str) -> str:
    return (
        "You answer questions about a personal book library. Use ONLY the records given "
        "in the message. If no record answers the question, say that no matching book "
        "was found. Reply with one JSON object and nothing else: {\"answer\": \"...\"}. "
        f"The answer must be at most {ASK_ANSWER_LIMIT} characters. "
        f"Write the answer in {language}."
    )


def _ask_summary_input(question: str, books: list[dict]) -> str:
    lines = [f"Question: {question}", "Records:"]
    if not books:
        lines.append("(none)")
    for book in books:
        authors = ", ".join(book["authors"]) or "-"
        lines.append(f"- title: {book['title']} | authors: {authors} | status: {book['status'] or 'none'}")
    return "\n".join(lines)


def _ask_answer(obj: dict) -> str | None:
    value = obj.get("answer")
    if not isinstance(value, str):
        return None
    return value.strip()[:ASK_ANSWER_LIMIT] or None


def _ask_search_kwargs(filters: dict, shelves: list[dict], types: list[dict]) -> dict:
    """Map model filters to the normal search arguments. Unknown shelf or type names are dropped."""
    kwargs: dict = {
        "query": filters.get("q", ""),
        "status": filters.get("status"),
        "needs_review": filters.get("needs_review", False),
    }
    if filters.get("shelf"):
        shelf = next((s for s in shelves if norm(s["name"]) == norm(filters["shelf"])), None)
        if shelf is not None:
            kwargs["shelf_id"] = shelf["id"]
    type_ids: list[int] = []
    for wanted in filters.get("type", []):
        match = next((t for t in types if norm(t["name"]) == norm(wanted)), None)
        if match is not None and match["id"] not in type_ids:
            type_ids.append(match["id"])
    if type_ids:
        kwargs["type_ids"] = type_ids
    return kwargs


def _suggest_prompt(language: str) -> str:
    return (
        "You suggest books similar to a book in a personal library. Use the title, authors, "
        "types and publisher you are given. Suggest only real books you are confident exist; "
        "never invent a title or author. Reply with one JSON object and nothing else: "
        '{"suggestions": [{"title": "...", "author": "...", "reason": "..."}]}. '
        f"Give at most {SUGGEST_LIMIT} suggestions with short reasons. "
        f"Write the reasons in {language}."
    )


def _suggest_input(book: dict, type_names: list[str]) -> str:
    return "\n".join(
        [
            f"Title: {book['title']}",
            f"Authors: {', '.join(book['authors']) or '-'}",
            f"Types: {', '.join(type_names) or '-'}",
            f"Publisher: {book['publisher'] or '-'}",
        ]
    )


def _complete_prompt() -> str:
    return (
        "You complete missing metadata for a book, using ONLY the title and the author given. "
        "Suggest a subtitle and a publisher only when you are sure of them. "
        "Never invent a value: if you are not sure, return an empty string for that field. "
        'Reply with one JSON object and nothing else: {"subtitle": "...", "publisher": "..."}.'
    )


def _completion_offers(values: dict, suggestion: dict) -> list[dict]:
    """Suggested values for blank fields only; filled fields are never offered."""
    offers = []
    if not values["subtitle"].strip() and suggestion["subtitle"]:
        offers.append({"field": "subtitle", "label_key": "field_subtitle", "value": suggestion["subtitle"]})
    if not values["publisher"].strip() and suggestion["publisher"]:
        offers.append({"field": "publisher", "label_key": "field_publisher", "value": suggestion["publisher"]})
    return offers


def create_app(
    settings: Settings | None = None,
    today_fn: Callable[[], date] = date.today,
    llm_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings.from_env()

    _upgrade_existing_db(settings.db_path)

    app = FastAPI(title="Personal Library")
    app.state.settings = settings
    app.state.llm_client = make_client(settings, transport=llm_transport)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def book_list(
        request: Request,
        q: str = "",
        status: str = "",
        shelf: str = "",
        type_ids: Annotated[list[str] | None, Query(alias="type")] = None,
        loan: bool = False,
        publisher: str = "",
        author: str = "",
        needs_review: bool = False,
        page: int = Query(1, ge=1),
        lang: str | None = None,
    ) -> HTMLResponse:
        active_lang = resolve_lang(lang, request.cookies.get("lang"), settings.default_lang)
        shelf_id, no_shelf = _shelf_param(shelf.strip())
        type_list = _type_params(type_ids or [])
        filters = {
            "q": q.strip(),
            "status": status if status in READING_STATUSES else "",
            "shelf": "none" if no_shelf else (str(shelf_id) if shelf_id is not None else ""),
            "type": [str(type_id) for type_id in type_list],
            "loan": loan,
            "publisher": publisher.strip(),
            "author": author.strip(),
            "needs_review": needs_review,
        }
        db_filters = {
            "query": filters["q"],
            "status": filters["status"] or None,
            "shelf_id": shelf_id,
            "no_shelf": no_shelf,
            "type_ids": type_list or None,
            "loan": "out" if loan else None,
            "publisher": filters["publisher"] or None,
            "author": filters["author"] or None,
            "needs_review": needs_review,
        }

        with _open_db(settings) as conn:
            total = db.count_books(conn, **db_filters)
            pages = max(1, math.ceil(total / PAGE_SIZE))
            page = min(page, pages)
            books = db.list_books(
                conn, **db_filters, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
            )
            extras = db.book_card_extras(conn, [book["id"] for book in books])
            shelves = db.list_shelves(conn)
            types = db.list_types(conn)
        for book in books:
            book.update(extras[book["id"]])
            _card_cover(book, book.get("shelf"))

        def t(key: str, **kwargs: object) -> str:
            return translate(active_lang, key, **kwargs)

        def query_string(**extra: object) -> str:
            params: list[tuple[str, str]] = []
            for key, value in filters.items():
                if value is True:
                    params.append((key, "1"))
                elif isinstance(value, list):
                    params.extend((key, item) for item in value)
                elif value:
                    params.append((key, str(value)))
            params.extend((key, str(value)) for key, value in extra.items())
            return "/?" + urlencode(params) if params else "/"

        def page_url(target_page: int) -> str:
            return query_string(page=target_page) if target_page > 1 else query_string()

        def lang_url(target_lang: str) -> str:
            return query_string(lang=target_lang)

        # HTMX filter and paging requests get only the results fragment.
        is_htmx = "HX-Request" in request.headers
        response = templates.TemplateResponse(
            request,
            "_results.html" if is_htmx else "list.html",
            {
                "t": t,
                "lang": active_lang,
                "languages": SUPPORTED_LANGS,
                "lang_url": lang_url,
                "books": books,
                "total": total,
                "page": page,
                "pages": pages,
                "page_url": page_url,
                "clear_url": query_string(),
                "filters": filters,
                "statuses": READING_STATUSES,
                "shelves": shelves,
                "types": types,
            },
        )
        response.headers["Vary"] = "HX-Request"
        if lang in SUPPORTED_LANGS:
            response.set_cookie("lang", lang, samesite="lax")
        return response

    def render(
        request: Request,
        name: str,
        lang: str | None,
        status_code: int = 200,
        **context: object,
    ) -> HTMLResponse:
        active_lang = resolve_lang(lang, request.cookies.get("lang"), settings.default_lang)

        def t(key: str, **kwargs: object) -> str:
            return translate(active_lang, key, **kwargs)

        def lang_url(target_lang: str) -> str:
            return request.url.path + "?" + urlencode({"lang": target_lang})

        response = templates.TemplateResponse(
            request,
            name,
            {
                "t": t,
                "lang": active_lang,
                "languages": SUPPORTED_LANGS,
                "lang_url": lang_url,
                "statuses": READING_STATUSES,
                **context,
            },
            status_code=status_code,
        )
        if lang in SUPPORTED_LANGS:
            response.set_cookie("lang", lang, samesite="lax")
        return response

    def translator(request: Request, lang: str | None) -> Callable[..., str]:
        active_lang = resolve_lang(lang, request.cookies.get("lang"), settings.default_lang)
        return lambda key, **kwargs: translate(active_lang, key, **kwargs)

    @app.get("/books/new", response_class=HTMLResponse)
    def book_add_form(request: Request, lang: str | None = None) -> HTMLResponse:
        empty = {field: "" for field, _ in EDITABLE_FIELDS}
        empty["review_status"] = "ok"
        return render(request, "add.html", lang, values=empty, cover_error=None)

    @app.post("/books/new", response_model=None)
    def book_add_submit(
        request: Request,
        title: Annotated[str, Form()] = "",
        subtitle: Annotated[str, Form()] = "",
        authors: Annotated[str, Form()] = "",
        publisher: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        review_status: Annotated[str, Form()] = "ok",
        lang: str | None = None,
        cover: Annotated[UploadFile | None, File()] = None,
    ) -> HTMLResponse | RedirectResponse:
        posted = {
            "title": title,
            "subtitle": subtitle,
            "authors": authors,
            "publisher": publisher,
            "note": note,
            "review_status": review_status,
        }
        try:
            data = BookInput(**posted)
        except ValidationError:
            return render(
                request, "add.html", lang, status_code=422, values=posted, cover_error=None
            )
        photo = _cover_upload_bytes(cover)
        if photo is not None:
            try:
                _check_cover(photo)
            except ValueError:
                # Checked before anything is stored: a bad file adds no book.
                return render(
                    request,
                    "add.html",
                    lang,
                    status_code=400,
                    values=posted,
                    cover_error=translator(request, lang)("err_cover_type"),
                )
        with _open_db(settings) as conn:
            book_id = db.add_book(
                conn,
                title=data.title,
                subtitle=data.subtitle,
                author_names=_author_names(data.authors),
                publisher=data.publisher,
                note=data.note,
                review_status=data.review_status,
            )
            if photo is not None:
                file_name, color = save_cover(photo, book_id, settings.cover_dir)
                db.set_book_cover(conn, book_id, file_name, color)
        return RedirectResponse(f"/books/{book_id}", status_code=303)

    @app.post("/books/ocr", response_class=HTMLResponse, response_model=None)
    def book_ocr_suggest(
        request: Request,
        title: Annotated[str, Form()] = "",
        subtitle: Annotated[str, Form()] = "",
        authors: Annotated[str, Form()] = "",
        publisher: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        review_status: Annotated[str, Form()] = "ok",
        lang: str | None = None,
        cover: Annotated[UploadFile | None, File()] = None,
    ) -> HTMLResponse:
        """Read the cover photo and return the add form with title and author suggested.

        Nothing is saved here. Typed values are kept when OCR finds no suggestion.
        """
        posted = {
            "title": title,
            "subtitle": subtitle,
            "authors": authors,
            "publisher": publisher,
            "note": note,
            "review_status": review_status,
        }
        t = translator(request, lang)
        photo = _cover_upload_bytes(cover)
        try:
            _check_cover(photo)
        except ValueError:
            return render(
                request,
                "add.html",
                lang,
                status_code=400,
                values=posted,
                cover_error=t("err_cover_type"),
                ocr_note=None,
            )
        suggested_title, suggested_author = ocr.suggest_title_author(ocr.ocr_text(photo))
        values = dict(posted)
        if suggested_title:
            values["title"] = suggested_title
        if suggested_author:
            values["authors"] = suggested_author
        note_key = "ocr_suggestion_note" if suggested_title or suggested_author else "ocr_no_suggestion"
        return render(
            request,
            "add.html",
            lang,
            values=values,
            cover_error=None,
            ocr_note=t(note_key),
        )

    def _ask_response(
        request: Request, lang: str | None, status_code: int = 200, **context: object
    ) -> HTMLResponse:
        # HTMX asks get only the result fragment; plain requests get the whole page.
        name = "_ask_result.html" if "HX-Request" in request.headers else "ask.html"
        response = render(request, name, lang, status_code=status_code, **context)
        response.headers["Vary"] = "HX-Request"
        return response

    @app.get("/ask", response_class=HTMLResponse)
    def ask_page(request: Request, lang: str | None = None) -> HTMLResponse:
        return _ask_response(
            request, lang, question="", asked=False, searched=False, error=None, answer=None, books=[]
        )

    @app.post("/ask", response_class=HTMLResponse, response_model=None)
    def ask_submit(
        request: Request,
        question: Annotated[str, Form(min_length=1, max_length=ASK_MAX_LENGTH)],
        lang: str | None = None,
    ) -> HTMLResponse:
        """Turn a question into filters, run the normal search, then summarise the records.

        Model output is only used for searching and for display; nothing is written.
        """
        t = translator(request, lang)
        text = question.strip()
        if not text:
            return _ask_response(
                request, lang, status_code=422, question="", asked=False, searched=False,
                error=t("ask_empty"), answer=None, books=[],
            )
        active_lang = resolve_lang(lang, request.cookies.get("lang"), settings.default_lang)
        language = "Turkish" if active_lang == "tr" else "English"
        client = request.app.state.llm_client

        with _open_db(settings) as conn:
            shelves = db.list_shelves(conn)
            types = db.list_types(conn)
        try:
            filter_obj = chat_json(client, settings, _ask_filter_prompt(shelves, types), text)
        except LLMError:
            return _ask_response(
                request, lang, question=text, asked=True, searched=False,
                error=t("ask_error_unavailable"), answer=None, books=[],
            )

        kwargs = _ask_search_kwargs(parse_filters(filter_obj), shelves, types)
        with _open_db(settings) as conn:
            books = db.list_books(conn, **kwargs, limit=ASK_RESULT_LIMIT)

        try:
            summary = chat_json(client, settings, _ask_summary_prompt(language), _ask_summary_input(text, books))
            answer = _ask_answer(summary)
        except LLMError:
            answer = None
        return _ask_response(
            request, lang, question=text, asked=True, searched=True,
            error=None if answer else t("ask_error_summary"), answer=answer, books=books,
        )

    def _detail_response(
        request: Request,
        book_id: int,
        lang: str | None,
        status_code: int = 200,
        cover_error: str | None = None,
        suggestions: list[dict] | None = None,
        suggest_error: str | None = None,
    ) -> HTMLResponse:
        with _open_db(settings) as conn:
            book = db.get_book(conn, book_id)
            if book is None:
                raise HTTPException(status_code=404)
            history = db.get_history(conn, book_id)
            photos = db.list_photos(conn, book_id)
            loans = db.list_loans(conn, book_id)
            assignments = _assignments(conn, book_id)
            shelf_name = db.book_card_extras(conn, [book_id]).get(book_id, {}).get("shelf")
        # Same cover colour as the list card.
        _card_cover(book, shelf_name)
        return render(
            request,
            "detail.html",
            lang,
            status_code=status_code,
            book=book,
            book_id=book_id,
            history=history,
            photos=photos,
            loans=loans,
            cover_error=cover_error,
            suggestions=suggestions,
            suggest_error=suggest_error,
            **assignments,
        )

    @app.get("/books/{book_id}", response_class=HTMLResponse)
    def book_detail(request: Request, book_id: int, lang: str | None = None) -> HTMLResponse:
        return _detail_response(request, book_id, lang)

    def _llm_language(request: Request, lang: str | None) -> str:
        active_lang = resolve_lang(lang, request.cookies.get("lang"), settings.default_lang)
        return "Turkish" if active_lang == "tr" else "English"

    @app.post("/books/{book_id}/suggest", response_class=HTMLResponse, response_model=None)
    def book_suggest(request: Request, book_id: int, lang: str | None = None) -> HTMLResponse:
        """Ask the local model for similar books. Nothing is saved; library matches are only linked."""
        t = translator(request, lang)
        with _open_db(settings) as conn:
            book = db.get_book(conn, book_id)
            if book is None:
                raise HTTPException(status_code=404)
            type_names = [chip["name"] for chip in db.get_book_shelf_and_types(conn, book_id)["chips"]]
            library = [b for b in db.list_books(conn, limit=db.count_books(conn)) if b["id"] != book_id]
        try:
            obj = chat_json(
                request.app.state.llm_client,
                settings,
                _suggest_prompt(_llm_language(request, lang)),
                _suggest_input(book, type_names),
            )
        except LLMError:
            suggestions, error = None, t("suggest_error")
        else:
            suggestions, error = [], None
            for item in parse_suggestions(obj, limit=SUGGEST_LIMIT):
                match = next((b for b in library if in_library(item["title"], item["author"], [b])), None)
                suggestions.append({**item, "book_id": match["id"] if match else None})

        if "HX-Request" in request.headers:
            response = render(
                request,
                "_suggestions.html",
                lang,
                book_id=book_id,
                suggestions=suggestions,
                suggest_error=error,
            )
            response.headers["Vary"] = "HX-Request"
            return response
        return _detail_response(
            request, book_id, lang, suggestions=suggestions, suggest_error=error
        )

    def _complete_values(
        title: str, subtitle: str, authors: str, publisher: str, note: str, review_status: str
    ) -> dict:
        return {
            "title": title,
            "subtitle": subtitle,
            "authors": authors,
            "publisher": publisher,
            "note": note,
            "review_status": review_status,
        }

    @app.post("/books/{book_id}/complete", response_class=HTMLResponse, response_model=None)
    def book_complete(
        request: Request,
        book_id: int,
        title: Annotated[str, Form()] = "",
        subtitle: Annotated[str, Form()] = "",
        authors: Annotated[str, Form()] = "",
        publisher: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        review_status: Annotated[str, Form()] = "ok",
        lang: str | None = None,
    ) -> HTMLResponse:
        """Suggest a subtitle and publisher from the title and author. The book is not changed."""
        t = translator(request, lang)
        with _open_db(settings) as conn:
            book = db.get_book(conn, book_id)
        if book is None:
            raise HTTPException(status_code=404)
        values = _complete_values(title, subtitle, authors, publisher, note, review_status)

        offers: list[dict] = []
        error: str | None = None
        if not title.strip():
            error = t("complete_need_title")
        else:
            try:
                obj = chat_json(
                    request.app.state.llm_client,
                    settings,
                    _complete_prompt(),
                    f"Title: {title.strip()}\nAuthors: {authors.strip() or '-'}",
                )
            except LLMError:
                error = t("complete_error")
            else:
                offers = _completion_offers(values, parse_completion(obj))

        if "HX-Request" in request.headers:
            response = render(
                request,
                "_completion.html",
                lang,
                book=book,
                values=values,
                offers=offers,
                completion_error=error,
            )
            response.headers["Vary"] = "HX-Request"
            return response
        return render(
            request,
            "edit.html",
            lang,
            book=book,
            values=values,
            preview=None,
            completion_open=True,
            offers=offers,
            completion_error=error,
        )

    @app.post("/books/{book_id}/complete/apply", response_class=HTMLResponse, response_model=None)
    def book_complete_apply(
        request: Request,
        book_id: int,
        title: Annotated[str, Form()] = "",
        subtitle: Annotated[str, Form()] = "",
        authors: Annotated[str, Form()] = "",
        publisher: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        review_status: Annotated[str, Form()] = "ok",
        suggested_subtitle: Annotated[str, Form()] = "",
        suggested_publisher: Annotated[str, Form()] = "",
        apply: Annotated[list[str], Form()] = [],
        lang: str | None = None,
    ) -> HTMLResponse:
        """Copy the checked suggestions into the form fields. Nothing is saved; /edit does that."""
        with _open_db(settings) as conn:
            book = db.get_book(conn, book_id)
        if book is None:
            raise HTTPException(status_code=404)
        values = _complete_values(title, subtitle, authors, publisher, note, review_status)
        if "subtitle" in apply and suggested_subtitle.strip():
            values["subtitle"] = suggested_subtitle.strip()[:300]
        if "publisher" in apply and suggested_publisher.strip():
            values["publisher"] = suggested_publisher.strip()[:200]
        return render(request, "edit.html", lang, book=book, values=values, preview=None)

    @app.post("/books/{book_id}/cover", response_model=None)
    def book_cover_replace(
        request: Request,
        book_id: int,
        cover: Annotated[UploadFile | None, File()] = None,
        lang: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        """Replace the cover photo. The file is stored as <book_id>.jpg, so the old file is overwritten."""
        error: str | None = None
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404)
            photo = _cover_upload_bytes(cover)
            try:
                _check_cover(photo)
            except ValueError:
                error = translator(request, lang)("err_cover_type")
            else:
                file_name, color = save_cover(photo, book_id, settings.cover_dir)
                db.set_book_cover(conn, book_id, file_name, color)
        if error is not None:
            return _detail_response(request, book_id, lang, status_code=400, cover_error=error)
        return RedirectResponse(f"/books/{book_id}", status_code=303)

    @app.get("/covers/{book_id}")
    def book_cover(book_id: str) -> FileResponse:
        """Stored cover photo as JPEG. Only numeric ids are accepted; anything else is 404."""
        if not (book_id.isascii() and book_id.isdigit()):
            raise HTTPException(status_code=404)
        with _open_db(settings) as conn:
            book = db.get_book(conn, int(book_id))
        if book is None or not book["cover_file"]:
            raise HTTPException(status_code=404)
        try:
            path = Path(covers.cover_path(settings.cover_dir, book["cover_file"]))
        except ValueError:
            raise HTTPException(status_code=404)
        if not path.is_file():
            raise HTTPException(status_code=404)
        # Same URL after a replacement, so the browser must revalidate instead of reusing its copy.
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    @app.post("/books/{book_id}/shelf", response_model=None)
    def book_set_shelf(
        request: Request,
        book_id: int,
        shelf_id: Annotated[str, Form()] = "",
        lang: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        """Set or clear the shelf. HTMX gets the shelf block only; otherwise the book page."""
        is_htmx = "HX-Request" in request.headers
        raw = shelf_id.strip()
        error: str | None = None
        if raw and not raw.isdigit():
            error = translator(request, lang)("err_invalid")
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404)
            if error is None:
                try:
                    db.set_book_shelf(conn, book_id, int(raw) if raw else None)
                except ValueError as exc:
                    error = str(exc)
            if error is not None and not is_htmx:
                raise HTTPException(status_code=400, detail=error)
            assignments = _assignments(conn, book_id)
        if not is_htmx:
            return RedirectResponse(f"/books/{book_id}", status_code=303)
        response = render(
            request,
            "_shelf.html",
            lang,
            status_code=400 if error else 200,
            book_id=book_id,
            error=error,
            **assignments,
        )
        if error is None:
            # Refresh the whole book page so the history table shows the change.
            response.headers["HX-Refresh"] = "true"
        return response

    @app.post("/books/{book_id}/types", response_model=None)
    def book_set_types(
        request: Request,
        book_id: int,
        type_id: Annotated[list[str] | None, Form()] = None,
        lang: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        """Replace the type set with the posted ids. Empty values are ignored (the add picker's placeholder)."""
        is_htmx = "HX-Request" in request.headers
        values = [value.strip() for value in (type_id or []) if value.strip()]
        error: str | None = None
        if not all(value.isdigit() for value in values):
            error = translator(request, lang)("err_invalid")
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404)
            if error is None:
                try:
                    db.set_book_types(conn, book_id, [int(value) for value in values])
                except ValueError as exc:
                    error = str(exc)
            if error is not None and not is_htmx:
                raise HTTPException(status_code=400, detail=error)
            assignments = _assignments(conn, book_id)
        if not is_htmx:
            return RedirectResponse(f"/books/{book_id}", status_code=303)
        response = render(
            request,
            "_types.html",
            lang,
            status_code=400 if error else 200,
            book_id=book_id,
            error=error,
            **assignments,
        )
        if error is None:
            # Refresh the whole book page so the history table shows the change.
            response.headers["HX-Refresh"] = "true"
        return response

    @app.get("/books/{book_id}/edit", response_class=HTMLResponse)
    def book_edit_form(request: Request, book_id: int, lang: str | None = None) -> HTMLResponse:
        with _open_db(settings) as conn:
            book = db.get_book(conn, book_id)
        if book is None:
            raise HTTPException(status_code=404)
        return render(
            request, "edit.html", lang, book=book, values=_values_from_book(book), preview=None
        )

    @app.post("/books/{book_id}/edit", response_model=None)
    def book_edit_submit(
        request: Request,
        book_id: int,
        title: Annotated[str, Form()] = "",
        subtitle: Annotated[str, Form()] = "",
        authors: Annotated[str, Form()] = "",
        publisher: Annotated[str, Form()] = "",
        note: Annotated[str, Form()] = "",
        review_status: Annotated[str, Form()] = "ok",
        action: Annotated[str, Form()] = "save",
        lang: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        posted = {
            "title": title,
            "subtitle": subtitle,
            "authors": authors,
            "publisher": publisher,
            "note": note,
            "review_status": review_status,
        }
        with _open_db(settings) as conn:
            book = db.get_book(conn, book_id)
            if book is None:
                raise HTTPException(status_code=404)
            try:
                data = BookInput(**posted)
            except ValidationError:
                return render(
                    request,
                    "edit.html",
                    lang,
                    status_code=422,
                    book=book,
                    values=posted,
                    preview=None,
                )
            if action == "preview":
                t = translator(request, lang)
                return render(
                    request,
                    "edit.html",
                    lang,
                    book=book,
                    values=data.model_dump(),
                    preview=_change_summary(book, data, t),
                )
            db.update_book(conn, book_id, data.model_dump())
        return RedirectResponse(f"/books/{book_id}", status_code=303)

    @app.post("/books/{book_id}/delete")
    def book_delete(book_id: int) -> RedirectResponse:
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404)
            db.soft_delete_book(conn, book_id)
        return RedirectResponse("/", status_code=303)

    @app.post("/books/{book_id}/status", response_model=None)
    def book_status(
        request: Request,
        book_id: int,
        status: Annotated[str, Form()] = "",
        started_on: Annotated[str, Form()] = "",
        finished_on: Annotated[str, Form()] = "",
        lang: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        """Save status and dates. HTMX gets the _status.html block back; plain posts redirect."""
        htmx = "HX-Request" in request.headers
        error: str | None = None
        status_code = 200
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404)
            try:
                db.set_reading_status(conn, book_id, status, started_on, finished_on)
            except ReadingDateError as exc:
                if not htmx:
                    raise HTTPException(
                        status_code=400, detail=translator(request, lang)(exc.code)
                    ) from exc
                error, status_code = translator(request, lang)(exc.code), 400
            except ValueError as exc:
                if not htmx:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                error, status_code = str(exc), 400
            if not htmx:
                return RedirectResponse(f"/books/{book_id}", status_code=303)
            row = db.get_reading_status(conn, book_id)
        book = {
            "id": book_id,
            "status": row["status"] if row is not None else None,
            "started_on": row["started_on"] if row is not None else None,
            "finished_on": row["finished_on"] if row is not None else None,
        }
        return render(
            request,
            "_status.html",
            lang,
            status_code=status_code,
            book=book,
            status_strip=True,
            error=error,
        )

    @app.post("/books/{book_id}/status/quick", response_model=None)
    def book_status_quick(
        request: Request,
        book_id: int,
        action: Annotated[str, Form()] = "",
        lang: str | None = None,
    ) -> HTMLResponse:
        """Quick status buttons. Returns the _status.html fragment for HTMX and plain requests."""
        t = translator(request, lang)
        error: str | None = None
        status_code = 200
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404, detail=t("msg_not_found"))
            if action not in QUICK_STATUS_ACTIONS:
                error, status_code = t("err_invalid"), 400
            else:
                today = today_fn()
                current = db.get_reading_status(conn, book_id)
                # Today fills an empty date only; a stored date is kept by passing None.
                started_on = finished_on = None
                if action == "reading" and (current is None or not current["started_on"]):
                    started_on = today.isoformat()
                if action == "read" and (current is None or not current["finished_on"]):
                    finished_on = today.isoformat()
                try:
                    db.set_reading_status(
                        conn,
                        book_id,
                        QUICK_STATUS_ACTIONS[action],
                        started_on,
                        finished_on,
                        today=today,
                    )
                except ReadingDateError as exc:
                    error, status_code = t(exc.code), 400
            row = db.get_reading_status(conn, book_id)
        book = {
            "id": book_id,
            "status": row["status"] if row is not None else None,
            "finished_on": row["finished_on"] if row is not None else None,
        }
        response = render(
            request, "_status.html", lang, status_code=status_code, book=book, error=error
        )
        if error is None and "HX-Request" in request.headers:
            # Refresh the whole book page so the history table shows the change.
            response.headers["HX-Refresh"] = "true"
        return response

    @app.get("/reading", response_class=HTMLResponse)
    def reading_page(request: Request, lang: str | None = None) -> HTMLResponse:
        with _open_db(settings) as conn:
            counts = db.reading_counts(conn)
            years = db.finished_per_year(conn)
        return render(request, "reading.html", lang, counts=counts, years=years)

    def loans_view(
        request: Request, lang: str | None, error: str | None = None, status_code: int = 200
    ) -> HTMLResponse:
        with _open_db(settings) as conn:
            loans = db.open_loans(conn)
        return render(
            request,
            "loans.html",
            lang,
            status_code=status_code,
            loans=loans,
            today=date.today().isoformat(),
            error=error,
        )

    @app.get("/loans", response_class=HTMLResponse)
    def loans_page(request: Request, lang: str | None = None) -> HTMLResponse:
        return loans_view(request, lang)

    @app.post("/loans", response_model=None)
    def loan_lend(
        request: Request,
        book_id: Annotated[int, Form()],
        borrower: Annotated[str, Form()] = "",
        lent_on: Annotated[str, Form()] = "",
        lang: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        t = translator(request, lang)
        if not borrower.strip() or not lent_on.strip():
            return loans_view(request, lang, t("err_invalid"), status_code=400)
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404, detail=t("msg_not_found"))
            try:
                db.lend_book(conn, book_id, borrower, lent_on)
            except LoanError:
                error, status = t("err_already_lent"), 409
            except ValueError:
                error, status = t("err_invalid"), 400
            else:
                return RedirectResponse("/loans", status_code=303)
        return loans_view(request, lang, error, status_code=status)

    @app.post("/loans/{loan_id}/return", response_model=None)
    def loan_return(
        request: Request,
        loan_id: int,
        returned_on: Annotated[str, Form()] = "",
        lang: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        t = translator(request, lang)
        if not returned_on.strip():
            return loans_view(request, lang, t("err_invalid"), status_code=400)
        with _open_db(settings) as conn:
            try:
                db.return_book(conn, loan_id, returned_on)
            except LoanError:
                error, status = t("err_already_returned"), 409
            except ValueError:
                # return_book raises ValueError only when the loan does not exist.
                raise HTTPException(status_code=404, detail=t("msg_not_found")) from None
            else:
                return RedirectResponse("/loans", status_code=303)
        return loans_view(request, lang, error, status_code=status)

    def reason_label(reason: str, t: Callable[..., str]) -> str:
        keys = {
            "low confidence": "reason_low_confidence",
            "medium confidence": "reason_medium_confidence",
            "author missing": "reason_author_missing",
            "unreadable": "reason_unreadable",
        }
        parts = [p.strip() for p in reason.split(",") if p.strip()]
        return ", ".join(t(keys[p]) if p in keys else p for p in parts)

    @app.get("/review", response_class=HTMLResponse)
    def review_page(
        request: Request,
        page: int = Query(1, ge=1),
        lang: str | None = None,
    ) -> HTMLResponse:
        t = translator(request, lang)
        with _open_db(settings) as conn:
            # One extra row tells whether a next page exists.
            rows = db.list_review_items(
                conn, limit=PAGE_SIZE + 1, offset=(page - 1) * PAGE_SIZE
            )
        has_next = len(rows) > PAGE_SIZE
        items = [
            {**row, "reason_label": reason_label(row["reason"], t)}
            for row in rows[:PAGE_SIZE]
        ]
        return render(
            request,
            "review.html",
            lang,
            items=items,
            page=page,
            has_prev=page > 1,
            has_next=has_next,
        )

    @app.post("/review/{item_id}", response_model=None)
    def review_resolve(
        request: Request,
        item_id: int,
        action: Annotated[str, Form()] = "",
        lang: str | None = None,
    ) -> RedirectResponse:
        t = translator(request, lang)
        with _open_db(settings) as conn:
            try:
                db.resolve_review_item(conn, item_id, action)
            except ValueError:
                raise HTTPException(status_code=400, detail=t("err_invalid")) from None
            except LookupError:
                raise HTTPException(status_code=404, detail=t("msg_not_found")) from None
            except ReviewError:
                raise HTTPException(status_code=409, detail=t("err_already_resolved")) from None
        return RedirectResponse("/review", status_code=303)

    def _mount_manage(
        path: str,
        template: str,
        list_fn: Callable[[sqlite3.Connection], list[dict]],
        add_fn: Callable[[sqlite3.Connection, str], int],
        rename_fn: Callable[[sqlite3.Connection, int, str], None],
        delete_fn: Callable[[sqlite3.Connection, int], None],
        taken_key: str,
    ) -> None:
        """List, create, rename and soft-delete routes for shelves or types."""

        def page(
            request: Request,
            lang: str | None,
            status_code: int = 200,
            error: str | None = None,
            form_name: str = "",
        ) -> HTMLResponse:
            with _open_db(settings) as conn:
                items = list_fn(conn)
            return render(
                request,
                template,
                lang,
                status_code=status_code,
                items=items,
                error=error,
                form_name=form_name,
            )

        def after_write(lang: str | None) -> RedirectResponse:
            target = f"{path}?lang={lang}" if lang in SUPPORTED_LANGS else path
            return RedirectResponse(target, status_code=303)

        @app.get(path, response_class=HTMLResponse)
        def manage_list(request: Request, lang: str | None = None) -> HTMLResponse:
            return page(request, lang)

        @app.post(path, response_model=None)
        def manage_add(
            request: Request,
            name: Annotated[str, Form()] = "",
            lang: str | None = None,
        ) -> HTMLResponse | RedirectResponse:
            t = translator(request, lang)
            cleaned = name.strip()
            if not norm(cleaned):
                return page(request, lang, 422, error=t("err_name_required"), form_name=name)
            try:
                with _open_db(settings) as conn:
                    add_fn(conn, cleaned)
            except NameTakenError:
                return page(request, lang, 409, error=t(taken_key), form_name=cleaned)
            return after_write(lang)

        @app.post(path + "/{item_id}/rename", response_model=None)
        def manage_rename(
            request: Request,
            item_id: int,
            name: Annotated[str, Form()] = "",
            lang: str | None = None,
        ) -> HTMLResponse | RedirectResponse:
            t = translator(request, lang)
            cleaned = name.strip()
            if not norm(cleaned):
                return page(request, lang, 422, error=t("err_name_required"), form_name=name)
            try:
                with _open_db(settings) as conn:
                    rename_fn(conn, item_id, cleaned)
            except NameTakenError:
                return page(request, lang, 409, error=t(taken_key), form_name=cleaned)
            except ValueError:
                raise HTTPException(status_code=404, detail=t("msg_not_found")) from None
            return after_write(lang)

        @app.post(path + "/{item_id}/delete", response_model=None)
        def manage_delete(
            request: Request,
            item_id: int,
            lang: str | None = None,
        ) -> RedirectResponse:
            t = translator(request, lang)
            with _open_db(settings) as conn:
                try:
                    delete_fn(conn, item_id)
                except ValueError:
                    raise HTTPException(status_code=404, detail=t("msg_not_found")) from None
            return after_write(lang)

    _mount_manage(
        "/shelves",
        "shelves.html",
        db.list_shelves,
        db.add_shelf,
        db.rename_shelf,
        db.delete_shelf,
        "err_shelf_name_taken",
    )
    _mount_manage(
        "/types",
        "types.html",
        db.list_types,
        db.add_type,
        db.rename_type,
        db.delete_type,
        "err_type_name_taken",
    )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, lang: str | None = None) -> HTMLResponse:
        return render(request, "settings.html", lang, backup_path=None)

    @app.post("/settings/backup", response_class=HTMLResponse)
    def settings_backup(request: Request, lang: str | None = None) -> HTMLResponse:
        with _open_db(settings):
            pass  # make sure the schema exists so the copy is a usable database
        path = make_backup(settings.db_path, settings.backup_dir, datetime.now())
        return render(request, "settings.html", lang, backup_path=path)

    @app.get("/settings/export.csv")
    def settings_export_csv() -> Response:
        with tempfile.TemporaryDirectory() as tmp_dir, _open_db(settings) as conn:
            out_path = str(Path(tmp_dir) / "books.csv")
            export_csv(conn, out_path)
            content = Path(out_path).read_bytes()
        return Response(
            content,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="library.csv"'},
        )

    @app.post("/settings/theme", response_model=None)
    def settings_theme(
        request: Request,
        value: Annotated[str, Form(alias="theme")] = "",
    ) -> RedirectResponse:
        if value not in THEMES:
            t = translator(request, None)
            raise HTTPException(status_code=400, detail=t("err_invalid"))
        # Return to the page the switch was used on, if it is on this site.
        target = "/"
        referer = urlsplit(request.headers.get("referer", ""))
        if referer.netloc == request.url.netloc and referer.path.startswith("/"):
            target = referer.path + (f"?{referer.query}" if referer.query else "")
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(THEME_COOKIE, value, max_age=THEME_MAX_AGE, samesite="lax")
        return response

    @app.post("/settings/language", response_model=None)
    def settings_language(
        request: Request,
        value: Annotated[str, Form(alias="lang")] = "",
    ) -> RedirectResponse:
        if value not in SUPPORTED_LANGS:
            t = translator(request, None)
            raise HTTPException(status_code=400, detail=t("err_invalid"))
        response = RedirectResponse(f"/settings?lang={value}", status_code=303)
        response.set_cookie("lang", value, samesite="lax")
        return response

    return app
