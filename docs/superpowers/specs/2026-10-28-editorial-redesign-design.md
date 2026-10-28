# Editorial Redesign — Design

Date: 2026-10-28
Status: Approved by owner (design approved in conversation; spec written for the record)

## 1. Purpose

The app's current visual language (book-cover tiles, warm accent, serif headings) is the
right direction but reads as unfinished: most sections wrap themselves in identical
bordered boxes, every button is filled accent regardless of importance, and pages do not
share a single typographic or spacing rhythm. This redesign keeps the warm "bookshop"
identity but gives it an editorial structure: typography and whitespace carry hierarchy
instead of boxes, and one small component catalogue is reused on every page.

No framework, library, or data-model change. Tailwind v4 (compiled `app.css`), Jinja2
templates, and HTMX stay exactly as they are; only design tokens and template markup
change.

## 2. Color and typography tokens

Keep the existing palette (it already fits "editorial/bookshop"): `--bg #f7f4ee`,
`--surface #fffdf9`, `--ink #1f1b16`, `--muted #6b645a`, `--line #e4ddd2`,
`--accent #8a3b1f` (light) / `#d9825b` (dark), plus the existing `--danger`/`--warn` pair
and the dark-mode equivalents already defined in `tailwind.input.css`. No new base colors.

Add one token: `--accent-soft` (a very light tint of `--accent`, light `#f1e3da` / dark
`#3a2a22`) for badge backgrounds, so accent is never used at full strength except on
primary buttons and active/selected states.

**Type scale** (new `@layer base` rules, replacing the current ad hoc `h1`/`h2` sizes):

| Role | Font | Size | Weight | Color | Used for |
|---|---|---|---|---|---|
| `h1` / `.title` | serif | 2rem (was 1.75rem) | 600 | ink | Page title, book title |
| `.eyebrow` | sans | 0.75rem, uppercase, tracking .08em | 600 | muted | Section labels ("LOAN HISTORY", "TYPES") replacing current `h2` |
| body | sans | 1rem | 400 | ink | Paragraphs, list items |
| `.meta` | sans | 0.875rem | 400 | muted | Dates, publisher, counts, secondary facts |

`h2` as a filled heading is retired from section headers; `.eyebrow` (small caps label)
takes over everywhere a section needs a title that is not the page's `h1`.

## 3. Boxed vs. unboxed sections

Two reusable patterns, used consistently everywhere instead of one generic bordered card:

- **`.panel`** — for interactive areas only: forms, the filter sidebar, the cover
  dropzone, button groups that need a visual container. Keeps the current look
  (`rounded-xl border border-line bg-surface p-4`).
- **`.section`** — for informational content (metadata, lists, history): no border, no
  background, no rounded box. Separated from the section above it by a `border-top` rule
  and `padding-top`, headed by an `.eyebrow` label. This is the new default; most of the
  current `rounded-xl border ... bg-surface` wrappers around read-only content convert to
  this.

Rule of thumb carried into every page: if the user can type, click a control inside it,
or drop a file into it, it is a `.panel`. If it only displays information, it is a
`.section`.

## 4. Component catalogue

One definition each, reused everywhere (replacing the current situation where most
buttons default to the same filled style regardless of importance):

- **`.btn-primary`** — filled accent background, light text. Reserved for the one
  confirming action per view (Save, Add, Upload, Lend). Replaces today's default
  `button` style.
- **`.btn-secondary`** — transparent background, `border-line`, `ink` text. Everything
  else: Stop, Refresh, Cancel, Delete (delete additionally uses `--danger` for its text
  color, not a filled danger button).
- **`.badge`** — small pill, `--accent-soft` background, `--accent` text, used for
  reading status, shelf name, and type chips (replacing the current mix of ad hoc pill
  classes).
- **Empty state** — a single `.meta` line ("No loans yet.", "No changes recorded."), no
  icon, no box.
- **Page header** — `h1` + optional `.meta` count line underneath (e.g. "431 results"),
  used identically on every list/management page.

## 5. Per-page application

- **List (`list.html`, `_book_card.html`, `_results.html`)**: filter sidebar stays a
  `.panel`. Card spacing increases; card internals simplify (title, author, one `.badge`
  row for status/shelf/type, nothing boxed inside the card itself).
- **Detail (`detail.html`)**: right column becomes one continuous flow — title/author/
  meta, status control, a single `.badge` row for shelf + types (no separate "Types" box),
  "Suggest similar books" as plain content (no panel), then a `.section` for loan history
  and a `.section` for the change-history opener, both unboxed, separated by rule lines.
  Left column (cover + quick actions) stays visually distinct since it is the one true
  sidebar.
- **Add / Edit (`add.html`, `edit.html`)**: the form itself stays one `.panel` (it is
  interactive); internal field spacing and label style follow the new type scale.
- **Shelves / Types / Loans / Review / Reading / Settings**: convert their current boxed
  "card list" look to `.section` groups with `.eyebrow` headers; action buttons follow
  the primary/secondary rule.
- **Base layout / nav / floating assistant**: nav link style and the assistant bubble get
  the same type scale and button rules; no structural change to the assistant's own
  panel (it is interactive, stays a `.panel`-equivalent).

## 6. Testing and rollout

- Build order: tokens + component CSS first, then `base.html`, then page by page in this
  order: List → Detail → Add/Edit → Shelves/Types → Loans/Review → Reading/Settings.
- Existing 494 tests keep passing; where a test asserts a specific Tailwind class that
  this redesign removes (e.g. a `rounded-xl border` wrapper that becomes a `.section`),
  update the assertion to match the new markup — behavior (what a route accepts, returns,
  writes) does not change.
- After each page group, rebuild the container and check it in a real browser
  (screenshot via headless Chrome) before moving to the next group.
