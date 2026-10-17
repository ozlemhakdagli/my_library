# Personal Library Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (owner-chosen: parallel Haiku agents) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single-user, Docker-hosted, bilingual (English/Turkish) library web app that imports the existing 431 books and supports search, editing, reading status, loans, change history, a review queue, backup, and CSV export.

**Architecture:** FastAPI serves server-rendered Jinja2 pages. SQLite holds all data in a file inside a Docker volume. Pure-Python modules (`norm`, `merge`) hold the matching rules; `db.py` is the only module that touches SQL; the web layer calls `db.py` and never SQL directly.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Pydantic, uvicorn, SQLite (stdlib `sqlite3`), pytest, httpx (for `TestClient`), Docker / docker compose.

**Spec:** `docs/superpowers/specs/2026-10-17-kutuphane-arayuz-design.md`

## Global Constraints

- Python 3.12 in the container; the host venv is 3.14 and must still run the tests. No syntax beyond 3.12.
- Port `8765`, read from env var `LIBRARY_PORT` (default `8765`).
- Database path from env var `LIBRARY_DB` (default `/data/library.db` in the container).
- Default UI language: `en`. Supported: `en`, `tr`. Language is set by `?lang=` (also stored in a cookie named `lang`).
- Search is accent- and case-insensitive for Turkish letters: `norm()` as defined in Task 2.
- Empty author or publisher is displayed as `unknown` (EN) / `bilinmiyor` (TR). Never filled from memory.
- Photos: only file names are stored; the photo root is never stored in the database.
- Deletes are soft (`deleted_at`). No row is ever physically removed by the app.
- Every write that changes a field also writes one `history` row per changed field, in the same transaction.
- Commits: author is the owner's git identity (ozlemhakdagli). Every commit ends with the trailer `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>` so Claude is visible but secondary; the owner is the primary author. Commit messages in English, conventional prefixes (`feat:`, `test:`, `fix:`, `chore:`, `docs:`).
- Pull request descriptions (if any) end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Source files `data/raw/*.jsonl` and `build_excel.py` are never modified by the app.

## Review Focus

Inputs the spec implies but no task's tests might otherwise exercise:

1. Search for `Yapay Zekâ` must match `yapay zeka`, `YAPAY ZEKA`, and `Yapay Zeka` (Turkish dotted/dotless I). Owned by Task 2.
2. A book with no author and no publisher renders `unknown` and does not crash the list or detail page. Owned by Task 9 and Task 10.
3. Returning a book twice, or lending a book that is already out, is rejected with a clear error and writes nothing. Owned by Task 7.
4. Running the importer twice, and running it after a partial previous import, creates no duplicate books. Owned by Task 6.
5. A photo file name containing spaces or Turkish characters renders and is not turned into a path on the server. Owned by Task 10.

---

## File Structure

```
.gitignore  README.md  pyproject.toml  Dockerfile  docker-compose.yml
src/library/__init__.py       package marker
src/library/config.py         env-based settings (port, db path, default lang)
src/library/norm.py           norm() — text normalization for search and matching
src/library/merge.py          merge/review rules ported from build_excel.py
src/library/db.py             schema, connection, all SQL, history writes
src/library/importer.py       data/raw/*.jsonl -> db, idempotent, count check
src/library/i18n.py           translation dictionaries and language resolution
src/library/web/app.py        FastAPI app factory and routes
src/library/web/templates/    Jinja2 templates (base, list, detail, edit, add, loans, review, settings)
src/library/web/static/       one CSS file
tests/                        mirrors src/library
```

---

