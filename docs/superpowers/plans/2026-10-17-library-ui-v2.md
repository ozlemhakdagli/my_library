# Library UI v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Restyle the library with HTMX + Tailwind, add shelves (one per book) and types (many per book), show reading status with quick buttons and dates, and migrate the existing database without data loss.

**Architecture:** Same FastAPI + Jinja2 app. HTMX and the compiled Tailwind CSS are static files. `db.py` gains shelf/type tables and functions; a separate `migrate.py` upgrades old databases in place.

**Tech Stack:** Python 3.12 (container) / 3.14 (host venv), FastAPI, Jinja2, HTMX (vendored), Tailwind standalone CLI (downloaded once into `tools/`, gitignored).

**Spec:** `docs/superpowers/specs/2026-10-17-library-ui-v2-design.md`

## Global Constraints

- Every visible string goes through `i18n.translate`; EN and TR dictionaries have identical key sets.
- No CDN or external script at runtime. HTMX and `static/app.css` are committed files.
- Migration never deletes, moves, or renames a book. Existing counts (431 books, 78 review items, 410 photos) must hold after migration.
- Every change to a field, shelf, or type writes `history` rows in the same transaction.
- Commits: author ozlemhakdagli; each commit ends with `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`.
- Test command: `.venv/bin/python -m pytest -q`. Baseline: 192 passing.
- Do not touch `data/`, `build_excel.py`, `PLAN.md`.

## Review Focus

1. A database created by v1 (no shelf table, no `shelf_id`) migrates, and running the migration twice changes nothing.
2. Shelf and type names that differ only by case or Turkish accent are treated as duplicates ("Roman" vs "roman").
3. A status change with an empty date keeps the existing dates.
4. A future date and a finished date earlier than the started date are rejected.
5. A filter with several types matches books having any of them (OR across types, AND with other filters).

---

### Task 1: Schema additions and migration

**Files:** Modify `src/library/db.py` (SCHEMA only); Create `src/library/migrate.py`, `tests/test_migrate.py`.

**Interfaces:** Produces `migrate.upgrade(conn) -> list[str]` returning the names of changes applied (empty when already current). `init_schema` must create the new tables for fresh databases.

- [ ] **Step 1: Failing tests.** Build a v1 database file in `tmp_path` using the v1 DDL (copy the v1 `SCHEMA` text into the test as a constant, before the change), insert 3 books, one photo, one review item. Test: `upgrade` returns non-empty; `shelf`, `type`, `book_type` tables exist; `book` has `shelf_id`; the 3 books and photo/review rows remain; a second `upgrade` returns `[]`. Fresh DB: `init_schema` creates the new tables.
- [ ] **Step 2: Run, see failure.** `.venv/bin/python -m pytest tests/test_migrate.py -q`.
- [ ] **Step 3: Implement.** Add `shelf`, `type`, `book_type` to SCHEMA with `CREATE TABLE IF NOT EXISTS`. `migrate.upgrade` checks `PRAGMA table_info(book)`, runs `ALTER TABLE book ADD COLUMN shelf_id INTEGER REFERENCES shelf(id)` if missing, and creates missing tables. One transaction.
- [ ] **Step 4: Pass.** Run the test file and full suite.
- [ ] **Step 5: Commit** `feat: add shelf and type schema with idempotent migration`.

### Task 2: Shelf and type repository functions

**Files:** Modify `src/library/db.py` (add functions only); Create `tests/test_db_shelves_types.py`.

**Interfaces:** Consumes Task 1 tables and `norm()`. Produces:
- `add_shelf(conn, name) -> int`, `rename_shelf(conn, shelf_id, name) -> None`, `delete_shelf(conn, shelf_id) -> None` (soft), `list_shelves(conn) -> list[dict]` (with `book_count`), `NameTakenError(Exception)`.
- `add_type(conn, name) -> int`, `rename_type`, `delete_type` (soft), `list_types(conn) -> list[dict]` (with `book_count`).
- `set_book_shelf(conn, book_id, shelf_id: int | None) -> None` (writes history; None = no shelf).
- `set_book_types(conn, book_id, type_ids: list[int]) -> None` (replaces the set; writes one history row per added/removed type, field `type`).

