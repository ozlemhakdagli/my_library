import pytest

from library.db import (
    add_book,
    connect,
    count_books,
    get_book,
    init_schema,
    list_books,
    soft_delete_book,
    update_book,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "lib.db"))
    init_schema(c)
    yield c
    c.close()


def history_rows(conn, book_id):
    return conn.execute(
        "SELECT field, old_value, new_value FROM history "
        "WHERE record_type = 'book' AND record_id = ? ORDER BY id",
        (book_id,),
    ).fetchall()


def test_add_then_get_round_trips_fields(conn):
    book_id = add_book(
        conn,
        title="Kürk Mantolu Madonna",
        subtitle="Roman",
        author_names=["Sabahattin Ali", "Ali Kaya"],
        publisher="Yapı Kredi",
    )
    book = get_book(conn, book_id)
    assert book["title"] == "Kürk Mantolu Madonna"
    assert book["subtitle"] == "Roman"
    assert book["authors"] == ["Sabahattin Ali", "Ali Kaya"]
    assert book["publisher"] == "Yapı Kredi"


def test_get_book_without_author_and_publisher(conn):
    book_id = add_book(conn, title="Yazarsız Kitap")
    book = get_book(conn, book_id)
    assert book["authors"] == []
    assert book["publisher"] == ""


def test_get_book_missing_returns_none(conn):
    assert get_book(conn, 999) is None


def test_update_changed_title_writes_exactly_one_history_row(conn):
    book_id = add_book(conn, title="Eski Başlık")
    before = len(history_rows(conn, book_id))

    entries = update_book(conn, book_id, {"title": "Yeni Başlık"})

    rows = history_rows(conn, book_id)[before:]
    assert len(rows) == 1
    assert rows[0]["field"] == "title"
    assert rows[0]["old_value"] == "Eski Başlık"
    assert rows[0]["new_value"] == "Yeni Başlık"
    assert len(entries) == 1
    assert get_book(conn, book_id)["title"] == "Yeni Başlık"


def test_update_with_no_changes_writes_no_history(conn):
    book_id = add_book(conn, title="Aynı", publisher="Y", author_names=["A"])
    before = len(history_rows(conn, book_id))

    entries = update_book(conn, book_id, {"title": "Aynı", "publisher": "Y", "authors": "A"})

    assert entries == []
    assert len(history_rows(conn, book_id)) == before


def test_update_authors_writes_one_history_row(conn):
    book_id = add_book(conn, title="Kitap", author_names=["Birinci"])
    before = len(history_rows(conn, book_id))

    update_book(conn, book_id, {"authors": "Birinci; İkinci"})

    rows = history_rows(conn, book_id)[before:]
    assert len(rows) == 1
    assert rows[0]["field"] == "authors"
    assert get_book(conn, book_id)["authors"] == ["Birinci", "İkinci"]


def test_update_rejects_unknown_field(conn):
    book_id = add_book(conn, title="Kitap")
    with pytest.raises(ValueError):
        update_book(conn, book_id, {"id": "5"})


def test_add_book_rejects_invalid_review_status(conn):
    with pytest.raises(ValueError):
        add_book(conn, title="Kitap", review_status="bilinmiyor")


def test_search_is_accent_and_case_insensitive(conn):
    add_book(conn, title="yapay zeka")
    add_book(conn, title="Başka Kitap")
    titles = [b["title"] for b in list_books(conn, query="Yapay Zekâ")]
    assert titles == ["yapay zeka"]


def test_search_matches_author_and_publisher(conn):
    add_book(conn, title="Kitap A", author_names=["Orhan Pamuk"], publisher="İş Bankası")
    add_book(conn, title="Kitap B", author_names=["Başkası"])
    assert [b["title"] for b in list_books(conn, query="orhan")] == ["Kitap A"]
    assert [b["title"] for b in list_books(conn, query="is bankasi")] == ["Kitap A"]


def test_soft_delete_hides_book_but_keeps_history(conn):
    book_id = add_book(conn, title="Silinecek")

    soft_delete_book(conn, book_id)

    assert get_book(conn, book_id) is None
    assert list_books(conn) == []
    assert count_books(conn) == 0
    fields = [r["field"] for r in history_rows(conn, book_id)]
    assert "deleted_at" in fields


def test_soft_delete_twice_writes_one_deleted_history_row(conn):
    book_id = add_book(conn, title="Silinecek")
    soft_delete_book(conn, book_id)
    soft_delete_book(conn, book_id)
    fields = [r["field"] for r in history_rows(conn, book_id)]
    assert fields.count("deleted_at") == 1


def test_list_filters_needs_review_publisher_and_loan(conn):
    a = add_book(conn, title="Ödünçte", publisher="Can", review_status="needs review")
    add_book(conn, title="Rafta", publisher="Can")
    conn.execute(
        "INSERT INTO loan (book_id, borrower, lent_on) VALUES (?, 'Ayşe', '2026-01-01')", (a,)
    )

    assert [b["title"] for b in list_books(conn, needs_review=True)] == ["Ödünçte"]
    assert count_books(conn, publisher="can") == 2
    assert [b["title"] for b in list_books(conn, loan="out")] == ["Ödünçte"]
    assert [b["title"] for b in list_books(conn, loan="in")] == ["Rafta"]
    assert get_book(conn, a)["loan"]["borrower"] == "Ayşe"


def test_list_pagination(conn):
    for i in range(5):
        add_book(conn, title=f"Kitap {i}")
    assert len(list_books(conn, limit=2)) == 2
    assert len(list_books(conn, limit=2, offset=4)) == 1
    assert count_books(conn) == 5
