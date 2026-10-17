"""Read text from a cover photo with Tesseract and suggest a title and author.

The suggestions are only pre-filled form text. Nothing is saved from OCR.
"""

from __future__ import annotations

import subprocess

TESSERACT_TIMEOUT_SECONDS = 60


def ocr_text(image_bytes: bytes, languages: str = "tur+eng") -> str:
    """Return the text Tesseract reads from an image, or "" when it cannot run."""
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", languages, "--psm", "6"],
            input=image_bytes,
            capture_output=True,
            timeout=TESSERACT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Covers a missing binary (FileNotFoundError) and a timeout.
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace")


def _clean_lines(text: str) -> list[str]:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return [line for line in lines if line]


def _is_title_candidate(line: str) -> bool:
    # At least three letters, or a four-digit number such as the title "1984".
    # Other digit-only lines (page numbers, ISBN fragments) are not titles.
    return sum(ch.isalpha() for ch in line) >= 3 or (line.isdigit() and len(line) == 4)


def _is_author_candidate(line: str) -> bool:
    words = line.split()
    return 2 <= len(words) <= 4 and all(word[0].isupper() for word in words)


def _is_all_caps_name(line: str) -> bool:
    return _is_author_candidate(line) and line.isupper()


def suggest_title_author(text: str) -> tuple[str, str]:
    """Suggest (title, author) from OCR text. Missing parts are returned as ""."""
    lines = _clean_lines(text)
    title_lines = [line for line in lines if _is_title_candidate(line)]
    if not title_lines:
        return "", ""

    # An all-caps name line is more likely the author, so the title is the first
    # candidate that is not one. Fall back to the first candidate.
    title = next(
        (line for line in title_lines if not _is_all_caps_name(line)),
        title_lines[0],
    )

    author_lines = [line for line in lines if line != title and _is_author_candidate(line)]
    author = next((line for line in author_lines if _is_all_caps_name(line)), "")
    if not author:
        author = author_lines[0] if author_lines else ""
    return title, author
