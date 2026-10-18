# Library Visual Design (v3)

Date: 2026-10-18
Status: Draft, awaiting owner approval
Scope: visual layer only. Data, routes, and behavior stay as in UI v2. Every new label goes through `i18n.translate`.

## 1. Direction

The library should feel like a bookshelf, not a form. Each book is shown as a book: a tall cover-shaped tile with a spine edge, a title set in a serif face, and a clear reading state. The interface itself is calm and modern, with generous spacing and few colors.

## 2. Theme

- Three choices in the nav: light, dark, system. Default: system.
- Stored in cookie `theme` (`light` | `dark` | `system`). Invalid values fall back to `system`.
- Implemented with CSS variables for surface, ink, muted ink, line, and accent. Tailwind uses them through `theme.extend.colors`. `dark` class on `<html>` switches the variables.
- Light: paper background `#f7f4ee`, ink `#1f1b16`, muted `#6b645a`, line `#e4ddd2`, accent `#8a3b1f`.
- Dark: background `#15130f`, surface `#1d1a16`, ink `#f2ede4`, muted `#a39a8c`, line `#2e2a24`, accent `#d9825b`.

## 3. Book tile (the core element)

- Aspect ratio 2:3, rounded corners on the right side only (the cover), a thin darker strip on the left (the spine), and a soft shadow.
- Cover color: taken from the shelf (klasör) if set, otherwise a stable color from a hash of the book title. A fixed palette of 8 muted tones so covers stay readable in both themes.
- Title on the cover in a serif face (`ui-serif, Georgia, serif`), large, clamped to 4 lines. Author in small caps under it.
- Publisher in small text at the bottom of the cover.
- Reading state: a ribbon across the top-right corner. Read: "Read" with finished date. Reading: "Reading". Not read: no ribbon. Abandoned: "Dropped".
- Types: up to 2 small chips below the tile, with "+N" when more.
- Photos are not shown (not available on this machine); the generated cover is the visual.

## 4. Layout

- Grid: 2 columns on phones, 3 to 5 on wider screens.
- Top bar: search field and theme switch; the filter panel is a drawer on phones and a left column on wide screens.
- Quick actions are not on the tiles. The tile links to the book page; status changes happen there (and through a small "read" icon on hover for desktop only).
- No horizontal scroll. Phone side margin 16 px.

## 5. Book page

- Left: large cover tile (same as the list, bigger). Right: title, subtitle, authors, publisher, shelf, types.
- Reading state as a segmented control: Not read / Reading / Read / Dropped, with date fields that appear when relevant.
- History and loans as calm lists with dividers, no heavy boxes.

## 6. Typography and spacing

- UI text: system sans. Titles and the app name: system serif.
- Base size 16 px; headings 28, 20, 16 px. Line height 1.5 for body, 1.2 for titles.
- Spacing scale: 4, 8, 12, 16, 24, 32 px.
- Buttons: one primary style (accent background), one secondary (outline). No button larger than the text needs.

## 7. Accessibility

- Contrast at least 4.5:1 for body text in both themes.
- Focus rings visible in both themes.
- Covers have `alt` text with the title and author.

## 8. Testing

- Theme: cookie value applied to `<html>` class; invalid value falls back to `system`.
- Tile: renders title, author, state ribbon for each status; color is deterministic for the same title.
- Layout: page contains the grid class with 2-column base and wider breakpoints; no fixed widths above 640 px in the list container.
- Both languages render all new labels.
- Visual check in a browser at 375 px and 1280 px in both themes before the work is marked done.

## 9. Open items

- Whether the list should also offer a compact table view. Not in this scope unless requested.
