# Add Book with Cover Photo and OCR Suggestions

Date: 2026-10-18
Status: Approved by owner ("1,2, yap")

## 1. Scope

- Add a book by hand (existing form) and optionally upload a cover photo.
- The uploaded cover is resized and stored outside the repository, in the data volume.
- The app extracts the dominant color of the photo and uses it for the book tile when there is no shelf color.
- The book tile shows the real cover image when one exists.
- From a cover photo, the app reads text with Tesseract (Turkish + English) and suggests title and author. The user confirms or edits before saving. Nothing is saved automatically from OCR.

Out of scope: AI-generated covers, LLM-based recognition (later project), external book APIs.

## 2. Data

- `book.cover_file TEXT NULL`: file name only, e.g. `12.jpg`. Stored under `LIBRARY_COVER_DIR` (default `/data/covers`).
- `book.cover_color TEXT NULL`: hex color, e.g. `#4a3f6b`.
- Migration adds both columns (idempotent, like the v2 migration).

## 3. Rules

- Accepted types: JPEG, PNG, WEBP. Maximum upload size 10 MB. Other types → 400.
- Stored image: longest side 600 px, JPEG quality 85.
- File name is always `<book_id>.jpg`; the client file name is never used on disk (no path traversal).
- Dominant color: image downscaled to 64 px, quantized to 5 colors, the most frequent non-near-white, non-near-black color is taken; fallback `#4a3f6b`.
- OCR: `tesseract <image> stdout -l tur+eng --psm 6`. Title suggestion = first line with at least 3 letters that is not all digits; author suggestion = a line of 2–4 words with capitalized words that is not the title. Suggestions are only pre-filled text.
- If Tesseract is not installed, the OCR step returns an empty suggestion and the form still works.
- Deleting a book keeps the cover file (soft delete), consistent with the rest of the data.

## 4. Routes

- `POST /books/new` accepts an optional `cover` file.
- `POST /books/{id}/cover` replaces the cover.
- `GET /covers/{id}` serves the stored JPEG (404 if none).
- `POST /books/ocr` accepts `cover` and returns the add form fragment with suggestions pre-filled.

## 5. Testing

- Migration on an old-schema DB adds columns and keeps rows.
- Save: file stored as `<id>.jpg`, color is a valid hex, size ≤ 600 px.
- Invalid type → 400, nothing stored.
- Dominant color deterministic for a solid-color test image.
- OCR suggestion logic with fixed text input; subprocess call mocked when tesseract is missing.
- Tile shows `<img>` when cover exists, generated tile otherwise.
