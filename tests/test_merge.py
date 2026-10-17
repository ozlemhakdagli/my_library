from library.merge import (
    RawBook,
    author_compatible,
    can_merge,
    group_books,
    partial_score,
)


def rb(title, photo, author="", publisher="", subtitle="", kind="cover",
       confidence="high", note="", photo_note=""):
    return RawBook(title=title, subtitle=subtitle, author=author, publisher=publisher,
                   kind=kind, confidence=confidence, note=note, photo=photo,
                   photo_note=photo_note)


# ---------------------------------------------------------------- author compatibility

def test_author_empty_side_is_compatible():
    assert author_compatible("", "Yuval Noah Harari")
    assert author_compatible("Yuval Noah Harari", "")


def test_author_containment_is_compatible():
    assert author_compatible("Ahmet Ümit", "Ahmet Ümit Yılmaz")


def test_author_different_names_not_compatible():
    assert not author_compatible("Ali", "Veli")


# ---------------------------------------------------------------- grouping rules

def test_same_title_compatible_author_different_photo_merges():
    a = rb("Sapiens", "p1.jpg", author="Yuval Noah Harari")
    b = rb("Sapiens", "p2.jpg", author="Yuval Noah Harari")
    assert can_merge(a, b)
    result = group_books([a, b])
    assert len(result.main) == 1
    assert len(result.merged) == 1


def test_same_photo_never_merges():
    a = rb("Sapiens", "p1.jpg", author="Yuval Noah Harari")
    b = rb("Sapiens", "p1.jpg", author="Yuval Noah Harari")
    assert not can_merge(a, b)
    assert len(group_books([a, b]).main) == 2


def test_conflicting_publishers_do_not_merge():
    a = rb("Zor Kadınlara Öğüt", "p1.jpg", publisher="Domingo")
    b = rb("Zor Kadınlara Öğüt", "p2.jpg", publisher="Can Yayınları")
    assert not can_merge(a, b)
    assert len(group_books([a, b]).main) == 2


def test_base_record_is_highest_confidence_and_empty_fields_are_filled():
    low = rb("Sapiens", "p1.jpg", confidence="medium", author="")
    high = rb("Sapiens", "p2.jpg", confidence="high", author="Yuval Noah Harari",
              publisher="Kolektif")
    book = group_books([low, high]).main[0]
    assert book.photo == "p2.jpg"
    assert book.author == "Yuval Noah Harari"
    assert book.publisher == "Kolektif"


def test_fields_not_invented_when_nobody_has_them():
    a = rb("Sapiens", "p1.jpg")
    b = rb("Sapiens", "p2.jpg")
    book = group_books([a, b]).main[0]
    assert book.author == ""
    assert book.publisher == ""


def test_photos_are_kept_in_order_without_duplicates():
    recs = [rb("Sapiens", "p1.jpg", author="A"), rb("Sapiens", "p2.jpg", author="A"),
            rb("Sapiens", "p2.jpg", author="A", note="aynı foto")]
    result = group_books(recs)
    # r3 shares photo p2 with r2, so it cannot join r1+r2 and forms its own book.
    assert [m.photos for m in result.main] == [["p1.jpg", "p2.jpg"], ["p2.jpg"]]


# ---------------------------------------------------------------- partial readings

def test_partial_low_reading_with_similar_longer_title_merges():
    # Same word count and similarity 0.94 >= 0.88: the fuzzy rule holds.
    low = rb("Zor Kadınlara Öğüt", "p1.jpg", confidence="low")
    high = rb("Zor Kadınlara Övgü", "p2.jpg", confidence="high")
    result = group_books([low, high])
    assert len(result.main) == 1
    assert result.merged[0].partial is True
    assert "Kısmi okuma birleşti" in result.main[0].note


def test_partial_low_reading_substring_match_merges():
    low = rb("Zor Kadınlara", "p1.jpg", confidence="low")
    high = rb("Zor Kadınlara Öğüt", "p2.jpg", confidence="high")
    result = group_books([low, high])
    assert len(result.main) == 1
    assert result.merged[0].partial is True


def test_partial_low_reading_with_different_digits_does_not_merge():
    low = rb("Aromaterapi Karışımları 1", "p1.jpg", confidence="low")
    high = rb("Aromaterapi Karışımları 2", "p2.jpg", confidence="high")
    assert partial_score(low.title, high.title) is None
    assert len(group_books([low, high]).main) == 2


def test_short_titles_never_match_by_substring():
    assert partial_score("Kek", "Kek Ekmeği") is None
    low = rb("Kek", "p1.jpg", confidence="low")
    high = rb("Kek Ekmeği", "p2.jpg", confidence="high")
    assert len(group_books([low, high]).main) == 2


# ---------------------------------------------------------------- volumes and review

def test_volume_numbers_differ_no_merge():
    a = rb("Aromaterapi Karışımları 1", "p1.jpg", author="Ali")
    b = rb("Aromaterapi Karışımları 2", "p2.jpg", author="Ali")
    assert not can_merge(a, b)
    assert len(group_books([a, b]).main) == 2


def test_volume_label_added_to_repeated_titles_without_merge():
    a = rb("Aromaterapi", "p1.jpg", note="Cilt I")
    b = rb("Aromaterapi", "p1.jpg", note="Cilt II")
    titles = [m.title for m in group_books([a, b]).main]
    assert titles == ["Aromaterapi (Cilt I)", "Aromaterapi (Cilt II)"]


def test_unreadable_records_never_enter_main_list():
    ok = rb("Sapiens", "p1.jpg", author="Yuval Noah Harari")
    bad = rb("[okunamadı]", "p2.jpg", photo_note="bulanık")
    result = group_books([ok, bad])
    assert [m.title for m in result.main] == ["Sapiens"]
    assert result.unreadable == 1
    assert result.review[0].reason == "Okunamadı"
    assert result.review[0].photos == ["p2.jpg"]


def test_review_reasons_for_low_confidence_and_missing_author():
    result = group_books([rb("Kitap", "p1.jpg", confidence="low")])
    assert result.review[0].reason == "Düşük güven, Yazar eksik"


def test_similar_unmerged_titles_are_reported_as_possible_duplicates():
    a = rb("Sapiens Kısa Tarih", "p1.jpg", author="Yuval Noah Harari")
    b = rb("Sapiens Kısa Tarihi", "p2.jpg", author="Yuval Noah Harari")
    result = group_books([a, b])
    assert len(result.main) == 2
    assert len(result.duplicates) == 1
