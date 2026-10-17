#!/usr/bin/env python3
"""Validate one OCR batch output against PLAN.md schema and batch membership.

Usage: .venv/bin/python src/validate_batch.py NN
"""
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK_KEYS = ("title", "subtitle", "author", "publisher", "kind", "confidence", "note", "visible_text")
KINDS = {"cover", "spine"}
CONFIDENCES = {"high", "medium", "low"}


def check_book(book, where, errors):
    if not isinstance(book, dict):
        errors.append(f"{where}: kitap bir nesne (dict) değil")
        return None
    for key in BOOK_KEYS:
        if key not in book:
            errors.append(f"{where}: kitapta '{key}' anahtarı yok")
        elif not isinstance(book[key], str):
            errors.append(f"{where}: '{key}' string değil")
    if isinstance(book.get("kind"), str) and book.get("kind") not in KINDS:
        errors.append(f"{where}: geçersiz kind={book.get('kind')!r} (cover|spine olmalı)")
    if isinstance(book.get("confidence"), str) and book.get("confidence") not in CONFIDENCES:
        errors.append(f"{where}: geçersiz confidence={book.get('confidence')!r} (high|medium|low olmalı)")
    return book.get("confidence")


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Kullanım: validate_batch.py NN", file=sys.stderr)
        return 1
    nn = sys.argv[1].zfill(2)
    batch_path = os.path.join(ROOT, "data", "batches", f"batch_{nn}.txt")
    raw_path = os.path.join(ROOT, "data", "raw", f"batch_{nn}.jsonl")

    errors = []
    try:
        with open(batch_path, encoding="utf-8") as f:
            expected_list = [os.path.basename(line.strip()) for line in f if line.strip()]
    except OSError as e:
        print(f"HATA: batch dosyası okunamadı: {e}")
        return 1
    expected = set(expected_list)

    try:
        with open(raw_path, encoding="utf-8") as f:
            raw_lines = f.read().splitlines()
    except OSError as e:
        print(f"HATA: çıktı dosyası okunamadı: {e}")
        return 1

    seen = Counter()
    n_books = 0
    n_low = 0
    for lineno, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"satır {lineno}: geçersiz JSON ({e.msg})")
            continue
        if not isinstance(rec, dict):
            errors.append(f"satır {lineno}: kayıt bir nesne (dict) değil")
            continue
        photo = rec.get("photo")
        where = f"satır {lineno} ({photo!r})"
        if not isinstance(photo, str):
            errors.append(f"satır {lineno}: 'photo' string değil")
        else:
            seen[photo] += 1
        if not isinstance(rec.get("photo_note"), str):
            errors.append(f"{where}: 'photo_note' string değil veya yok")
        books = rec.get("books")
        if not isinstance(books, list):
            errors.append(f"{where}: 'books' list değil veya yok")
            continue
        for i, book in enumerate(books, start=1):
            conf = check_book(book, f"{where} kitap #{i}", errors)
            n_books += 1
            if conf == "low":
                n_low += 1

    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    dups = sorted(p for p, c in seen.items() if c > 1)
    for p in missing:
        errors.append(f"EKSİK foto (çıktıda satır yok): {p}")
    for p in extra:
        errors.append(f"FAZLA foto (batch'te yok): {p}")
    for p in dups:
        errors.append(f"TEKRAR foto ({seen[p]} satır): {p}")

    if errors:
        print(f"HATA: {len(errors)} sorun")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"OK: {len(expected)} foto, {n_books} kitap, {n_low} low-confidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