### Task 1: Repository skeleton, health route, Docker

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `Dockerfile`, `docker-compose.yml`
- Create: `src/library/__init__.py`, `src/library/config.py`, `src/library/web/__init__.py`, `src/library/web/app.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Produces: `library.config.Settings` (fields: `port: int`, `db_path: str`, `default_lang: str`), built by `Settings.from_env()`.
- Produces: `library.web.app.create_app(settings: Settings | None = None) -> FastAPI`. Route `GET /health` returns `{"status": "ok"}`.

- [ ] **Step 1: `git init` and first commit of existing files**

Run: `git init -b main && git add docs && git commit -m "docs: add approved design spec and plan"`
Expected: a commit on `main`. Confirm `git log --format='%an <%ae>' -1` shows `ozlemhakdagli`.

- [ ] **Step 2: Write the failing test `tests/test_health.py`**

```python
from fastapi.testclient import TestClient
from library.web.app import create_app


def test_health_returns_ok():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run it and see it fail**

Run: `.venv/bin/python -m pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'library'`.

- [ ] **Step 4: Create `pyproject.toml`, `.gitignore`, `README.md`, and install dependencies**

`pyproject.toml` declares package `library` under `src/`, runtime deps `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, and dev deps `pytest`, `httpx`. `.gitignore` lists: `.venv/`, `data/`, `*.db`, `*.db-journal`, `exports/`, `backups/`, `*.xlsx`, `*.csv`, `__pycache__/`, `.pytest_cache/`. README: one paragraph in English plus the run command.

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: installs without error.

- [ ] **Step 5: Implement `config.py`, `app.py`, package markers**

`Settings.from_env()` reads `LIBRARY_PORT` (int, default 8765), `LIBRARY_DB` (default `/data/library.db`), `LIBRARY_DEFAULT_LANG` (default `en`). `create_app` returns a FastAPI instance with the `/health` route.

- [ ] **Step 6: Run the test and see it pass**

Run: `.venv/bin/python -m pytest tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 7: Write `Dockerfile` and `docker-compose.yml`**

`Dockerfile`: base `python:3.12-slim`, copy `pyproject.toml` and `src/`, `pip install .`, `ENV LIBRARY_DB=/data/library.db`, `EXPOSE 8765`, command `uvicorn library.web.app:create_app --factory --host 0.0.0.0 --port 8765`.
`docker-compose.yml`: one service `library`, `build: .`, `ports: ["8765:8765"]`, `volumes: ["library-data:/data"]`, `restart: unless-stopped`; top-level `volumes: library-data:`.

- [ ] **Step 8: Verify the image builds and serves health**

Run: `docker compose up -d --build && curl -s http://localhost:8765/health && docker compose down`
Expected: `{"status":"ok"}`.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore README.md Dockerfile docker-compose.yml src tests
git commit -m "chore: scaffold app, health route, Docker setup"
```

---

### Task 2: Text normalization (`norm`)

**Files:**
- Create: `src/library/norm.py`
- Test: `tests/test_norm.py`

**Interfaces:**
- Produces: `norm(text: str | None) -> str`. Returns `""` for `None`.
- Behavior: `İ`→`i`, `I`→`ı`, then lowercase, then `ı`→`i`, then NFKD and drop combining marks (so `ş`→`s`, `ğ`→`g`, `ü`→`u`, `ö`→`o`, `ç`→`c`, `â`→`a`, `î`→`i`, `û`→`u`), then drop everything that is not a letter or digit.

- [ ] **Step 1: Write the failing test**

```python
from library.norm import norm


def test_turkish_accent_insensitive():
    assert norm("Yapay Zekâ") == norm("YAPAY ZEKA") == norm("yapay zeka")


def test_dotted_and_dotless_i():
    assert norm("Işık") == norm("ışık") == norm("Isik")
    assert norm("İnsan") == norm("insan")


def test_none_is_empty():
    assert norm(None) == ""


def test_punctuation_removed():
    assert norm("Su'dan \"Cola\"ya") == norm("Sudan Colaya")
