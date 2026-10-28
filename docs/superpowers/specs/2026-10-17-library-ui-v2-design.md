# Personal Library — UI v2 Design (Shelves, Types, Reading Status)

Date: 2026-10-17
Status: Draft, awaiting owner approval
Builds on: `docs/superpowers/specs/2026-10-17-kutuphane-arayuz-design.md` (v1). Everything in v1 that is not changed here stays as it is.

## 1. Purpose

Make the library screens current and easier to use, and add two ways to organize books:

- **Shelf** (klasör): where a book physically or logically lives. One shelf per book.
- **Type** (tür): what a book is about. A book can have several types.

Reading status (not read, reading, read, abandoned) becomes visible and quick to change, with start and finish dates.

Future use: a local LLM (LM Studio) will read shelves, types, and reading status to answer questions and suggest books. This version prepares that data but does not call any model.

## 2. Decisions

| Topic | Decision |
|---|---|
| Stack | FastAPI + Jinja2 templates (unchanged) + HTMX for partial page updates + Tailwind CSS compiled to a static file |
| JavaScript | HTMX is served from `static/`, not a CDN, so the app works offline |
| Build tooling | Tailwind standalone CLI (single binary, no Node). Output committed as `static/app.css` |
| Shelf | one per book, optional (`book.shelf_id`, may be NULL = "No shelf") |
| Type | many per book (`book_type` junction table), a type can be attached to many books |
| Reading status | unchanged data model; UI adds quick buttons, date fields, and status filter |
| Languages | EN and TR, as in v1; every new label goes through `i18n.translate` |

## 3. Data model changes

New tables:

- **shelf:** id, name, norm_name, created_at, deleted_at
- **type:** id, name, norm_name, created_at, deleted_at
- **book_type:** book_id, type_id (primary key on both)

Changed table:

- **book:** add `shelf_id INTEGER NULL REFERENCES shelf(id)`

Rules:

- Shelf names are unique among non-deleted shelves (compared by `norm_name`).
- Type names are unique among non-deleted types (compared by `norm_name`).
- Deleting a shelf or type is soft (`deleted_at`). Books that pointed to it keep history; the shelf or type is hidden from pickers and shown as "deleted" in history.
- Every change to `shelf_id` or to a book's types writes `history` rows, as other fields already do.

## 4. Migration (required)

A database already exists in the Docker volume with 431 books, 78 review items, and 410 photos. Migration must:

1. Add the new tables and the `book.shelf_id` column with `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN` (guarded by a column check).
2. Keep all existing rows unchanged. No book is moved, deleted, or renamed.
3. Be idempotent: running it twice changes nothing.
4. Be tested against a copy of an old-schema database file, not only against an empty database.

Before migration runs on the real volume, the backup function creates a copy of the database file.

## 5. Screens

1. **Library (home):** card or table view of books. Each card shows title, author, shelf, types, and a status badge (read / reading / unread / abandoned, with a finished date when read). Left side: filters for shelf, type, status, and "needs review". Search box at the top. HTMX updates only the results area when a filter or search changes.
2. **Book page:** all fields; shelf selector; type chips with add/remove; reading status with quick buttons ("Mark as read", "Start reading", "Abandon") and date inputs for start and finish. Changing a status with no date entered keeps existing dates (v1 fix).
3. **Shelves page:** list shelves with book counts; create, rename, delete (soft).
4. **Types page:** list types with book counts; create, rename, delete (soft).
5. **Reading overview:** counts by status and by year finished. No charts library; plain numbers and a small table.
6. **Loans, review queue, settings:** as in v1, restyled in the same layout.

Layout rules: 16 px side margin on phones, no horizontal page scroll, one column below 640 px.

## 6. Behavior

- Quick status buttons send a small HTMX request and swap only the status badge.
- "Mark as read" sets status `read` and sets finished date to today if empty.
- "Start reading" sets status `reading` and started date to today if empty.
- Dates in the future are rejected with a message; finished date before started date is rejected.
- A book with no shelf shows "No shelf" (translated). A book with no types shows nothing.
- Filters combine with AND. Multiple types in one filter are OR across types (a book matching any selected type is shown).

## 7. Testing

- **Migration:** a copy of a v1-schema database file (built in the test with v1 DDL) migrates; book count, review count, and photo count are unchanged; running migration twice is a no-op.
- **Repository:** shelf and type create, rename, soft delete; duplicate names rejected (accent-insensitive: "Roman" vs "roman"); book_type add and remove writes history.
- **Web:** library page renders with filters; HTMX partial returns only the results fragment; quick status button changes status and keeps dates; future date rejected; both languages render.
- **Regression:** all 192 existing tests still pass; the real-data import still gives 431 / 78 / 410.
- **Responsive check:** page renders at 375 px width with no horizontal overflow (checked with a test that inspects the Tailwind classes used, plus a manual check in the browser).

## 8. Out of scope (later)

- LLM questions and recommendations (LM Studio)
- New-release tracking
- Ratings, notes beyond the existing note field, covers
- Phone access and APK

## 9. Open items for owner

- Tailwind: standalone CLI binary is downloaded once into `tools/` (not committed). Confirm this is fine.
- Shelf for books without one: default "No shelf" (no automatic shelf). Confirm.
