from library.norm import norm


def test_turkish_accent_insensitive():
    assert norm("Yapay Zekâ") == norm("YAPAY ZEKA") == norm("yapay zeka")


def test_dotted_and_dotless_i():
    assert norm("Işık") == norm("ışık") == norm("Isik")
    assert norm("İnsan") == norm("insan")


def test_none_is_empty():
    assert norm(None) == ""


def test_punctuation_removed():
    assert norm("Su'dan \"Cola\"ya") == norm("Sudan Colaya")
