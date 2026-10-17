import math
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field, ValidationError, field_validator

from library import db
from library.backup import export_csv, make_backup
from library.config import Settings
from library.db import READING_STATUSES, LoanError, ReadingDateError, ReviewError
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


def _shelf_param(value: str) -> tuple[int | None, bool]:
    """Shelf filter from the query: (shelf id, no_shelf). Empty or invalid means no filter."""
    if value == "none":
        return None, True
    if value.isdigit():
        return int(value), False
    return None, False


def _type_params(values: list[str]) -> list[int]:
    return [int(value) for value in values if value.isdigit()]


def _card_extras(conn: sqlite3.Connection, book_ids: list[int]) -> dict[int, dict]:
    """Shelf name, type names and finished date for the list cards.

    Read here instead of in db.py, which only takes filter parameters for the list.
    """
    extras: dict[int, dict] = {
        book_id: {"shelf": None, "types": [], "finished_on": None} for book_id in book_ids
    }
    if not book_ids:
        return extras
    marks = ", ".join("?" for _ in book_ids)
    for row in conn.execute(
        f"SELECT b.id, s.name FROM book b JOIN shelf s ON s.id = b.shelf_id "
        f"WHERE b.id IN ({marks})",
        book_ids,
    ):
        extras[row["id"]]["shelf"] = row["name"]
    for row in conn.execute(
        "SELECT bt.book_id, t.name FROM book_type bt JOIN type t ON t.id = bt.type_id "
        f"WHERE t.deleted_at IS NULL AND bt.book_id IN ({marks}) ORDER BY t.norm_name, t.id",
        book_ids,
    ):
        extras[row["book_id"]]["types"].append(row["name"])
    for row in conn.execute(
        f"SELECT book_id, finished_on FROM reading_status WHERE book_id IN ({marks})", book_ids
    ):
        extras[row["book_id"]]["finished_on"] = row["finished_on"]
    return extras


# Quick status action -> reading status it sets.
QUICK_STATUS_ACTIONS = {"read": "read", "reading": "reading", "abandon": "abandoned"}


def create_app(
    settings: Settings | None = None, today_fn: Callable[[], date] = date.today
) -> FastAPI:
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
            extras = _card_extras(conn, [book["id"] for book in books])
            shelves = db.list_shelves(conn)
            types = db.list_types(conn)
        for book in books:
            book.update(extras[book["id"]])

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
        request: Request,
        book_id: int,
        status: Annotated[str, Form()] = "",
        started_on: Annotated[str, Form()] = "",
        finished_on: Annotated[str, Form()] = "",
        lang: str | None = None,
    ) -> RedirectResponse:
        with _open_db(settings) as conn:
            if db.get_book(conn, book_id) is None:
                raise HTTPException(status_code=404)
            try:
                db.set_reading_status(conn, book_id, status, started_on, finished_on)
            except ReadingDateError as exc:
                raise HTTPException(
                    status_code=400, detail=translator(request, lang)(exc.code)
                ) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"/books/{book_id}", status_code=303)

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
                current = conn.execute(
                    "SELECT started_on, finished_on FROM reading_status WHERE book_id = ?",
                    (book_id,),
                ).fetchone()
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
            row = conn.execute(
                "SELECT status, finished_on FROM reading_status WHERE book_id = ?", (book_id,)
            ).fetchone()
        book = {
            "id": book_id,
            "status": row["status"] if row is not None else None,
            "finished_on": row["finished_on"] if row is not None else None,
        }
        return render(
            request, "_status.html", lang, status_code=status_code, book=book, error=error
        )

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
