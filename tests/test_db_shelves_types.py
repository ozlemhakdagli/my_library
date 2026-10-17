import pytest

from library.db import (
    NameTakenError,
    add_book,
    add_shelf,
    add_type,
    connect,
    delete_shelf,
    delete_type,
    get_book,
    get_history,
    init_schema,
    list_shelves,
    list_types,
    rename_shelf,
    rename_type,
    set_book_shelf,
    set_book_types,
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


def history_rows(conn, book_id, field):
    return [
        (r["old_value"], r["new_value"])
        for r in conn.execute(
            "SELECT old_value, new_value FROM history "
            "WHERE record_type = 'book' AND record_id = ? AND field = ? ORDER BY id",
            (book_id, field),
        ).fetchall()
    ]


def test_add_and_list_shelves_and_types(conn):
    add_shelf(conn, "Roman")
    add_shelf(conn, "  Şiir  ")
    add_type(conn, "Deneme")

    shelves = list_shelves(conn)
    assert [(s["name"], s["book_count"]) for s in shelves] == [("Roman", 0), ("Şiir", 0)]
    assert [(t["name"], t["book_count"]) for t in list_types(conn)] == [("Deneme", 0)]


def test_names_are_unique_by_norm_among_live_rows(conn):
    add_shelf(conn, "Roman")
    with pytest.raises(NameTakenError):
        add_shelf(conn, "roman")
    with pytest.raises(NameTakenError):
        add_shelf(conn, "ROMÁN")

    add_type(conn, "Öykü")
    with pytest.raises(NameTakenError):
        add_type(conn, "oyku")

    with pytest.raises(ValueError):
        add_shelf(conn, "   ")


def test_rename_checks_uniqueness_and_allows_case_change(conn):
    roman = add_shelf(conn, "Roman")
    add_shelf(conn, "Şiir")
    with pytest.raises(NameTakenError):
        rename_shelf(conn, roman, "siir")

    rename_shelf(conn, roman, "roman")
    assert [s["name"] for s in list_shelves(conn)] == ["roman", "Şiir"]

    t = add_type(conn, "Deneme")
    with pytest.raises(NameTakenError):
        add_type(conn, "DENEME")
    rename_type(conn, t, "deneme")
    assert [t["name"] for t in list_types(conn)] == ["deneme"]


def test_soft_delete_hides_shelf_but_keeps_book_link_and_history(conn, book_id):
    shelf = add_shelf(conn, "Roman")
    set_book_shelf(conn, book_id, shelf)

    delete_shelf(conn, shelf)

    assert list_shelves(conn) == []
    assert get_book(conn, book_id)["id"] == book_id
    assert conn.execute("SELECT shelf_id FROM book WHERE id = ?", (book_id,)).fetchone()[
        "shelf_id"
    ] == shelf
    assert history_rows(conn, book_id, "shelf") == [(None, "Roman")]

    # A deleted name no longer blocks a new one.
    add_shelf(conn, "roman")
    assert [s["name"] for s in list_shelves(conn)] == ["roman"]


def test_soft_delete_type_hides_it_and_keeps_links(conn, book_id):
    t = add_type(conn, "Deneme")
    set_book_types(conn, book_id, [t])

    delete_type(conn, t)

    assert list_types(conn) == []
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM book_type WHERE book_id = ?", (book_id,)
    ).fetchone()["n"] == 1


def test_set_book_shelf_sets_changes_and_clears(conn, book_id):
    roman = add_shelf(conn, "Roman")
    siir = add_shelf(conn, "Şiir")

    set_book_shelf(conn, book_id, roman)
    set_book_shelf(conn, book_id, siir)
    set_book_shelf(conn, book_id, None)

    assert history_rows(conn, book_id, "shelf") == [
        (None, "Roman"),
        ("Roman", "Şiir"),
        ("Şiir", None),
    ]
    counts = {s["name"]: s["book_count"] for s in list_shelves(conn)}
    assert counts == {"Roman": 0, "Şiir": 0}


def test_set_book_shelf_same_value_writes_no_history(conn, book_id):
    roman = add_shelf(conn, "Roman")
    set_book_shelf(conn, book_id, roman)
    before = len(get_history(conn, book_id))

    set_book_shelf(conn, book_id, roman)
    set_book_shelf(conn, book_id, roman)
    set_book_shelf(conn, book_id, None)
    set_book_shelf(conn, book_id, None)

    assert len(get_history(conn, book_id)) == before + 1  # only the clear is a change


def test_set_book_shelf_rejects_unknown_or_deleted_shelf_without_writes(conn, book_id):
    roman = add_shelf(conn, "Roman")
    set_book_shelf(conn, book_id, roman)
    before = len(get_history(conn, book_id))

    with pytest.raises(ValueError):
        set_book_shelf(conn, book_id, 9999)
    delete_shelf(conn, roman)
    with pytest.raises(ValueError):
        set_book_shelf(conn, book_id, roman)

    assert len(get_history(conn, book_id)) == before
    assert conn.execute("SELECT shelf_id FROM book WHERE id = ?", (book_id,)).fetchone()[
        "shelf_id"
    ] == roman


def test_set_book_types_adds_and_removes_with_history(conn, book_id):
    deneme = add_type(conn, "Deneme")
    oyku = add_type(conn, "Öykü")
    siir = add_type(conn, "Şiir")

    set_book_types(conn, book_id, [deneme, oyku])
    assert history_rows(conn, book_id, "type") == [(None, "Deneme"), (None, "Öykü")]

    set_book_types(conn, book_id, [oyku, siir])
    assert history_rows(conn, book_id, "type") == [
        (None, "Deneme"),
        (None, "Öykü"),
        ("Deneme", None),
        (None, "Şiir"),
    ]
    counts = {t["name"]: t["book_count"] for t in list_types(conn)}
    assert counts == {"Deneme": 0, "Öykü": 1, "Şiir": 1}


def test_set_book_types_no_change_writes_no_history(conn, book_id):
    deneme = add_type(conn, "Deneme")
    set_book_types(conn, book_id, [deneme])
    before = len(get_history(conn, book_id))

    set_book_types(conn, book_id, [deneme, deneme])
    set_book_types(conn, book_id, [deneme])

    assert len(get_history(conn, book_id)) == before


def test_set_book_types_rejects_unknown_type_without_writes(conn, book_id):
    deneme = add_type(conn, "Deneme")
    before = len(get_history(conn, book_id))

    with pytest.raises(ValueError):
        set_book_types(conn, book_id, [deneme, 9999])

    assert len(get_history(conn, book_id)) == before
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM book_type WHERE book_id = ?", (book_id,)
    ).fetchone()["n"] == 0


def test_set_book_types_on_deleted_book_is_rejected(conn, book_id):
    deneme = add_type(conn, "Deneme")
    conn.execute("UPDATE book SET deleted_at = '2026-10-17' WHERE id = ?", (book_id,))
    conn.commit()

    with pytest.raises(ValueError):
        set_book_types(conn, book_id, [deneme])
    with pytest.raises(ValueError):
        set_book_shelf(conn, book_id, None)
