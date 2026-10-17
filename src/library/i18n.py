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
        # book detail
        "btn_edit": "Edit",
        "field_started": "Started",
        "field_finished": "Finished",
        "history_title": "Change history",
        "hist_field": "Field",
        "hist_old": "Old value",
        "hist_new": "New value",
        "hist_when": "When",
        "history_empty": "No changes recorded.",
        "photos_title": "Photos",
        "photos_empty": "No photos.",
        "loan_history_title": "Loan history",
        "loan_borrower": "Borrower",
        "loan_lent_on": "Lent on",
        "loan_returned_on": "Returned on",
        "loan_empty": "No loans yet.",
        # history field names
        "hf_title": "Title",
        "hf_subtitle": "Subtitle",
        "hf_note": "Note",
        "hf_review_status": "Review status",
        "hf_publisher": "Publisher",
        "hf_authors": "Authors",
        "hf_status": "Status",
        "hf_started_on": "Started",
        "hf_finished_on": "Finished",
        "hf_lent_to": "Borrower",
        "hf_lent_on": "Lent on",
        "hf_returned_on": "Returned on",
        "hf_deleted_at": "Deleted",
        "hf_review_resolution": "Review",
        # loans
        "loans_lend_title": "Lend a book",
        "loans_open_title": "Books currently out",
        "loans_empty": "No books are out.",
        "field_book_id": "Book ID",
        "field_lent_on": "Lent on",
        "field_returned_on": "Returned on",
        "err_already_lent": "This book is already on loan.",
        "err_already_returned": "This loan was already returned.",
        "err_invalid": "Invalid input.",
        # review queue
        "review_empty": "The review queue is empty.",
        "unreadable_title": "[unreadable]",
        "field_reason": "Reason",
        "field_photo": "Photo",
        "btn_confirm": "Confirm",
        "btn_correct": "Correct",
        "btn_not_a_book": "Not a book",
        "btn_next": "Next",
        "err_already_resolved": "This item was already resolved.",
        "reason_low_confidence": "low confidence",
        "reason_medium_confidence": "medium confidence",
        "reason_author_missing": "author missing",
        "reason_unreadable": "unreadable",
        # settings
        "settings_backup_title": "Backup",
        "settings_backup_help": "Save a copy of the database file to the backup folder.",
        "settings_backup_done": "Backup saved to {path}",
        "settings_export_title": "CSV export",
        "settings_export_help": "Download all books (deleted books are not included) as a CSV file.",
        "settings_language_title": "Language",
        "settings_language_label": "Interface language",
        "lang_name_en": "English",
        "lang_name_tr": "Türkçe",
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
        # book detail
        "btn_edit": "Düzenle",
        "field_started": "Başlangıç",
        "field_finished": "Bitiş",
        "history_title": "Değişiklik geçmişi",
        "hist_field": "Alan",
        "hist_old": "Eski değer",
        "hist_new": "Yeni değer",
        "hist_when": "Ne zaman",
        "history_empty": "Kayıtlı değişiklik yok.",
        "photos_title": "Fotoğraflar",
        "photos_empty": "Fotoğraf yok.",
        "loan_history_title": "Ödünç geçmişi",
        "loan_borrower": "Ödünç alan",
        "loan_lent_on": "Verildiği tarih",
        "loan_returned_on": "İade tarihi",
        "loan_empty": "Henüz ödünç yok.",
        # history field names
        "hf_title": "Başlık",
        "hf_subtitle": "Alt başlık",
        "hf_note": "Not",
        "hf_review_status": "İnceleme durumu",
        "hf_publisher": "Yayıncı",
        "hf_authors": "Yazarlar",
        "hf_status": "Durum",
        "hf_started_on": "Başlangıç",
        "hf_finished_on": "Bitiş",
        "hf_lent_to": "Ödünç alan",
        "hf_lent_on": "Verildiği tarih",
        "hf_returned_on": "İade tarihi",
        "hf_deleted_at": "Silindi",
        "hf_review_resolution": "İnceleme",
        # loans
        "loans_lend_title": "Kitap ödünç ver",
        "loans_open_title": "Şu an ödünçte olan kitaplar",
        "loans_empty": "Ödünçte kitap yok.",
        "field_book_id": "Kitap no",
        "field_lent_on": "Verildiği tarih",
        "field_returned_on": "İade tarihi",
        "err_already_lent": "Bu kitap zaten ödünçte.",
        "err_already_returned": "Bu ödünç zaten iade alındı.",
        "err_invalid": "Geçersiz giriş.",
        # review queue
        "review_empty": "İnceleme kuyruğu boş.",
        "unreadable_title": "[okunamadı]",
        "field_reason": "Neden",
        "field_photo": "Fotoğraf",
        "btn_confirm": "Onayla",
        "btn_correct": "Düzelt",
        "btn_not_a_book": "Kitap değil",
        "btn_next": "Sonraki",
        "err_already_resolved": "Bu kayıt zaten sonuçlandırılmış.",
        "reason_low_confidence": "düşük güven",
        "reason_medium_confidence": "orta güven",
        "reason_author_missing": "yazar eksik",
        "reason_unreadable": "okunamadı",
        # settings
        "settings_backup_title": "Yedek",
        "settings_backup_help": "Veritabanı dosyasının bir kopyasını yedek klasörüne kaydeder.",
        "settings_backup_done": "Yedek kaydedildi: {path}",
        "settings_export_title": "CSV dışa aktarma",
        "settings_export_help": "Tüm kitapları (silinenler dahil değil) CSV dosyası olarak indirir.",
        "settings_language_title": "Dil",
        "settings_language_label": "Arayüz dili",
        "lang_name_en": "English",
        "lang_name_tr": "Türkçe",
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
