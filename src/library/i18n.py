SUPPORTED_LANGS: tuple[str, ...] = ("en", "tr")

DICTIONARIES: dict[str, dict[str, str]] = {
    "en": {
        # navigation
        "nav_books": "Books",
        "nav_loans": "Loans",
        "nav_review": "Review",
        "nav_settings": "Settings",
        # page titles
        "title_books": "Books",
        "title_loans": "Loans",
        "title_review": "Review queue",
        "title_settings": "Settings",
        # field labels
        "field_title": "Title",
        "field_subtitle": "Subtitle",
        "field_authors": "Authors",
        "field_publisher": "Publisher",
        "field_note": "Note",
        "field_status": "Status",
        "field_loan": "Loan",
        # reading status names
        "status_unread": "Unread",
        "status_reading": "Reading",
        "status_read": "Read",
        "status_abandoned": "Abandoned",
        # buttons
        "btn_save": "Save",
        "btn_delete": "Delete",
        "btn_add": "Add",
        "btn_search": "Search",
        "btn_lend": "Lend",
        "btn_return": "Return",
        "btn_backup": "Backup",
        "btn_export": "Export",
        # messages
        "msg_saved": "Saved.",
        "msg_not_found": "Not found.",
        # placeholders
        "unknown": "unknown",
        "needs_review": "Needs review",
        "pager_prev": "Previous",
        "pager_next": "Next",
        "filter_all": "All",
        "not_on_loan": "Not on loan",
    },
    "tr": {
        # navigation
        "nav_books": "Kitaplar",
        "nav_loans": "Ödünçler",
        "nav_review": "İnceleme",
        "nav_settings": "Ayarlar",
        # page titles
        "title_books": "Kitaplar",
        "title_loans": "Ödünçler",
        "title_review": "İnceleme kuyruğu",
        "title_settings": "Ayarlar",
        # field labels
        "field_title": "Başlık",
        "field_subtitle": "Alt başlık",
        "field_authors": "Yazarlar",
        "field_publisher": "Yayıncı",
        "field_note": "Not",
        "field_status": "Durum",
        "field_loan": "Ödünç",
        # reading status names
        "status_unread": "okunmadı",
        "status_reading": "okunuyor",
        "status_read": "okundu",
        "status_abandoned": "yarım bırakıldı",
        # buttons
        "btn_save": "Kaydet",
        "btn_delete": "Sil",
        "btn_add": "Ekle",
        "btn_search": "Ara",
        "btn_lend": "Ödünç ver",
        "btn_return": "İade al",
        "btn_backup": "Yedekle",
        "btn_export": "Dışa aktar",
        # messages
        "msg_saved": "Kaydedildi.",
        "msg_not_found": "Bulunamadı.",
        # placeholders
        "unknown": "bilinmiyor",
        "needs_review": "İnceleme gerekiyor",
        "pager_prev": "Önceki",
        "pager_next": "Sonraki",
        "filter_all": "Tümü",
        "not_on_loan": "Ödünçte değil",
    },
}


def resolve_lang(query_lang: str | None, cookie_lang: str | None, default: str) -> str:
    """Pick the UI language: query parameter, then cookie, then default.

    Invalid values are skipped; if the default is also invalid, English is used.
    """
    fallback = default if default in SUPPORTED_LANGS else "en"
    for candidate in (query_lang, cookie_lang):
        if candidate in SUPPORTED_LANGS:
            return candidate
    return fallback


def translate(lang: str, key: str, **kwargs: object) -> str:
    """Return the text for ``key`` in ``lang``.

    Falls back to English when the key is missing in ``lang``, and returns the
    key itself when it is missing in English too.
    """
    text = DICTIONARIES.get(lang, {}).get(key)
    if text is None:
        text = DICTIONARIES["en"].get(key, key)
    return text.format(**kwargs) if kwargs else text