- [ ] **Step 1: Failing tests.** Cover: add/list; "Roman" then "roman" raises `NameTakenError`; soft delete hides from `list_shelves` but the book's `shelf_id` stays and history remains; `set_book_shelf` to None; `set_book_types` adds and removes with exact history count; no history when nothing changes.
- [ ] **Step 2: Run, see failure.**
- [ ] **Step 3: Implement** each function in one `with conn:` transaction, validation before writes.
- [ ] **Step 4: Pass.**
- [ ] **Step 5: Commit** `feat: add shelf and type repository functions with history`.

### Task 3: Vendor HTMX and build Tailwind CSS

**Files:** Create `tools/fetch_assets.sh`, `src/library/web/static/htmx.min.js`, `src/library/web/static/app.css`, `src/library/web/static/tailwind.input.css`; Modify `.gitignore` (add `tools/`), `tests/test_assets.py`.

**Interfaces:** `fetch_assets.sh` downloads the Tailwind standalone CLI into `tools/` and the HTMX minified file (pinned version, e.g. 2.0.4) into `static/`. `app.css` is built from `tailwind.input.css` with the CLI, scanning `src/library/web/templates/**/*.html`.

- [ ] **Step 1: Failing test.** `tests/test_assets.py`: `static/htmx.min.js` exists and is non-empty; `static/app.css` exists and contains the class `grid` and `rounded-xl`; no template contains `https://` script or link tags.
- [ ] **Step 2: Run, see failure.**
- [ ] **Step 3: Implement** `fetch_assets.sh` (uses `curl`), run it, build CSS with `tools/tailwindcss -i ... -o ... --minify`. If the sandbox has no network, stop and report the exact failing command; do not vendor by hand-writing files.
- [ ] **Step 4: Pass.**
- [ ] **Step 5: Commit** `chore: vendor htmx and build tailwind css locally`.

### Task 4: Base layout and library page

**Files:** Modify `src/library/web/templates/base.html`, `src/library/web/templates/list.html`, `src/library/web/app.py`, `src/library/i18n.py`; Create `src/library/web/templates/_book_card.html`, `_results.html`; Create `tests/test_web_library_v2.py`.

**Interfaces:** `GET /` renders full page; if request header `HX-Request` is present, returns only `_results.html`. Filters: `q`, `shelf` (id or `none`), `type` (repeatable), `status`, `needs_review`, `page`. Consumes `db.list_books` extended with `shelf_id` and `type_ids` (add optional params in `db.py`; keep existing behavior).

- [ ] **Step 1: Failing tests.** Full page 200 with `<link ... app.css>` and `<script ... htmx.min.js>`; `HX-Request` header returns no `<html>` tag; shelf filter; multi-type filter is OR across types and AND with status (Review Focus 5); 375 px responsive check: template contains `px-4` at root container and no `w-[` fixed widths above 640 px (check via regex).
- [ ] **Step 2: Run, see failure.**
- [ ] **Step 3: Implement** layout (sidebar on wide screens, stacked on phones), cards with status badge, shelf, type chips; `hx-get` on filter controls targeting `#results`.
- [ ] **Step 4: Pass.** Full suite.
- [ ] **Step 5: Commit** `feat: library page with HTMX filters and card layout`.

### Task 5: Reading status quick buttons and date validation

**Files:** Modify `src/library/db.py` (validation helper only), `src/library/web/app.py`, `src/library/web/templates/_status.html` (new), `src/library/i18n.py`; Create `tests/test_web_status.py`.

**Interfaces:** `POST /books/{id}/status/quick` with form field `action` in `{"read","reading","abandon"}`; returns `_status.html` fragment. Sets status and today's date when the date is empty; keeps existing dates. `set_reading_status` rejects future dates and finished-before-started with `ValueError` (new message keys).

- [ ] **Step 1: Failing tests.** "Mark as read" sets `read` and finished date today; a book already having started date keeps it; future date rejected (400, DB unchanged); finished before started rejected; fragment contains the badge text in the selected language.
- [ ] **Step 2: Run, see failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Pass.**
- [ ] **Step 5: Commit** `feat: quick reading status buttons with date rules`.

