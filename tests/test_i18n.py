from library.i18n import DICTIONARIES, resolve_lang, translate


def test_query_lang_is_used():
    assert resolve_lang("tr", None, "en") == "tr"


def test_invalid_query_falls_back_to_default():
    assert resolve_lang("fr", None, "en") == "en"


def test_cookie_used_when_no_query():
    assert resolve_lang(None, "tr", "en") == "tr"


def test_query_beats_cookie():
    assert resolve_lang("en", "tr", "tr") == "en"


def test_invalid_cookie_falls_back_to_default():
    assert resolve_lang(None, "de", "tr") == "tr"


def test_nothing_given_uses_default():
    assert resolve_lang(None, None, "en") == "en"


def test_dictionaries_have_identical_key_sets():
    assert set(DICTIONARIES["en"]) == set(DICTIONARIES["tr"])


def test_unknown_translates_per_language():
    assert translate("tr", "unknown") == "bilinmiyor"
    assert translate("en", "unknown") == "unknown"


def test_needs_review_translates_per_language():
    assert translate("tr", "needs_review") == "İnceleme gerekiyor"
    assert translate("en", "needs_review") == "Needs review"


def test_status_names_translate():
    assert translate("tr", "status_unread") == "okunmadı"
    assert translate("tr", "status_reading") == "okunuyor"
    assert translate("tr", "status_read") == "okundu"
    assert translate("tr", "status_abandoned") == "yarım bırakıldı"


def test_missing_tr_key_falls_back_to_en(monkeypatch):
    monkeypatch.setitem(DICTIONARIES["en"], "only_en", "English only")
    assert translate("tr", "only_en") == "English only"


def test_missing_in_both_returns_key():
    assert translate("tr", "no_such_key") == "no_such_key"
    assert translate("en", "no_such_key") == "no_such_key"


def test_kwargs_are_interpolated(monkeypatch):
    monkeypatch.setitem(DICTIONARIES["en"], "greet", "Hello {name}")
    monkeypatch.setitem(DICTIONARIES["tr"], "greet", "Merhaba {name}")
    assert translate("en", "greet", name="Ada") == "Hello Ada"
    assert translate("tr", "greet", name="Ada") == "Merhaba Ada"


def test_required_ui_keys_present_in_both_languages():
    required = [
        "nav_books", "nav_loans", "nav_review", "nav_settings",
        "title_books", "title_loans", "title_review", "title_settings",
        "field_title", "field_subtitle", "field_authors", "field_publisher",
        "field_note", "field_status", "field_loan",
        "status_unread", "status_reading", "status_read", "status_abandoned",
        "btn_save", "btn_delete", "btn_add", "btn_search", "btn_lend",
        "btn_return", "btn_backup", "btn_export",
        "msg_saved", "msg_not_found", "unknown", "needs_review",
    ]
    for lang in ("en", "tr"):
        missing = [k for k in required if k not in DICTIONARIES[lang]]
        assert missing == [], f"{lang} missing: {missing}"
