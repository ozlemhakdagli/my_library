# Editorial Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the app's boxed, one-filled-button-everywhere look with an editorial
design: typography and whitespace carry hierarchy, boxes are reserved for interactive
areas, and one small component catalogue (two buttons, one badge, one section header) is
reused on every page.

**Architecture:** No framework or data-model change. Design tokens and component classes
are added to `src/library/web/static/tailwind.input.css` (compiled to `app.css` with the
existing `tools/tailwindcss` CLI); templates are updated page group by page group to use
the new classes in place of ad hoc Tailwind utility chains.

**Tech Stack:** Tailwind v4 (CLI-compiled CSS, no build tool change), Jinja2 templates,
HTMX, pytest + FastAPI `TestClient`.

**Spec:** `docs/superpowers/specs/2026-10-28-editorial-redesign-design.md`

## Global Constraints

- No new runtime dependency, no change to routes, the database, or HTMX wiring — visual
  markup and CSS only.
- Compile CSS after every CSS edit: `tools/tailwindcss -i src/library/web/static/tailwind.input.css -o src/library/web/static/app.css -m`.
- Colors: keep the existing palette; add only `--accent-soft` (light `#f1e3da`, dark
  `#3a2a22`) and its `--color-accent-soft` theme alias.
- Type scale (spec §2): `h1`/`.title` 2rem serif 600 ink; `.eyebrow` 0.75rem uppercase
  letter-spacing .08em weight 600 muted (replaces `h2` as a section heading); body 1rem
  ink; `.meta` 0.875rem muted.
- Box rule (spec §3): `.panel` only for interactive areas (forms, filter sidebar,
  dropzone, button groups); `.section` (no border/background, `border-top` + padding-top
  + `.eyebrow` label) for everything read-only.
- Components (spec §4): `.btn-primary` (filled accent, one per view: Save/Add/Upload/
  Lend), `.btn-secondary` (transparent, `border-line`, `ink` text — everything else,
  including Delete, which also gets `--danger` text color), `.badge` (`--accent-soft`
  background, `--accent` text — status/shelf/type), empty state = one `.meta` line, no
  icon, no box.
- Run `.venv/bin/python -m pytest -q` after every task; it must stay green (494 baseline,
  adjusted per task below).
- After each page-group task, rebuild the container (`docker compose up -d --build`) and
  confirm with a real-browser screenshot (headless Chrome, as used earlier this session)
  before moving to the next task.

## Review Focus

1. Badge text stays readable on `--accent-soft` in **both** light and dark themes (new
   color pairing, not yet contrast-checked) — Task 1.
2. A page/section with zero items (no shelves, no types, no loans) renders the one-line
   `.meta` empty state and does not silently disappear once its box is removed — Tasks
   3, 4, 6, 7.
3. A very long book title under the new 2rem `h1` does not overflow the detail page's
   right column — Task 4.
4. Existing tests that assert a specific Tailwind utility string (e.g. `"rounded-xl
   border"` via regex) must be updated to the new class names, not left silently
   matching the wrong thing — every template task below.
5. HTMX partial responses (`_results.html`, `_status.html`, `_shelf.html`, `_types.html`)
   must carry the new classes too, since they are returned standalone on `HX-Request` —
   Tasks 3 and 4.

---

## File Structure

```
src/library/web/static/tailwind.input.css   design tokens + component classes (modified)
src/library/web/static/app.css              compiled output (rebuilt every task, not hand-edited)
src/library/web/templates/base.html         nav link style (modified)
src/library/web/templates/list.html         page header, filter panel (modified)
src/library/web/templates/_book_card.html   card badges (modified)
src/library/web/templates/_results.html     HTMX fragment wrapper (modified)
src/library/web/templates/detail.html       right-column flow, loan/history sections (modified)
src/library/web/templates/_cover.html       cover tile (modified: title overflow)
src/library/web/templates/_status.html      status control fragment (modified)
src/library/web/templates/_shelf.html       shelf badge/select fragment (modified)
src/library/web/templates/_types.html       type badges/picker fragment (modified)
src/library/web/templates/_cover_dropzone.html  dropzone panel (modified)
src/library/web/templates/add.html          form field/label style (modified)
src/library/web/templates/edit.html         form field/label style (modified)
src/library/web/templates/shelves.html      section list (modified)
src/library/web/templates/types.html        section list (modified)
src/library/web/templates/loans.html        section list (modified)
src/library/web/templates/review.html       section list (modified)
src/library/web/templates/reading.html      section list (modified)
src/library/web/templates/settings.html     section list (modified)
tests/test_*.py                             assertions updated where they check class strings
```