```

- [ ] **Step 2: Run and see it fail**

Run: `.venv/bin/python -m pytest tests/test_norm.py -v`
Expected: FAIL, `ImportError` for `library.norm`.

- [ ] **Step 3: Implement `norm` in `src/library/norm.py`**

Implement the behavior above. Keep the exact order of steps from the Behavior line: the dotted/dotless pre-mapping must happen before lowercasing.

- [ ] **Step 4: Run and see it pass**

Run: `.venv/bin/python -m pytest tests/test_norm.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/norm.py tests/test_norm.py
git commit -m "feat: add accent- and case-insensitive text normalization"
```

---

### Task 3: Merge and review rules

**Files:**
- Create: `src/library/merge.py`
- Test: `tests/test_merge.py`
- Reference (do not modify): `src/build_excel.py` — the rules to port are its grouping, author-compatibility, publisher-conflict, subtitle-conflict, same-photo, volume-number, and partial-reading rules.

**Interfaces:**
- Consumes: `library.norm.norm(text) -> str`.
- Produces: `RawBook` dataclass with fields `title, subtitle, author, publisher, kind, confidence, note, photo: str, photo_note: str`.
- Produces: `group_books(records: list[RawBook]) -> MergeResult`, where `MergeResult` has `main: list[Book]`, `merged: list[MergeGroup]`, `review: list[ReviewItem]`, `unreadable: int`.
- Produces: `can_merge(a: RawBook, b: RawBook) -> bool`, `author_compatible(a: str, b: str) -> bool`.

- [ ] **Step 1: Read the reference rules**

Read `src/build_excel.py` in full. Note each rule name and threshold. The existing test file `tests/test_build_excel.py` (54 tests overall in the repo) is the behavioral reference.

- [ ] **Step 2: Write failing tests for each ported rule**

One test per rule, named after the rule. Required cases:
- same normalized title, compatible author, different photo → merges
- same photo, same title → never merges
- publishers both set and conflicting (`Domingo` vs `Can Yayınları`) → does not merge
- partial low-confidence reading with a longer matching title (`Zor Kadınlara Öğüt` vs `Zor Kadınlara Övgü`) → merges only when the spec's partial-reading rule holds
- short titles (norm length < 6) never match by substring
- volume numbers differ (`Aromaterapi Karışımları 1` vs `… 2`) → no merge
- `[okunamadı]` records never enter the main list

- [ ] **Step 3: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_merge.py -v`
Expected: FAIL, import errors.

- [ ] **Step 4: Port the rules to `src/library/merge.py`**

Same thresholds and decision order as the reference. No I/O in this module.

- [ ] **Step 5: Run and see them pass; confirm the reference tests still pass**

Run: `.venv/bin/python -m pytest tests/test_merge.py tests/test_build_excel.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/library/merge.py tests/test_merge.py
git commit -m "feat: port merge and review rules into library package"
```

---

### Task 4: Database schema and connection

**Files:**
- Create: `src/library/db.py` (schema and connection part only)
- Test: `tests/test_db_schema.py`

**Interfaces:**
- Produces: `connect(path: str) -> sqlite3.Connection` with `row_factory = sqlite3.Row`, `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL`.
- Produces: `init_schema(conn: sqlite3.Connection) -> None`, idempotent (`CREATE TABLE IF NOT EXISTS`).
- Tables exactly as in the spec's data model, plus `deleted_at TEXT` on `book`, `author`, `publisher`; `review_status TEXT NOT NULL DEFAULT 'ok'` on `book`; `review_item` with `reason TEXT NOT NULL`.

- [ ] **Step 1: Write failing tests**

Required assertions:
- `init_schema` on an empty in-memory DB creates tables `book, author, book_author, publisher, photo, reading_status, loan, history, review_item`.
- Calling `init_schema` twice does not raise.
- Inserting a `book_author` row with a non-existent `book_id` raises `sqlite3.IntegrityError` (foreign keys on).

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_db_schema.py -v`
Expected: FAIL, import error.

- [ ] **Step 3: Implement `connect` and `init_schema` in `src/library/db.py`**

Use `CREATE TABLE IF NOT EXISTS` for each table. Use `TEXT` for timestamps in ISO-8601 UTC.

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_db_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/db.py tests/test_db_schema.py
git commit -m "feat: add SQLite schema and connection"
```

---

### Task 5: Repository functions with history

**Files:**
- Modify: `src/library/db.py`
- Test: `tests/test_db_books.py`

