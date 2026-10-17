import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field, ValidationError, field_validator

from library import db
from library.config import Settings
from library.db import READING_STATUSES
from library.i18n import SUPPORTED_LANGS, resolve_lang, translate

WEB_DIR = Path(__file__).parent
PAGE_SIZE = 50

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

templates = Jinja2Templates(
    env=Environment(
        loader=FileSystemLoader(WEB_DIR / "templates"),
        autoescape=select_autoescape(["html"]),
    )
)


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


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings.from_env()

    app = FastAPI(title="Personal Library")
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def book_list(
        request: Request,
        q: str = "",
        status: str = "",
        loan: bool = False,
        publisher: str = "",
        author: str = "",
        needs_review: bool = False,
        page: int = Query(1, ge=1),
        lang: str | None = None,
    ) -> HTMLResponse:
        active_lang = resolve_lang(lang, request.cookies.get("lang"), settings.default_lang)
        filters = {
            "q": q.strip(),
            "status": status if status in READING_STATUSES else "",
            "loan": loan,
            "publisher": publisher.strip(),
            "author": author.strip(),
            "needs_review": needs_review,
        }
        db_filters = {
            "query": filters["q"],
            "status": filters["status"] or None,
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

        def t(key: str, **kwargs: object) -> str:
            return translate(active_lang, key, **kwargs)

        def query_string(**extra: object) -> str:
            params: dict[str, object] = {}
            for key, value in filters.items():
                if value is True:
                    params[key] = "1"
                elif value:
                    params[key] = value
            params.update(extra)
            return "/?" + urlencode(params)

        def page_url(target_page: int) -> str:
            return query_string(page=target_page) if target_page > 1 else query_string()

        def lang_url(target_lang: str) -> str:
            return query_string(lang=target_lang)

        response = templates.TemplateResponse(
            request,
            "list.html",
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
                "filters": filters,
                "statuses": READING_STATUSES,
            },
        )
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
        return render(request, "add.html", lang, values=empty)

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
            return render(request, "add.html", lang, status_code=422, values=posted)
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
        return RedirectResponse(f"/books/{book_id}", status_code=303)

    @app.get("/books/{book_id}", response_class=HTMLResponse)
    def book_detail(request: Request, book_id: int, lang: str | None = None) -> HTMLResponse:
        with _open_db(settings) as conn:
            book = db.get_book(conn, book_id)
            if book is None:
                raise HTTPException(status_code=404)
            history = db.get_history(conn, book_id)
            photos = db.list_photos(conn, book_id)
            loans = db.list_loans(conn, book_id)
        return render(
            request, "detail.html", lang, book=book, history=history, photos=photos, loans=loans
        )

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

    @app.post("/books/{book_id}/status")
    def book_status(
        book_id: int,
        status: Annotated[str, Form()] = "",
        started_on: Annotated[str, Form()] = "",
        finished_on: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404)
            try:
                db.set_reading_status(conn, book_id, status, started_on, finished_on)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"/books/{book_id}", status_code=303)

    return app
