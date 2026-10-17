"""Merge and review rules ported from src/build_excel.py.

Pure functions only: no file or database access. Thresholds and the decision
order are the same as in the reference script.
"""
import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from library.norm import norm

UNREADABLE_TITLE = "[okunamadı]"
DUP_THRESHOLD = 0.88
PARTIAL_MIN_LEN = 6  # kısmi okumada en az bu uzunlukta norm başlık
CONF_RANK = {"high": 3, "medium": 2, "low": 1}
MERGE_FIELDS = ("subtitle", "author", "publisher")
CILT_RE = re.compile(r"\b[Cc]ilt\s+([IVXLCDM]+|\d+)\b")
TR_ALPHABET = "abcçdefgğhıijklmnoöpqrsştuüvwxyz"
TR_RANK = {c: i for i, c in enumerate(TR_ALPHABET)}
_FOLD_ACCENTS = str.maketrans({"â": "a", "î": "i", "û": "u"})


@dataclass(frozen=True, eq=False)
class RawBook:
    """One book entry as read from one photo. Compared by identity."""
    title: str
    subtitle: str
    author: str
    publisher: str
    kind: str
    confidence: str
    note: str
    photo: str
    photo_note: str


@dataclass(eq=False)
class Book:
    """One row of the main list (possibly built from several RawBook records)."""
    title: str
    subtitle: str
    author: str
    publisher: str
    kind: str
    confidence: str
    note: str
    photo: str  # base record's photo
    photos: list[str]
    members: list[RawBook]  # base record first


@dataclass(eq=False)
class MergeGroup:
    """A group of records that became one Book."""
    book: Book
    members: list[RawBook]
    partial: bool  # True if any member was absorbed as a partial reading


@dataclass
class ReviewItem:
    title: str
    subtitle: str
    author: str
    publisher: str
    kind: str
    confidence: str
    photos: list[str]
    reason: str
    note: str


@dataclass
class MergeResult:
    main: list[Book]
    merged: list[MergeGroup]  # only groups with 2+ records
    review: list[ReviewItem]
    unreadable: int
    duplicates: list[tuple[Book, Book, float]] = field(default_factory=list)


# ---------------------------------------------------------------- compatibility