**Interfaces:**
- Consumes: `connect`, `init_schema` from Task 4; `norm` from Task 2.
- Produces:
  - `add_book(conn, *, title: str, subtitle: str = "", author_names: list[str] = [], publisher: str = "", note: str = "", review_status: str = "ok") -> int`
  - `get_book(conn, book_id: int) -> dict | None` (includes `authors: list[str]`, `publisher: str`, `status`, `loan`)
  - `update_book(conn, book_id: int, changes: dict[str, str], ) -> list[HistoryEntry]` — writes one history row per changed field in the same transaction; returns no entries if nothing changed
  - `soft_delete_book(conn, book_id: int) -> None`
  - `list_books(conn, *, query: str = "", status: str | None = None, loan: str | None = None, publisher: str | None = None, author: str | None = None, needs_review: bool = False, limit: int = 50, offset: int = 0) -> list[dict]` — search uses `norm()` on title, authors, publisher
  - `count_books(conn, **same_filters) -> int`

- [ ] **Step 1: Write failing tests**

Required:
- `add_book` then `get_book` round-trips title, subtitle, authors (in order), publisher.
- `update_book` with a changed title writes exactly one `history` row with the old and new title.
- `update_book` with no changes writes no history.
- `list_books(query="Yapay Zekâ")` finds a book titled `yapay zeka` (Review Focus 1).
- `soft_delete_book` hides the book from `list_books` but `history` rows remain.
- `get_book` on a book with no author and no publisher returns `authors == []` and `publisher == ""`.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_db_books.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the functions**

