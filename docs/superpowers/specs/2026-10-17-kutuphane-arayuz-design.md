# Personal Library Web App — First Release (UI) Design

Date: 2026-10-17
Status: Approved by the owner (2026-10-17). Storage location: Docker volume (default).

## 1. Purpose

A single-user personal book library web app. Books are added and edited through the app's own forms. Excel is not used. The app runs on the owner's computer in Docker, and the data never leaves that computer.

Language: the code, docs, and commit messages are in English. The UI is available in **Turkish and English**, switchable by the user.

**Success criterion:** The current 431 books are imported; adding, searching, loan tracking, and reading status work reliably in daily use; a backup can be taken.

## 2. Scope

**In this release:**
- Book list with accent-insensitive search (Yapay Zekâ = yapay zeka, Turkish letters included)
- Filters: reading status, loan status, publisher, author, "needs review"
- Book detail and edit (title, subtitle, authors, publisher, note)
- Add a book; delete a book (confirmed; a soft delete that stays visible in history)
- Reading status: not read, reading, read, abandoned
- Loan tracking: to whom, when, return date
- Change history: every edit stores old and new values
- Review queue: the 78 records kept out of the main list; each is confirmed, corrected, or marked "not a book"
- Backup (copy of the database file) and CSV export
- One-time import of the existing data
- Turkish/English UI language switch

**Not in this release (later projects):**
- LLM integration (LM Studio) — phase 2
- New-release tracking
- Phone access and an APK
- Cover images, ISBN lookup, tags, ratings

## 3. Architecture

- **Language and framework:** Python, FastAPI. Pages are server-rendered HTML from Jinja2 templates; there is no separate frontend build. Forms are validated with Pydantic.
- **Database:** SQLite, a single file.
- **Container:** one Docker image. The app runs in the container; the database file lives in a Docker volume, which survives rebuilding the container.
- **Access:** `http://localhost:8765`. No external access in this release.
- **Configuration:** database path, port, and default language come from environment variables.
- **Language:** UI strings live in a translation module with one dictionary per language. Default language: English. The choice is stored in a cookie and can also be set with `?lang=tr` / `?lang=en`.

**Components:**
- `src/library/norm.py` — text normalization for search and matching (ported from `build_excel.py`)
- `src/library/merge.py` — duplicate-merge and review rules (ported from `build_excel.py`)
- `src/library/db.py` — schema, queries, history recording
- `src/library/importer.py` — import from `data/raw/*.jsonl`
- `src/library/i18n.py` — translations and language selection
- `src/library/web/` — FastAPI routes, Jinja2 templates, static files
- `src/build_excel.py` — existing tool, kept as a reference and for verification

Each component has one job. The web layer talks to the database only through `db.py`.

## 4. Data model

- **book:** id, title, subtitle, norm_title, publisher_id, review_status (ok / needs review), note, created_at, updated_at, deleted_at
- **author:** id, name, norm_name
- **book_author:** book_id, author_id, position (many-to-many)
- **publisher:** id, name, norm_name
- **photo:** id, book_id, file_name, kind (cover / spine), confidence. Only the file name is stored, never an absolute path.
- **reading_status:** book_id, status, started_on, finished_on
- **loan:** id, book_id, borrower, lent_on, returned_on (empty means the book is out)
- **history:** id, record_type, record_id, field, old_value, new_value, changed_at
- **review_item:** book_id, reason (low confidence / author missing / unreadable, etc.)

**Rule:** If an author or publisher is empty, the app does not fill it from memory. The UI shows "unknown".

## 5. Screens

1. **List and search:** search box, filters, pagination
2. **Book detail:** fields, reading status, loan history, change history, photo file names
3. **Edit form:** fields, change summary before saving
4. **Add book form**
5. **Loans:** books currently out, with return dates
6. **Review queue:** 78 items, each with "confirm" / "correct" / "not a book"
7. **Settings and backup:** take a backup, export CSV, switch language

## 6. Import

- Source: `data/raw/*.jsonl` (475 raw records). Excel is not a source.
- Merge and dedup rules are the same as in `build_excel.py`, and their tests carry over.
- The command is idempotent: running it again creates no duplicates.
- Final count check: 431 main books, 78 review items, 410 photos. If the counts do not match, the import fails and writes nothing.
- Source files are never modified.

## 7. Errors and backup

- Each write runs in one database transaction; no half-written records.
- Delete is soft: the book is marked deleted and still appears in history.
- Backup: a timestamped copy of the database file, created from the settings screen.
- If the photo folder is not mounted, the app keeps working and shows only the file name.

## 8. Testing

- **Unit tests:** normalization, merge rules, import idempotence, count check, loan and status transitions, change history. The existing 54 tests are kept.
- **App tests:** FastAPI `TestClient` checks that main pages render, that a save writes to the database, and that both languages render.
- **Smoke test:** after the container starts, `localhost:8765` responds.

## 9. Repository

- Private GitHub repository. Code is committed; commits are authored by the owner only.
- `.gitignore`: `.venv/`, `data/`, `*.db`, `exports/`, `*.xlsx`, `*.csv`, photos. Book data never enters the repository.
- `Dockerfile` and `docker-compose.yml` are in the repository. Data lives in the volume.

## 10. Open items

- Drive backup copies: a later step, not part of this release.

## 11. Next steps

1. Repository setup and skeleton
2. Normalization, merge rules, schema, and import (with tests)
3. Screens, in both languages
4. Smoke test and usage check
5. LLM integration (LM Studio) as a separate project