---

### Task 1: Design tokens, component CSS, and nav

**Files:**
- Modify: `src/library/web/static/tailwind.input.css`
- Modify: `src/library/web/templates/base.html`
- Test: `tests/test_design_tokens.py` (new)

**Interfaces:**
- Produces (CSS class names other tasks rely on): `.panel`, `.section`, `.eyebrow`,
  `.title`, `.meta`, `.btn-primary`, `.btn-secondary`, `.badge`.
- Produces (CSS variables): `--accent-soft`, theme alias `--color-accent-soft`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_design_tokens.py
from pathlib import Path

CSS = Path("src/library/web/static/app.css").read_text()

def test_component_classes_are_compiled():
    for name in (".panel", ".section", ".eyebrow", ".title", ".meta",
                 ".btn-primary", ".btn-secondary", ".badge"):
        assert name in CSS, f"{name} missing from compiled app.css"

def test_accent_soft_token_is_compiled():
    assert "--color-accent-soft" in CSS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_design_tokens.py -v`
Expected: FAIL (classes/token not yet defined).

- [ ] **Step 3: Add tokens and component classes to `tailwind.input.css`**

Add `--accent-soft` to both the light `:root` block and the two dark blocks
(`@media (prefers-color-scheme: dark) :root:not(.light)` and `:root.dark`), using the
light/dark values from Global Constraints. Add `--color-accent-soft: var(--accent-soft);`
next to the existing `--color-accent` line in the `@theme inline` block.

Add these rules (plain CSS, outside `@layer`, so they win over `@layer base` defaults by
cascade order — follow the existing pattern used by `.cover-dropzone`/`.history-dialog`
near the end of the file):

```css
.title, h1 { font-family: ui-serif, Georgia, serif; font-size: 2rem; font-weight: 600; line-height: 1.15; color: var(--ink); }
.eyebrow { font-size: .75rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 600; color: var(--muted); }
.meta { font-size: .875rem; color: var(--muted); }
.panel { border-radius: .75rem; border: 1px solid var(--line); background: var(--surface); padding: 1rem; }
.section { border-top: 1px solid var(--line); padding-top: 1rem; }
.btn-primary, .btn-secondary { display: inline-flex; align-items: center; gap: .4rem; padding: .5rem 1.25rem; border-radius: .5rem; font: inherit; cursor: pointer; }
.btn-primary { background: var(--accent); color: var(--bg); border: 0; }
.btn-secondary { background: transparent; color: var(--ink); border: 1px solid var(--line); }
.badge { display: inline-flex; align-items: center; padding: .15rem .6rem; border-radius: 999px; font-size: .75rem; background: var(--accent-soft); color: var(--accent); }
```

Remove the now-superseded `h1`/`h2` rules in the existing `@layer base` block (keep `h2`
only if any template still relies on it as a generic heading outside a `.section`; check
with `grep -rn "<h2" src/library/web/templates/` and leave `h2` styled only if uses
remain after this plan's tasks — otherwise delete it). Do not touch the existing
`button` element rule in `@layer base` yet; it stays as a harmless fallback and is
superseded in-place wherever a template gains `.btn-primary`/`.btn-secondary` in later
tasks.

- [ ] **Step 4: Rebuild CSS**

Run: `tools/tailwindcss -i src/library/web/static/tailwind.input.css -o src/library/web/static/app.css -m`

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_design_tokens.py -v`
Expected: PASS

- [ ] **Step 6: Update nav link style in `base.html`**

The nav links (`<a href="/" class="text-muted hover:text-ink">...`) already use
`text-muted`/`hover:text-ink`; leave the Tailwind utilities as-is (they already match the
new `.meta`-level color intent for secondary nav) — no markup change needed here. Confirm
by reading the current nav block; if it already matches, skip to Step 7 with no edit.

- [ ] **Step 7: Run full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 496 passed (494 baseline + 2 new in this task).

- [ ] **Step 8: Commit**

```bash
git add src/library/web/static/tailwind.input.css src/library/web/static/app.css tests/test_design_tokens.py
git commit -m "feat: add editorial design tokens and component classes"
```

---

### Task 2: List page (home)