Each write function uses `with conn:` (one transaction). Author and publisher rows are created on demand with `norm_name` set. `list_books` builds its SQL with bound parameters only.

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_db_books.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/db.py tests/test_db_books.py
git commit -m "feat: add book repository functions with change history"
```

---

### Task 6: Importer with count check

**Files:**
- Create: `src/library/importer.py`
- Test: `tests/test_importer.py`

**Interfaces:**
- Consumes: `merge.group_books` and `merge.RawBook` from Task 3; `db.add_book`, `db.count_books` etc. from Task 5; `db.init_schema` from Task 4.
- Produces: `import_raw(conn, raw_dir: str) -> ImportReport` where `ImportReport` has `main_books: int`, `review_items: int`, `photos: int`, `merged_records: int`, `unreadable: int`.
- Produces: `check_counts(report: ImportReport, expected: dict[str, int]) -> None`, raising `ImportCountMismatch` on any difference. Expected values for the real run: `{"main_books": 431, "review_items": 78, "photos": 410}`.

- [ ] **Step 1: Write failing tests**

Use a temp dir with two small `batch_01.jsonl` / `batch_02.jsonl` fixtures written in the test.
Required:
- Importing twice into the same DB yields the same counts and no duplicate `book` rows (Review Focus 4).
- Importing when the DB already has the first batch only completes without duplicates.
- A record with `title == "[okunamadı]"` goes to `review_item`, not `book`.
- `check_counts` raises `ImportCountMismatch` when a count differs, and the importer does not commit (transaction rolled back).

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_importer.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `import_raw` and `check_counts`**

Read `data/raw/*.jsonl` in sorted order. Parse each line as one photo record with a `books` list. Call `merge.group_books`. Insert inside one transaction. Idempotence: before inserting, skip books whose `norm_title` and photo file name already exist. Run `check_counts` before commit; on mismatch, roll back.

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_importer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/importer.py tests/test_importer.py
git commit -m "feat: add idempotent importer with count verification"
```

---

### Task 7: Reading status and loans

**Files:**
- Modify: `src/library/db.py`
- Test: `tests/test_db_status_loans.py`

**Interfaces:**
- Consumes: Task 5 functions.
- Produces:
  - `set_reading_status(conn, book_id: int, status: str, started_on: str | None = None, finished_on: str | None = None) -> None`. `status` ∈ `{"unread", "reading", "read", "abandoned"}`; raises `ValueError` otherwise. Writes a history row.
  - `lend_book(conn, book_id: int, borrower: str, lent_on: str) -> int`. Raises `LoanError("already lent")` if an open loan exists. Writes a history row.
  - `return_book(conn, loan_id: int, returned_on: str) -> None`. Raises `LoanError("already returned")` if the loan is closed.
  - `open_loans(conn) -> list[dict]`

- [ ] **Step 1: Write failing tests**

Required (Review Focus 3):
- lending a book twice without return raises `LoanError`, and the second call writes no loan row.
- returning twice raises `LoanError`.
- invalid status `"lost"` raises `ValueError`.
- `open_loans` lists only books with empty `returned_on`.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_db_status_loans.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the functions**

Validation happens before any write. Each write is one transaction.

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_db_status_loans.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/db.py tests/test_db_status_loans.py
git commit -m "feat: add reading status and loan tracking"
```

---

### Task 8: Translations and language selection

**Files:**
- Create: `src/library/i18n.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Produces: `resolve_lang(query_lang: str | None, cookie_lang: str | None, default: str) -> str` (returns `"en"` or `"tr"`; invalid values fall back to `default`).
- Produces: `translate(lang: str, key: str, **kwargs) -> str`. Missing key in `tr` falls back to `en`; missing in both returns the key itself.
- Produces: `DICTIONARIES: dict[str, dict[str, str]]` with identical key sets for `en` and `tr`.

- [ ] **Step 1: Write failing tests**

Required:
- `resolve_lang("tr", None, "en") == "tr"`; `resolve_lang("fr", None, "en") == "en"`; `resolve_lang(None, "tr", "en") == "tr"`; query beats cookie.
- Both dictionaries have the same key set (test iterates keys).
- `translate("tr", "unknown") == "bilinmiyor"` and `translate("en", "unknown") == "unknown"`.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_i18n.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `i18n.py`**

Keys needed for the UI: nav labels, page titles, field labels, status names (`unread`, `reading`, `read`, `abandoned`), button labels, messages, `unknown`, `needs_review`. Keep the English value as the key-readable default.

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_i18n.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/i18n.py tests/test_i18n.py
git commit -m "feat: add English and Turkish translations with language resolution"
```

---

### Task 9: Web — list, search, filters, language switch

**Files:**
- Modify: `src/library/web/app.py`
- Create: `src/library/web/templates/base.html`, `src/library/web/templates/list.html`, `src/library/web/static/style.css`
- Test: `tests/test_web_list.py`

**Interfaces:**
- Consumes: `db.list_books`, `db.count_books`, `i18n.resolve_lang`, `i18n.translate`.
- Produces: `GET /` with query params `q`, `status`, `loan`, `publisher`, `author`, `needs_review`, `page`, `lang`. Sets cookie `lang` when `lang` is given. Renders `list.html`.
- `create_app` now receives the DB path from `Settings` and opens a connection per request (dependency).

- [ ] **Step 1: Write failing tests**

Required:
- `GET /` returns 200 and includes the book title.
- `GET /?q=Yapay%20Zekâ` finds a book titled `yapay zeka` (Review Focus 1).
- `GET /?lang=tr` returns Turkish page text (e.g. `Kitaplar`) and sets cookie `lang=tr`.
- A book with no author and no publisher renders `unknown` and the page is 200 (Review Focus 2).

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_web_list.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement routes and templates**

Use Jinja2 with autoescape on. Every visible string goes through `translate`. Pagination: 50 per page. Filters are plain form controls, not JavaScript.

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_web_list.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/web tests/test_web_list.py
git commit -m "feat: add book list with search, filters and language switch"
```

---

### Task 10: Web — detail, edit, add, delete

**Files:**
- Modify: `src/library/web/app.py`
- Create: `src/library/web/templates/detail.html`, `src/library/web/templates/edit.html`, `src/library/web/templates/add.html`
- Test: `tests/test_web_books.py`

**Interfaces:**
- Consumes: Task 5 and Task 7 functions; `i18n.translate`.
- Produces:
  - `GET /books/{id}` — detail page, includes reading status, loans, history, and photo file names. Photo file names are shown as text only; no link to a server path (Review Focus 5).
  - `GET /books/{id}/edit`, `POST /books/{id}/edit` — validates with a Pydantic model (`title` required, max 300 chars); on success calls `update_book` and redirects to detail.
  - `GET /books/new`, `POST /books/new` — add form.
  - `POST /books/{id}/delete` — calls `soft_delete_book`, redirects to `/`.
  - `POST /books/{id}/status` — calls `set_reading_status`; a `ValueError` returns HTTP 400.

- [ ] **Step 1: Write failing tests**

Required:
- POST edit with a new title, then GET detail shows the new title and the history section shows the old title.
- POST edit with an empty title returns 422 and the DB is unchanged.
- A photo file name `20261017 094020 (1).jpg` renders as text and no `/run/media` path appears in the page (Review Focus 5).
- POST delete hides the book from `/` and the book's history remains.
- POST status with `"lost"` returns 400.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_web_books.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement routes and templates**

Every form has a CSRF-safe pattern appropriate to a local app: POST-only mutations, no GET side effects. The edit page shows a summary of changed fields before saving (compare posted values to current values server-side and render them).

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_web_books.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/web tests/test_web_books.py
git commit -m "feat: add book detail, edit, add and soft delete"
```

---

### Task 11: Web — loans and review queue

**Files:**
- Modify: `src/library/web/app.py`
- Create: `src/library/web/templates/loans.html`, `src/library/web/templates/review.html`
- Test: `tests/test_web_loans_review.py`

**Interfaces:**
- Consumes: Task 7 `open_loans`, `lend_book`, `return_book`; `db.list_review_items`, `db.resolve_review_item(conn, item_id: int, action: str) -> None` where `action` ∈ `{"confirm", "not_a_book"}`. (`db.list_review_items` and `db.resolve_review_item` are added in this task alongside their tests.)
- Produces:
  - `GET /loans`, `POST /loans` (lend), `POST /loans/{id}/return`.
  - `GET /review`, `POST /review/{id}` with `action` form field. "correct" is handled by redirecting to the book's edit page.

- [ ] **Step 1: Write failing tests**

Required:
- lend, then `GET /loans` lists the book; return, then it disappears.
- lending twice returns 409 and no second loan row is created.
- `GET /review` lists 78 items when the importer has run on the real data (skipped in CI if raw data is absent; marked with `pytest.mark.skipif`).
- POST review `not_a_book` removes the item from the queue and keeps the book's history.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_web_loans_review.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement routes, templates, and the two new db functions**

Map `LoanError` to 409 in the web layer.

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_web_loans_review.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/web src/library/db.py tests/test_web_loans_review.py
git commit -m "feat: add loans screen and review queue"
```

---

### Task 12: Web — settings, backup, CSV export

**Files:**
- Modify: `src/library/web/app.py`
- Create: `src/library/web/templates/settings.html`, `src/library/backup.py`
- Test: `tests/test_backup_export.py`

**Interfaces:**
- Produces: `backup.make_backup(db_path: str, backup_dir: str, now: datetime) -> str` returns the backup file path; uses SQLite's online backup API (`sqlite3.Connection.backup`), file name `library-YYYYMMDD-HHMMSS.db`.
- Produces: `backup.export_csv(conn, out_path: str) -> int` returns row count; UTF-8 with BOM; columns: `id,title,subtitle,authors,publisher,status,on_loan,note`.
- Routes: `GET /settings`, `POST /settings/backup`, `GET /settings/export.csv`, `POST /settings/language` (sets cookie).

- [ ] **Step 1: Write failing tests**

Required:
- `make_backup` on a DB with one book produces a file that opens and contains that book.
- `export_csv` writes a UTF-8 BOM and a row per non-deleted book; deleted books are excluded.
- `GET /settings/export.csv` returns `text/csv` with the header row.

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/python -m pytest tests/test_backup_export.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `backup.py` and the routes**

Backup directory from env var `LIBRARY_BACKUP_DIR` (default `/data/backups`).

- [ ] **Step 4: Run and see them pass**

Run: `.venv/bin/python -m pytest tests/test_backup_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/library/backup.py src/library/web tests/test_backup_export.py
git commit -m "feat: add backup, CSV export and settings page"
```

---

### Task 13: Container run, smoke test, and first real import

**Files:**
- Modify: `docker-compose.yml`, `README.md`
- Create: `scripts/import_books.sh`, `tests/test_smoke.sh`

**Interfaces:**
- `scripts/import_books.sh` runs `python -m library.importer` inside the container against the mounted raw data. Raw data is mounted read-only from the host path given by env var `LIBRARY_RAW_DIR`.

- [ ] **Step 1: Add the raw-data mount to compose**

`docker-compose.yml` adds `${LIBRARY_RAW_DIR}:/raw:ro` to the service and sets `LIBRARY_RAW_DIR` default in `.env.example` (not committed with values).

- [ ] **Step 2: Write the smoke test script**

`tests/test_smoke.sh`: `docker compose up -d --build`, wait up to 30 s for `curl -fs localhost:8765/health`, then `curl -fs localhost:8765/ > /dev/null`, then `curl -fs "localhost:8765/?lang=tr" | grep -q Kitaplar`. Exits non-zero on any failure.

- [ ] **Step 3: Run the smoke test and see it pass**

Run: `bash tests/test_smoke.sh`
Expected: exit 0.

- [ ] **Step 4: Run the one-time import in the container**

Run: `LIBRARY_RAW_DIR=/home/ozlem/Documents/python-projects/my_library/data/raw bash scripts/import_books.sh`
Expected: output contains `431 books`, `78 review items`, `410 photos`. Any mismatch fails the command.

- [ ] **Step 5: Verify the import is idempotent**

Run the import script a second time.
Expected: the same counts; no new rows (`docker compose exec library python -c "..."` check of `count_books` equals 431).

- [ ] **Step 6: Update README and commit**

README: how to set `.env`, run `docker compose up -d`, open `http://localhost:8765`, switch language, take a backup, run the import.

```bash
git add docker-compose.yml README.md scripts tests/test_smoke.sh
git commit -m "chore: container run, smoke test and import script"
```

---

## Parallelism (for subagent execution)

- Sequential: Task 1 first.
- Parallel after Task 1: Task 2, Task 4, Task 8.
- Parallel after Task 2: Task 3 (needs Task 2 only).
- After Task 4: Task 5. After Tasks 3 and 5: Task 6. After Task 5: Task 7.
- After Tasks 5 and 8: Task 9. After Tasks 7 and 9: Task 10 and Task 11 (parallel with each other after Task 10's files exist; Task 11 touches only its own routes and templates).
- Task 12 after Task 9. Task 13 last.

## Self-Review

- **Spec coverage:** list/search/filters (T9), detail/edit/add/delete (T10), reading status and loans (T7, T11), history (T5), review queue (T11), backup and CSV (T12), import (T6, T13), Docker and port (T1, T13), English + Turkish (T8, T9), commit-author rule (Global Constraints), repository privacy (T1 `.gitignore`).
- **Review Focus:** 1 → T2, T5, T9; 2 → T9, T10; 3 → T7, T11; 4 → T6; 5 → T10.
- **Type consistency:** `norm` (T2) used in T3, T5. `connect` and `init_schema` (T4) used in T5, T6, T9. `LoanError` (T7) mapped in T11. `Settings` (T1) used in T9, T12.
- **Known risk:** Task 3 depends on the exact rules in `build_excel.py`; the implementer must read it first (Step 1 of Task 3).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-17-library-web-app.md`. Please review the plan. Does it capture what you want?

**Execution method you chose:** parallel Haiku subagents, per task, with the Subagent-driven workflow. Once you confirm the plan, I will start with Task 1, then run Tasks 2, 4, and 8 in parallel.