def fields_compatible(a: str, b: str) -> bool:
    """One is empty, or the norms are equal, or one contains the other."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return True
    return na == nb or na in nb or nb in na


def author_compatible(a: str, b: str) -> bool:
    return fields_compatible(a, b)


def _same_book_fields(a: RawBook, b: RawBook) -> bool:
    """Author, publisher and subtitle do not conflict."""
    return (fields_compatible(a.author, b.author)
            and fields_compatible(a.publisher, b.publisher)
            and fields_compatible(a.subtitle, b.subtitle))


def can_merge(a: RawBook, b: RawBook) -> bool:
    """Same normalized title, different photo, and no conflicting author/publisher/subtitle."""
    return (norm(a.title) == norm(b.title)
            and a.photo != b.photo
            and _same_book_fields(a, b))


def _digit_runs(title: str) -> list[str]:
    return re.findall(r"\d+", title)


# ---------------------------------------------------------------- partial readings

def partial_score(low_title: str, target_title: str):
    """Partial-reading match score: (is_substring, ratio), or None if no match.

    The norm title must be at least PARTIAL_MIN_LEN long, and digit runs must match.
    A substring match (1, ratio) always ranks above a fuzzy match (0, ratio).
    A fuzzy match needs ratio >= DUP_THRESHOLD and the same word count.
    """
    nl, nt = norm(low_title), norm(target_title)
    if len(nl) < PARTIAL_MIN_LEN or not nt:
        return None
    if _digit_runs(low_title) != _digit_runs(target_title):
        return None
    ratio = difflib.SequenceMatcher(None, nl, nt, autojunk=False).ratio()
    if nl in nt:
        return (1, ratio)
    if ratio >= DUP_THRESHOLD and len(low_title.split()) == len(target_title.split()):
        return (0, ratio)
    return None


# ---------------------------------------------------------------- grouping

def _filled(r: RawBook) -> int:
    return sum(1 for v in (r.subtitle, r.author, r.publisher, r.note) if v.strip())


def _base(group: list[RawBook]) -> RawBook:
    return max(group, key=lambda r: (CONF_RANK.get(r.confidence, 0), _filled(r)))


def _group_records(records: list[RawBook]) -> list[list[RawBook]]:
    """Join a record to the first group whose members it can_merge with. Input order is kept."""
    groups: list[list[RawBook]] = []
    for r in records:
        for members in groups:
            if all(can_merge(r, m) for m in members):
                members.append(r)
                break
        else:
            groups.append([r])
    return groups


def _absorb_partials(groups: list[list[RawBook]], partial_ids: set[int]) -> list[list[RawBook]]:
    """Attach low-confidence groups to a unique non-low group whose title matches.

    Absorbed record ids are added to partial_ids. A tie between two equal candidates
    means no merge.
    """
    groups = [list(g) for g in groups]
    lows = [g for g in groups if _base(g).confidence == "low"]
    targets = [g for g in groups if _base(g).confidence != "low"]
    absorbed: set[int] = set()
    for low in lows:
        low_base = _base(low)
        low_photos = {r.photo for r in low}
        cands = []
        for t in targets:
            if any(r.photo in low_photos for r in t):
                continue
            t_base = _base(t)
            score = partial_score(low_base.title, t_base.title)
            if score is None:
                continue
            if not (author_compatible(low_base.author, t_base.author)
                    and fields_compatible(low_base.publisher, t_base.publisher)):
                continue
            cands.append((score, t))
        if not cands:
            continue
        cands.sort(key=lambda c: c[0], reverse=True)
        if len(cands) > 1 and cands[0][0] == cands[1][0]:
            continue  # ambiguous: equal best candidates
        target = cands[0][1]
        for r in low:
            partial_ids.add(id(r))
        target.extend(low)
        absorbed.add(id(low))
    return [g for g in groups if id(g) not in absorbed]


def _merge_group(group: list[RawBook], partial_ids: set[int]) -> Book:
    base = _base(group)
    members = [base] + [r for r in group if r is not base]
    values = {"subtitle": base.subtitle, "author": base.author, "publisher": base.publisher}
    for name in MERGE_FIELDS:
        if not values[name].strip():
            for other in members[1:]:
                if getattr(other, name).strip():
                    values[name] = getattr(other, name)
                    break
    photos: list[str] = []
    for r in members:
        if r.photo not in photos:
            photos.append(r.photo)
    note = base.note
    partial_notes = [f"Kısmi okuma birleşti ({r.photo}): {r.title}"
                     + (f" - {r.note}" if r.note else "")
                     for r in members[1:] if id(r) in partial_ids]
    if partial_notes:
        note = " | ".join(x for x in [base.note] + partial_notes if x)
    return Book(
        title=base.title, subtitle=values["subtitle"], author=values["author"],
        publisher=values["publisher"], kind=base.kind, confidence=base.confidence,
        note=note, photo=base.photo, photos=photos, members=members,
    )


# ---------------------------------------------------------------- review and duplicates

def _possible_duplicates(bases: list[Book], threshold: float = DUP_THRESHOLD):
    """Similar titles that were not merged: [(a, b, ratio)], sorted by ratio descending.

    All of these must hold: ratio >= threshold; authors compatible; publishers not in
    conflict; same digit runs in the titles; the two books come from different photos.
    """
    pairs = []
    keys = [norm(b.title) for b in bases]
    for i in range(len(bases)):
        for j in range(i + 1, len(bases)):
            a, b = bases[i], bases[j]
            ratio = difflib.SequenceMatcher(None, keys[i], keys[j], autojunk=False).ratio()
            if ratio < threshold:
                continue
            if not author_compatible(a.author, b.author):
                continue
            if not fields_compatible(a.publisher, b.publisher):
                continue
            if _digit_runs(a.title) != _digit_runs(b.title):
                continue
            if set(a.photos) & set(b.photos):
                continue
            pairs.append((a, b, ratio))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs


def volume_label(note: str) -> str:
    """'Cilt I', 'Cilt II' or 'Cilt 3' in the note gives the volume mark, else ''."""
    m = CILT_RE.search(note or "")
    return m.group(1) if m else ""


def _label_volumes(main: list[Book]) -> None:
    """For titles that appear 2+ times in main, add ' (Cilt X)' when the note has a volume mark.
    Display only; it does not change the merge key."""
    counts: dict[str, int] = {}
    for b in main:
        k = norm(b.title)
        counts[k] = counts.get(k, 0) + 1
    for b in main:
        if counts[norm(b.title)] < 2:
            continue
        vol = volume_label(b.members[0].note)
        if vol:
            b.title = f"{b.title} (Cilt {vol})"


def _control_reasons(book: Book) -> list[str]:
    reasons = []
    if book.confidence == "low":
        reasons.append("Düşük güven")
    elif book.confidence == "medium":
        reasons.append("Orta güven")
    if not book.author.strip():
        reasons.append("Yazar eksik")
    return reasons


def _check_consistency(raw: int, main: int, absorbed: int, unreadable: int) -> None:
    if raw != main + absorbed + unreadable:
        raise ValueError(
            f"Tutarsızlık: ham={raw} != ana={main} + birleşme={absorbed} + okunamadı={unreadable}"
        )


def tr_sort_key(s: str) -> tuple:
    """Turkish alphabet order. Leading punctuation is ignored; digits come first;
    letters follow TR_ALPHABET (foreign accented letters fold to their base)."""
    f = s.replace("İ", "i").replace("I", "ı").lower().translate(_FOLD_ACCENTS)
    f = re.sub(r"^[\W_]+", "", f)
    key = []
    for c in f:
        if c in TR_RANK:
            key.append((1, TR_RANK[c]))
        elif c.isdigit():
            key.append((0, c))
        elif c.isalnum():
            base = unicodedata.normalize("NFKD", c)[0]
            if base in TR_RANK:
                key.append((1, TR_RANK[base]))
            else:
                key.append((2, ord(base)))
        else:
            key.append((-1, ord(c)))  # inner space/punctuation sorts before letters
    return tuple(key)


# ---------------------------------------------------------------- entry point

def group_books(records: list[RawBook]) -> MergeResult:
    """Apply the merge and review rules to all raw records.

    Raises ValueError if raw != main + absorbed + unreadable.
    """
    partial_ids: set[int] = set()
    readable = [r for r in records if r.title != UNREADABLE_TITLE]
    unreadable_recs = [r for r in records if r.title == UNREADABLE_TITLE]

    groups = _absorb_partials(_group_records(readable), partial_ids)
    merge_groups = []
    for g in groups:
        book = _merge_group(g, partial_ids)
        merge_groups.append(MergeGroup(book=book, members=book.members,
                                       partial=any(id(r) in partial_ids for r in g)))
    merge_groups.sort(key=lambda mg: (tr_sort_key(mg.book.title),
                                      tr_sort_key(mg.book.subtitle),
                                      norm(mg.book.author)))
    absorbed = sum(len(mg.members) - 1 for mg in merge_groups)
    _check_consistency(len(records), len(merge_groups), absorbed, len(unreadable_recs))

    main = [mg.book for mg in merge_groups]
    duplicates = _possible_duplicates(main)
    _label_volumes(main)

    control: list[tuple[tuple, ReviewItem]] = []
    for book in main:
        reasons = _control_reasons(book)
        if reasons:
            control.append(((0, tr_sort_key(book.title)), ReviewItem(
                title=book.title, subtitle=book.subtitle, author=book.author,
                publisher=book.publisher, kind=book.kind, confidence=book.confidence,
                photos=book.photos, reason=", ".join(reasons), note=book.note)))
    for r in unreadable_recs:
        note = " | ".join(x for x in (r.photo_note, r.note) if x)
        control.append(((1, r.photo), ReviewItem(
            title=UNREADABLE_TITLE, subtitle="", author="", publisher="", kind=r.kind,
            confidence="low", photos=[r.photo], reason="Okunamadı", note=note)))
    control.sort(key=lambda c: c[0])

    return MergeResult(
        main=main,
        merged=[mg for mg in merge_groups if len(mg.members) > 1],
        review=[c[1] for c in control],
        unreadable=len(unreadable_recs),
        duplicates=duplicates,
    )