**Files:**
- Modify: `src/library/web/templates/list.html`, `_book_card.html`, `_results.html`
- Test: `tests/test_web_library_v2.py`, `tests/test_cover_cards.py`, `tests/test_list_layout.py`, `tests/test_card_polish.py`, `tests/test_polish2.py` (update existing class-string assertions; do not add new behavior tests — this task is visual)

**Interfaces:**
- Consumes: `.panel`, `.eyebrow`, `.title`, `.meta`, `.btn-primary`, `.btn-secondary`,
  `.badge` from Task 1.

- [ ] **Step 1: Read current markup**

Read `list.html`, `_book_card.html`, `_results.html` in full before editing — note every
Tailwind class string that an existing test matches with `in response.text` or `re.search`
(grep: `rg -n "rounded-xl|border-line|bg-surface" tests/test_web_library_v2.py
tests/test_cover_cards.py tests/test_list_layout.py tests/test_card_polish.py
tests/test_polish2.py`), so Step 4 updates exactly those assertions.

- [ ] **Step 2: Update `list.html`**

- Filter sidebar (`<details class="filter-panel ...">`) keeps its box: replace its
  Tailwind utility chain (`rounded-xl border border-line bg-surface ...`) with `panel`
  plus whatever layout-only utilities remain (sticky positioning, width) — the box
  styling itself now comes from `.panel`.
- Page header: `<h1>` becomes `<h1 class="title">` (or relies on the bare `h1` rule from
  Task 1 if no class was present before — check current markup and keep it minimal), with
  the existing results-count line given class `meta` in place of its current text color
  utility.
