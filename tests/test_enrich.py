import httpx

from library import db
from library.enrich import enrich_types, lookup_subjects, types_for_subjects


def test_science_fiction_is_not_plain_fiction():
    assert types_for_subjects(["Science fiction", "Fiction"]) == ["Bilim Kurgu", "Roman"]


def test_subjects_map_and_are_capped_and_unique():
    names = types_for_subjects(["History", "Biography", "Psychology", "Fiction", "History"])
    assert names == ["Tarih", "Biyografi"]


def test_unknown_subjects_map_to_nothing():
    assert types_for_subjects(["Miscellaneous xyz"]) == []


def _client(payload=None, status=200):
    def handler(request):
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_lookup_takes_first_matching_title():
    payload = {"docs": [{"title": "Other", "subject": ["Cooking"]}, {"title": "1984 (adaptation)", "subject": ["Fiction", "Dystopias"]}]}
    assert lookup_subjects(_client(payload), "1984", "Orwell") == ["Fiction", "Dystopias"]


def test_lookup_without_title_match_is_empty():
    assert lookup_subjects(_client({"docs": [{"title": "Unrelated", "subject": ["Fiction"]}]}), "1984", None) == []


def test_enrich_adds_types_with_history_and_skips_typed_books(tmp_path):
    conn = db.connect(str(tmp_path / "e.db"))
    db.init_schema(conn)
    plain = db.add_book(conn, title="1984", author_names=["George Orwell"])
    typed = db.add_book(conn, title="Typed", author_names=["X"])
    db.attach_book_types(conn, typed, [db.ensure_type(conn, "Roman")])
    payload = {"docs": [{"title": "1984", "subject": ["Fiction", "Psychology"]}]}
    report = enrich_types(conn, _client(payload), delay=0, sleep=lambda s: None)
    assert report.updated == 1
    assert report.checked == 1
    names = [r[0] for r in conn.execute(
        "SELECT t.name FROM book_type bt JOIN type t ON t.id = bt.type_id WHERE bt.book_id = ? ORDER BY t.name", (plain,)
    ).fetchall()]
    assert names == ["Psikoloji", "Roman"]
    history = conn.execute("SELECT COUNT(*) FROM history WHERE record_id = ? AND field = 'type'", (plain,)).fetchone()[0]
    assert history == 2
    conn.close()


def test_enrich_is_safe_to_run_twice(tmp_path):
    conn = db.connect(str(tmp_path / "e.db"))
    db.init_schema(conn)
    db.add_book(conn, title="1984", author_names=["George Orwell"])
    payload = {"docs": [{"title": "1984", "subject": ["Fiction"]}]}
    enrich_types(conn, _client(payload), delay=0, sleep=lambda s: None)
    second = enrich_types(conn, _client(payload), delay=0, sleep=lambda s: None)
    assert second.checked == 0
    count = conn.execute("SELECT COUNT(*) FROM book_type").fetchone()[0]
    assert count == 1
    conn.close()


def test_rate_limit_stops_and_reports(tmp_path):
    conn = db.connect(str(tmp_path / "e.db"))
    db.init_schema(conn)
    db.add_book(conn, title="A", author_names=[])
    db.add_book(conn, title="B", author_names=[])
    report = enrich_types(conn, _client(status=429), delay=0, sleep=lambda s: None)
    assert report.stopped_early is True
    assert report.updated == 0
    conn.close()


def test_model_fallback_fills_types_when_subjects_are_missing(tmp_path):
    conn = db.connect(str(tmp_path / "m.db"))
    db.init_schema(conn)
    book = db.add_book(conn, title="Turkish novel", author_names=["Local Author"])
    report = enrich_types(
        conn,
        _client(status=404),
        delay=0,
        sleep=lambda s: None,
        classify=lambda title, authors: ["Roman", "Not a real type"],
    )
    assert report.updated == 1
    names = [r[0] for r in conn.execute(
        "SELECT t.name FROM book_type bt JOIN type t ON t.id = bt.type_id WHERE bt.book_id = ?", (book,)
    ).fetchall()]
    assert names == ["Roman"]
    conn.close()


def test_limit_processes_only_that_many(tmp_path):
    conn = db.connect(str(tmp_path / "l.db"))
    db.init_schema(conn)
    db.add_book(conn, title="A", author_names=[])
    db.add_book(conn, title="B", author_names=[])
    report = enrich_types(conn, _client(status=404), delay=0, sleep=lambda s: None, limit=1)
    assert report.checked == 1
    conn.close()
