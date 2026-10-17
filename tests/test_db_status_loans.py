import pytest

from library.db import (
    LoanError,
    add_book,
    connect,
    get_book,
    init_schema,
    lend_book,
    open_loans,
    return_book,
    list_loans,
    set_reading_status,
    soft_delete_book,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "lib.db"))
    init_schema(c)
    yield c
    c.close()


@pytest.fixture
def book_id(conn):
    return add_book(conn, title="Sefiller", author_names=["Victor Hugo"])


def history_fields(conn, book_id):
    return [
        r["field"]
        for r in conn.execute(
            "SELECT field FROM history WHERE record_type = 'book' AND record_id = ? ORDER BY id",
            (book_id,),
        ).fetchall()
    ]


def loan_count(conn, book_id):
    return conn.execute("SELECT COUNT(*) FROM loan WHERE book_id = ?", (book_id,)).fetchone()[0]


def test_set_reading_status_is_visible_and_recorded(conn, book_id):
    set_reading_status(conn, book_id, "reading", started_on="2026-10-01")
    book = get_book(conn, book_id)
    assert book["status"] == "reading"
    assert "status" in history_fields(conn, book_id)


def test_set_reading_status_updates_existing_row(conn, book_id):
    set_reading_status(conn, book_id, "reading")
    set_reading_status(conn, book_id, "read", finished_on="2026-10-10")
    assert get_book(conn, book_id)["status"] == "read"
    rows = conn.execute("SELECT COUNT(*) FROM reading_status WHERE book_id = ?", (book_id,)).fetchone()
    assert rows[0] == 1


def test_invalid_status_raises_and_writes_nothing(conn, book_id):
    before = history_fields(conn, book_id)
    with pytest.raises(ValueError):
        set_reading_status(conn, book_id, "lost")
    assert get_book(conn, book_id)["status"] is None
    assert history_fields(conn, book_id) == before


def test_lend_twice_raises_and_writes_no_second_loan(conn, book_id):
    lend_book(conn, book_id, "Ayşe", "2026-10-01")
    with pytest.raises(LoanError, match="already lent"):
        lend_book(conn, book_id, "Mehmet", "2026-10-02")
    assert loan_count(conn, book_id) == 1


def test_lend_writes_history(conn, book_id):
    lend_book(conn, book_id, "Ayşe", "2026-10-01")
    assert "lent_to" in history_fields(conn, book_id)
    assert get_book(conn, book_id)["loan"]["borrower"] == "Ayşe"


def test_return_twice_raises(conn, book_id):
    loan_id = lend_book(conn, book_id, "Ayşe", "2026-10-01")
    return_book(conn, loan_id, "2026-10-05")
    with pytest.raises(LoanError, match="already returned"):
        return_book(conn, loan_id, "2026-10-06")
    row = conn.execute("SELECT returned_on FROM loan WHERE id = ?", (loan_id,)).fetchone()
    assert row["returned_on"] == "2026-10-05"


def test_return_writes_history_and_allows_relending(conn, book_id):
    loan_id = lend_book(conn, book_id, "Ayşe", "2026-10-01")
    return_book(conn, loan_id, "2026-10-05")
    assert "returned_on" in history_fields(conn, book_id)
    assert get_book(conn, book_id)["loan"] is None
    lend_book(conn, book_id, "Mehmet", "2026-10-06")
    assert loan_count(conn, book_id) == 2


def test_open_loans_lists_only_unreturned(conn, book_id):
    other = add_book(conn, title="Kürk Mantolu Madonna", author_names=["Sabahattin Ali"])
    returned = lend_book(conn, book_id, "Ayşe", "2026-10-01")
    return_book(conn, returned, "2026-10-03")
    lend_book(conn, other, "Mehmet", "2026-10-04")

    loans = open_loans(conn)
    assert [(l["book_id"], l["borrower"]) for l in loans] == [(other, "Mehmet")]
    assert loans[0]["title"] == "Kürk Mantolu Madonna"


def test_lend_unknown_book_raises_and_writes_nothing(conn):
    with pytest.raises(ValueError):
        lend_book(conn, 999, "Ayşe", "2026-10-01")
    assert conn.execute("SELECT COUNT(*) FROM loan").fetchone()[0] == 0


def test_reading_status_without_dates_keeps_existing_started_on(conn, book_id):
    set_reading_status(conn, book_id, "reading", started_on="2026-10-01")
    set_reading_status(conn, book_id, "read")
    row = conn.execute(
        "SELECT status, started_on FROM reading_status WHERE book_id = ?", (book_id,)
    ).fetchone()
    assert row["status"] == "read"
    assert row["started_on"] == "2026-10-01"


def test_reading_status_empty_string_dates_keep_existing_values(conn, book_id):
    set_reading_status(conn, book_id, "reading", started_on="2026-10-01")
    set_reading_status(conn, book_id, "read", started_on="  ", finished_on="")
    row = conn.execute(
        "SELECT started_on, finished_on FROM reading_status WHERE book_id = ?", (book_id,)
    ).fetchone()
    assert row["started_on"] == "2026-10-01"
    assert row["finished_on"] is None


def test_reading_status_keeps_started_on_without_history_for_it(conn, book_id):
    set_reading_status(conn, book_id, "reading", started_on="2026-10-01")
    before = history_fields(conn, book_id)
    set_reading_status(conn, book_id, "read")
    assert history_fields(conn, book_id) == before + ["status"]


def test_reading_status_given_date_still_overwrites(conn, book_id):
    set_reading_status(conn, book_id, "reading", started_on="2026-10-01")
    set_reading_status(conn, book_id, "reading", started_on="2026-10-03")
    row = conn.execute(
        "SELECT started_on FROM reading_status WHERE book_id = ?", (book_id,)
    ).fetchone()
    assert row["started_on"] == "2026-10-03"


def test_open_loans_excludes_soft_deleted_books(conn, book_id):
    other = add_book(conn, title="Kalan Kitap", author_names=["Yazar"])
    lend_book(conn, book_id, "Ayşe", "2026-10-01")
    lend_book(conn, other, "Mehmet", "2026-10-02")
    soft_delete_book(conn, book_id)

    assert [l["book_id"] for l in open_loans(conn)] == [other]


def test_list_loans_is_newest_first_and_includes_returned(conn, book_id):
    first = lend_book(conn, book_id, "Ayşe", "2026-10-01")
    return_book(conn, first, "2026-10-03")
    lend_book(conn, book_id, "Mehmet", "2026-10-05")

    loans = list_loans(conn, book_id)
    assert [(l["borrower"], l["returned_on"]) for l in loans] == [
        ("Mehmet", None),
        ("Ayşe", "2026-10-03"),
    ]
    assert set(loans[0]) == {"borrower", "lent_on", "returned_on"}