### Task 6: Book page with shelf, types, and status

**Files:** Modify `src/library/web/app.py`, `src/library/web/templates/detail.html`, `src/library/i18n.py`; Create `tests/test_web_book_v2.py`.

**Interfaces:** `POST /books/{id}/shelf` (form `shelf_id`, empty = none); `POST /books/{id}/types` (form repeated `type_id`); both return to the book page (or an HTMX fragment when `HX-Request`). Consumes Task 2 functions.

- [ ] **Step 1: Failing tests.** Set shelf and read it back on the page; set types replaces the set; history section lists the type and shelf changes; page shows "No shelf" when none; book with no types shows no chip block.
- [ ] **Step 2: Run, see failure.**
- [ ] **Step 3: Implement** shelf `<select>` and type chips with remove buttons plus a type `<select>` to add.
- [ ] **Step 4: Pass.**
- [ ] **Step 5: Commit** `feat: book page shelf and type assignment`.

### Task 7: Shelves and types management pages

**Files:** Modify `src/library/web/app.py`, `src/library/i18n.py`; Create `src/library/web/templates/shelves.html`, `types.html`, `tests/test_web_manage.py`.

**Interfaces:** `GET /shelves`, `POST /shelves` (name), `POST /shelves/{id}/rename`, `POST /shelves/{id}/delete`; same for `/types`. Duplicate name → 409 with message. Consumes Task 2.

- [ ] **Step 1: Failing tests.** Create, duplicate (accent-insensitive) → 409, rename, soft delete hides it from the page, counts shown.
- [ ] **Step 2: Run, see failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Pass.**
- [ ] **Step 5: Commit** `feat: manage shelves and types`.

### Task 8: Reading overview, restyle loans/review/settings

**Files:** Modify `src/library/web/app.py`, `loans.html`, `review.html`, `settings.html`, `base.html` (nav); Create `src/library/web/templates/reading.html`, `tests/test_web_reading.py`.

**Interfaces:** `GET /reading` returns counts per status and count of books finished per year (plain table). Consumes existing `reading_status` data via a new read function `reading_counts(conn) -> dict` and `finished_per_year(conn) -> list[tuple[int,int]]` added to `db.py`.

- [ ] **Step 1: Failing tests.** Counts match a seeded DB; finished-per-year groups by year of `finished_on`; `/loans`, `/review`, `/settings` still return 200 with the new layout class present.
- [ ] **Step 2: Run, see failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Pass.**
- [ ] **Step 5: Commit** `feat: reading overview and restyled secondary pages`.

### Task 9: Full verification, migration of the real volume, container

**Files:** Modify `README.md` (short section on shelves, types, migration, backup before upgrade). Scripts only; no product code.

- [ ] **Step 1: Regression.** `.venv/bin/python -m pytest -v` — all tests pass, count >= 192 + new.
- [ ] **Step 2: Backup before migration.** Run the existing backup function against the running container's DB (via `docker compose exec library python -c ...` calling `backup.make_backup`), and confirm the backup file exists in `/data/backups`.
- [ ] **Step 3: Rebuild and migrate.** `docker compose up -d --build`; then `docker compose exec library python -m library.migrate` (add a `__main__` if missing; it prints the list of applied changes). Re-run to confirm empty output.
- [ ] **Step 4: Data check.** Book count 431, review items 78, photos 410 via the same SQL check as before.
- [ ] **Step 5: Browser check.** `curl -fs localhost:8765/` and `curl -fs localhost:8765/shelves` return 200; `?lang=tr` shows Turkish labels.
- [ ] **Step 6: Commit** `docs: document shelves, types and migration`.

---

## Parallelism

- Task 1 → Task 2 (both touch `db.py`; run sequentially).
- Task 3 runs in parallel with Tasks 1–2 (it touches only static files, `tools/`, `.gitignore`).
- Tasks 4 → 5 → 6 → 7 → 8 are sequential (shared templates and `app.py`).
- Task 9 last.