- "+ Add book" button keeps its filled look via `btn-primary` (it is the one primary
  action on this page); any other button-styled link in this template (e.g. "Clear
  filters") becomes `btn-secondary`.

- [ ] **Step 3: Update `_book_card.html` and `_results.html`**

- Replace the per-card status/shelf/type text rows with `.badge` spans (one badge per
  value: reading status, shelf name if set, each type name) — same data, new visual
  treatment. No change to what data is fetched or passed to the template.
- `_results.html` is the HTMX-fragment wrapper around the card grid; confirm it has no
  boxed wrapper around the whole grid (it should not; the grid itself is unboxed, only
  the filter sidebar and cards' internal badges are styled) — adjust only if it currently
  wraps the grid in a box.

- [ ] **Step 4: Update the five test files' class-string assertions**

For each assertion found in Step 1 that checked an old utility string (e.g.
`"rounded-xl border" in text` for the filter panel), change it to check for `"panel"` (or
the new class actually used) instead. Do not change assertions about data (titles,
authors, counts, HTMX headers) — only ones that assert presence of now-renamed CSS.

- [ ] **Step 5: Rebuild CSS and run tests**

Run: `tools/tailwindcss -i src/library/web/static/tailwind.input.css -o src/library/web/static/app.css -m`
Run: `.venv/bin/python -m pytest -q`
Expected: 496 passed, same count as Task 1 (no tests added, some assertions changed).

- [ ] **Step 6: Rebuild the container and check in a browser**

Run: `docker compose up -d --build`, wait for `/health` to return 200, then screenshot
`/` at a wide viewport (as done earlier this session with headless Chrome + CDP) in both
light and dark theme. Confirm: filter sidebar is the only boxed element, cards show badge
pills instead of plain text for status/shelf/type, "+ Add book" is the only filled
button on the page.

- [ ] **Step 7: Commit**

```bash
git add src/library/web/templates/list.html src/library/web/templates/_book_card.html src/library/web/templates/_results.html src/library/web/static/app.css tests/test_web_library_v2.py tests/test_cover_cards.py tests/test_list_layout.py tests/test_card_polish.py tests/test_polish2.py
git commit -m "feat: apply editorial design to the list page"
```

---

### Task 3: Book detail page

**Files:**
- Modify: `src/library/web/templates/detail.html`, `_cover.html`, `_status.html`, `_shelf.html`, `_types.html`, `_cover_dropzone.html`
- Test: `tests/test_web_books.py`, `tests/test_web_book_v2.py`, `tests/test_web_status.py`, `tests/test_detail_layout.py`, `tests/test_polish.py`, `tests/test_polish2.py`, `tests/test_cover_web.py` (update class-string assertions)

**Interfaces:**
- Consumes: Task 1 classes; Task 2's `.badge` pattern (shelf/type as badges), reused here.

- [ ] **Step 1: Read current markup**

Read `detail.html` in full, plus the four fragment partials it includes. Grep the seven
listed test files for Tailwind utility strings they assert on (same method as Task 2,
Step 1), so every renamed class has its matching test update identified up front.

- [ ] **Step 2: Rebuild the right column as one flow in `detail.html`**

- Title/author/meta block: `h1`/`title` + `.meta` lines (publisher, loan line) — no box.
- Status control: keep its current interactive widget (it is a control, not read-only);
  if it currently sits in a boxed wrapper, that wrapper may stay a `.panel` since the
  reader clicks inside it, per the box rule (interactive = boxed is allowed, not
  required — the spec's example merges shelf+type display but does not require removing
  every interactive box on this page). Use judgement per element: a plain button row
  needs no box; a form with a select and a save button is a `.panel`.
- Shelf + types: replace the separate "Types" `.panel` box and the shelf line with **one**
  unboxed row of `.badge` spans (shelf badge first if set, then one badge per type).
  Directly below that row, keep the existing edit affordance (shelf `<select>` + Save
  button, type add/remove controls) as a compact `.panel` — same controls, now visually
  secondary to the badge row above it, not in a box titled "Types".
- "Suggest similar books": drop its current `.panel`-style wrapper; render as plain
  content (`.eyebrow` label + `.btn-secondary` trigger button + results list once loaded).
- Loan history and the change-history opener: each becomes a `.section` (eyebrow label +
  `border-top`), replacing their current boxed/`<details>` treatment. The change-history
  dialog itself (`<dialog>`) is unaffected — only the opener row outside it changes from a
  plain button to a `.section`-headed row with a `.btn-secondary`-styled opener.

- [ ] **Step 3: Update `_cover.html` for the new `h1`/`.title` size**

Confirm the title text inside the generated cover tile (for books without a photo) still
uses `[overflow-wrap:anywhere]` (Review Focus 3) and is not affected by the new global
`h1` font-size rule (the cover's own title element should keep its own explicit font-size
utility so it does not inherit the page-level 2rem rule meant for `h1`/`.title` — give it
a class other than `title` if it currently relies on the bare `h1` selector, to avoid an
accidental size change inside the small cover tile).

- [ ] **Step 4: Update `_status.html`, `_shelf.html`, `_types.html`, `_cover_dropzone.html`**

- `_status.html`: segmented control keeps its current interactive styling; its action
  buttons (if any besides the segmented control itself) follow `.btn-primary`/
  `.btn-secondary` per Global Constraints.
- `_shelf.html`, `_types.html`: these HTMX fragments must render the same badge-row +
  compact-panel structure from Step 2 (they are swapped in standalone on `HX-Request`, so
  they need their own copy of the new markup, not just the full-page version).
- `_cover_dropzone.html`: already a `.panel`-equivalent (dashed box); replace its ad hoc
  border/background utilities with `panel` plus the dashed-border/drag-state utilities
  that must stay (drag-over highlight etc. are not part of `.panel` and stay as-is).

- [ ] **Step 5: Update the seven test files' class-string assertions**

Same method as Task 2 Step 4: only CSS-string assertions change; behavior assertions
(HTMX status codes, redirect targets, form data, history entries, cover upload
acceptance) do not change.

- [ ] **Step 6: Rebuild CSS and run tests**

Run: `tools/tailwindcss -i ... -m` then `.venv/bin/python -m pytest -q`
Expected: 496 passed.

- [ ] **Step 7: Rebuild the container and check in a browser**

Screenshot a book's detail page (one with a shelf and types set, one without) in light
and dark theme. Confirm: shelf+type badges appear as one row with no "Types" box, loan
history and change-history are unboxed `.section`s, a long title does not overflow.

- [ ] **Step 8: Commit**

```bash
git add src/library/web/templates/detail.html src/library/web/templates/_cover.html src/library/web/templates/_status.html src/library/web/templates/_shelf.html src/library/web/templates/_types.html src/library/web/templates/_cover_dropzone.html src/library/web/static/app.css tests/test_web_books.py tests/test_web_book_v2.py tests/test_web_status.py tests/test_detail_layout.py tests/test_polish.py tests/test_polish2.py tests/test_cover_web.py
git commit -m "feat: apply editorial design to the book detail page"
```

---

### Task 4: Add / Edit forms

**Files:**
- Modify: `src/library/web/templates/add.html`, `edit.html`
- Test: `tests/test_web_books.py` (update class-string assertions only)

**Interfaces:**
- Consumes: Task 1 classes (`.panel`, `.meta`, `.btn-primary`, `.btn-secondary`).

- [ ] **Step 1: Read current markup and grep `test_web_books.py` for utility-string assertions on add/edit pages**

- [ ] **Step 2: Update `add.html` and `edit.html`**

The form itself keeps its `.panel` box (interactive). Replace its current
`rounded-xl border border-line bg-surface p-4` utility chain with `panel`. Field labels
and help text use `.meta` for secondary copy (e.g. "Optional. JPEG, PNG or WEBP..."). The
submit button (Add / Save) is `.btn-primary`; any secondary action (e.g. "Fill from
photo") is `.btn-secondary`.

- [ ] **Step 3: Update class-string assertions in `test_web_books.py`**

- [ ] **Step 4: Rebuild CSS and run tests**

Run: `tools/tailwindcss -i ... -m` then `.venv/bin/python -m pytest -q`
Expected: 496 passed.

- [ ] **Step 5: Rebuild the container and check in a browser**

Screenshot `/books/new` and an edit page in light and dark theme.

- [ ] **Step 6: Commit**

```bash
git add src/library/web/templates/add.html src/library/web/templates/edit.html src/library/web/static/app.css tests/test_web_books.py
git commit -m "feat: apply editorial design to add and edit forms"
```

---

### Task 5: Shelves and types management pages

**Files:**
- Modify: `src/library/web/templates/shelves.html`, `types.html`
- Test: `tests/test_web_manage.py` (update class-string assertions)

**Interfaces:**
- Consumes: Task 1 classes.

- [ ] **Step 1: Read current markup and grep `test_web_manage.py` for utility-string assertions**

- [ ] **Step 2: Update `shelves.html` and `types.html`**

Convert the current boxed list of shelves/types into one `.section` (eyebrow label "Add
a shelf"/"Add a type" over the create form, which stays a `.panel` since it is
interactive) followed by a plain list where each row is name + `.meta` book-count +
`.btn-secondary` rename/delete actions — no per-row box. Empty list renders the
single-line `.meta` empty state (Review Focus 2).

- [ ] **Step 3: Update class-string assertions in `test_web_manage.py`**

- [ ] **Step 4: Rebuild CSS and run tests**

Run: `tools/tailwindcss -i ... -m` then `.venv/bin/python -m pytest -q`
Expected: 496 passed.

- [ ] **Step 5: Rebuild the container and check in a browser**

Screenshot `/shelves` and `/types`, including a check with zero shelves/types if the
current seed data allows it (or temporarily confirm via `sqlite3` that the empty state
renders, then restore).

- [ ] **Step 6: Commit**

```bash
git add src/library/web/templates/shelves.html src/library/web/templates/types.html src/library/web/static/app.css tests/test_web_manage.py
git commit -m "feat: apply editorial design to shelves and types pages"
```

---

### Task 6: Loans and review pages

**Files:**
- Modify: `src/library/web/templates/loans.html`, `review.html`
- Test: `tests/test_web_loans_review.py` (update class-string assertions)

**Interfaces:**
- Consumes: Task 1 classes.

- [ ] **Step 1: Read current markup and grep `test_web_loans_review.py` for utility-string assertions**

- [ ] **Step 2: Update `loans.html` and `review.html`**

Same conversion as Task 5: lend/resolve forms stay `.panel` (interactive); the list of
open loans / review items becomes an unboxed list under an `.eyebrow` label, each row
using `.meta` for secondary facts (lent-on date, confidence reason) and `.btn-secondary`
for row actions (Return, Confirm, Not a book). Empty state is the one-line `.meta`
message (Review Focus 2).

- [ ] **Step 3: Update class-string assertions in `test_web_loans_review.py`**

- [ ] **Step 4: Rebuild CSS and run tests**

Run: `tools/tailwindcss -i ... -m` then `.venv/bin/python -m pytest -q`
Expected: 496 passed.

- [ ] **Step 5: Rebuild the container and check in a browser**

Screenshot `/loans` and `/review`.

- [ ] **Step 6: Commit**

```bash
git add src/library/web/templates/loans.html src/library/web/templates/review.html src/library/web/static/app.css tests/test_web_loans_review.py
git commit -m "feat: apply editorial design to loans and review pages"
```

---

### Task 7: Reading and settings pages

**Files:**
- Modify: `src/library/web/templates/reading.html`, `settings.html`
- Test: `tests/test_web_reading.py`, `tests/test_backup_export.py` (update class-string assertions)

**Interfaces:**
- Consumes: Task 1 classes.

- [ ] **Step 1: Read current markup and grep both test files for utility-string assertions**

- [ ] **Step 2: Update `reading.html` and `settings.html`**

`reading.html`: status-count table and finished-per-year table become plain `.section`s
with `.eyebrow` labels (no surrounding box) — tabular data itself is unaffected.
`settings.html`: theme/language switch, backup button, and CSV export link are grouped
under `.eyebrow` labels; the backup/export actions are `.btn-secondary` (not primary —
they are not the page's main confirming action), each in its own `.section` rather than
a shared box.

- [ ] **Step 3: Update class-string assertions in both test files**

- [ ] **Step 4: Rebuild CSS and run tests**

Run: `tools/tailwindcss -i ... -m` then `.venv/bin/python -m pytest -q`
Expected: 496 passed.

- [ ] **Step 5: Rebuild the container and check in a browser**

Screenshot `/reading` and `/settings` in both languages (EN/TR) to confirm `.eyebrow`
labels translate correctly (they reuse existing `t(...)` strings — no new translation
keys are needed since no new labels are introduced, only re-styled).

- [ ] **Step 6: Commit**

```bash
git add src/library/web/templates/reading.html src/library/web/templates/settings.html src/library/web/static/app.css tests/test_web_reading.py tests/test_backup_export.py
git commit -m "feat: apply editorial design to reading and settings pages"
```

---

### Task 8: Final regression pass

**Files:** none changed unless a defect is found; this task verifies Tasks 1–7.

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 496 passed, 0 failed.

- [ ] **Step 2: Rebuild the container**

Run: `docker compose up -d --build`; wait for `/health` to return 200.

- [ ] **Step 3: Screenshot every page in light theme**

`/`, a book detail page, `/books/new`, an edit page, `/shelves`, `/types`, `/loans`,
`/review`, `/reading`, `/settings` — confirm each uses the shared button/badge/section
vocabulary and no stray boxed-card wrapper remains around read-only content.

- [ ] **Step 4: Screenshot the same pages in dark theme**

Confirm `--accent-soft` badge text stays readable (Review Focus 1) and no element is
invisible or low-contrast.

- [ ] **Step 5: Check the floating assistant panel still opens correctly**

Open the assistant on any page, confirm its panel (already a `.panel`-equivalent,
unchanged by this plan per spec §5) and its buttons still render correctly next to the
redesigned page behind it.

- [ ] **Step 6: Report findings to the owner**

List any visual defect found in Steps 3–5, with the page and a one-line description; fix
with a new commit per defect and rerun the affected screenshot before closing this task.

---

## Self-Review

- **Spec coverage:** §2 tokens/type scale → Task 1. §3 panel/section rule → Task 1
  (classes) + every page task (application). §4 component catalogue → Task 1 (classes) +
  every page task. §5 per-page application → Tasks 2–7 map one-to-one to its bullet
  list. §6 build order and testing → task ordering (tokens → list → detail → add/edit →
  shelves/types → loans/review → reading/settings) and the rebuild-and-screenshot step
  in every task, plus Task 8 as the final full-app pass.
- **Review Focus coverage:** 1 → Task 8 Step 4 (and Task 1 defines the token). 2 → Tasks
  2, 3, 5, 6 (empty-state call-outs). 3 → Task 3 Steps 2–3. 4 → every page task's "update
  class-string assertions" step. 5 → Task 2 Step 3 and Task 3 Step 4 explicitly call out
  the HTMX fragment partials.
- **Type/class consistency:** `.panel`, `.section`, `.eyebrow`, `.title`, `.meta`,
  `.btn-primary`, `.btn-secondary`, `.badge` are defined once in Task 1 and only ever
  consumed (never redefined) in Tasks 2–7.
- **Proportion:** eight tasks for a visual-only change across ~20 templates is
  proportionate — each task is one page group, matching the spec's own build order,
  with no task re-deriving code the spec already fixed (exact CSS values are given once
  in Task 1; later tasks reference class names, not new values).
