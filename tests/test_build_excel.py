#!/usr/bin/env python3
"""PLAN.md 'Faz 4 şartnamesi' kapsamındaki testler (yalnızca unittest)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import build_excel as be  # noqa: E402


def entry(title, author="", confidence="high", photo="a.jpg", **kw):
    rec = {
        "photo": photo,
        "photo_note": "",
        "title": title,
        "subtitle": "",
        "author": author,
        "publisher": "",
        "kind": "cover",
        "confidence": confidence,
        "note": "",
    }
    rec.update(kw)
    return rec


class NormTests(unittest.TestCase):
    def test_turkish_dotted_and_dotless_i(self):
        self.assertEqual(be.norm("Işık"), be.norm("ışık"))
        self.assertEqual(be.norm("Işık"), be.norm("Isik"))
        self.assertEqual(be.norm("İnsan"), be.norm("insan"))
        self.assertEqual(be.norm("BÜYÜK VERİ"), be.norm("büyük veri"))

    def test_accents_and_cedillas_removed(self):
        self.assertEqual(be.norm("Yapay Zekâ"), be.norm("YAPAY ZEKA"))
        self.assertEqual(be.norm("şğüöçâîû"), "sguocaiu")
        self.assertEqual(be.norm("ş ğ ü ö ç â î û"), "sguocaiu")

    def test_punctuation_and_spaces_removed(self):
        self.assertEqual(be.norm("Neden Böyleyim? Nasıl Değişebilirim?"), be.norm("neden böyleyim nasil degisebilirim"))
        self.assertEqual(be.norm("  Steve   Jobs - Olmak "), "stevejobsolmak")


class AuthorCompatibilityTests(unittest.TestCase):
    def test_empty_side_is_compatible(self):
        self.assertTrue(be.authors_compatible("", "Ahmet Yılmaz"))
        self.assertTrue(be.authors_compatible("Ahmet Yılmaz", ""))
        self.assertTrue(be.authors_compatible("", ""))

    def test_equal_after_norm(self):
        self.assertTrue(be.authors_compatible("Ahmet YILMAZ", "ahmet yilmaz"))

    def test_containment(self):
        self.assertTrue(be.authors_compatible("Murat Ağır", "Murat Ağır Kaya"))
        self.assertTrue(be.authors_compatible("Murat Ağır Kaya", "Murat Ağır"))

    def test_different_authors_not_compatible(self):
        self.assertFalse(be.authors_compatible("Ali Veli", "Ayşe Kaya"))


class GroupingAndMergeTests(unittest.TestCase):
    def test_same_title_compatible_author_is_one_group(self):
        entries = [
            entry("Kaynak Kod", "Bill Gates", photo="p1.jpg"),
            entry("Kaynak Kod", "", photo="p2.jpg"),
        ]
        groups = be.group_entries(entries)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_same_title_incompatible_author_stays_separate(self):
        entries = [
            entry("Kaynak Kod", "Bill Gates", photo="p1.jpg"),
            entry("Kaynak Kod", "Ahmet Yılmaz", photo="p2.jpg"),
        ]
        self.assertEqual(len(be.group_entries(entries)), 2)

    def test_base_prefers_higher_confidence(self):
        group = [
            entry("Kitap", "Yazar", confidence="medium", photo="p1.jpg", publisher="Elma"),
            entry("Kitap", "Yazar", confidence="high", photo="p2.jpg"),
        ]
        merged = be.merge_group(group)
        self.assertEqual(merged["confidence"], "high")
        self.assertEqual(merged["photo"], "p2.jpg")

    def test_tie_on_confidence_prefers_most_filled_fields(self):
        group = [
            entry("Kitap", "", confidence="high", photo="p1.jpg"),
            entry("Kitap", "Yazar", confidence="high", photo="p2.jpg", publisher="Elma"),
        ]
        merged = be.merge_group(group)
        self.assertEqual(merged["photo"], "p2.jpg")

    def test_empty_fields_filled_from_other_records(self):
        group = [
            entry("Kitap", "", confidence="high", photo="p1.jpg"),
            entry("Kitap", "Yazar Adı", confidence="medium", photo="p2.jpg",
                  subtitle="Alt Başlık", publisher="Elma"),
        ]
        merged = be.merge_group(group)
        self.assertEqual(merged["author"], "Yazar Adı")
        self.assertEqual(merged["subtitle"], "Alt Başlık")
        self.assertEqual(merged["publisher"], "Elma")

    def test_fields_not_invented_when_nobody_has_them(self):
        group = [entry("Kitap", "", photo="p1.jpg"), entry("Kitap", "", photo="p2.jpg")]
        merged = be.merge_group(group)
        self.assertEqual(merged["publisher"], "")
        self.assertEqual(merged["author"], "")

    def test_photos_are_kept_in_order_without_duplicates(self):
        group = [
            entry("Kitap", "", photo="p1.jpg"),
            entry("Kitap", "", photo="p2.jpg"),
            entry("Kitap", "", photo="p1.jpg"),
        ]
        merged = be.merge_group(group)
        self.assertEqual(merged["photos"], ["p1.jpg", "p2.jpg"])

    def test_unreadable_is_split_out(self):
        entries = [entry("[okunamadı]", confidence="low"), entry("Kitap")]
        readable, unreadable = be.split_unreadable(entries)
        self.assertEqual(len(readable), 1)
        self.assertEqual(len(unreadable), 1)
        self.assertEqual(readable[0]["title"], "Kitap")


class TurkishSortTests(unittest.TestCase):
    def test_turkish_alphabet_order(self):
        items = ["Çay", "Cam", "Zeka", "Ilık", "İnsan"]
        self.assertEqual(sorted(items, key=be.tr_sort_key),
                         ["Cam", "Çay", "Ilık", "İnsan", "Zeka"])

    def test_cedilla_and_g_breve_positions(self):
        items = ["Ümit", "Uçurum", "Ölüm", "Ozan", "Ağaç", "Gül", "Güneş", "Göl"]
        self.assertEqual(sorted(items, key=be.tr_sort_key),
                         ["Ağaç", "Göl", "Gül", "Güneş", "Ozan", "Ölüm", "Uçurum", "Ümit"])


class ConsistencyTests(unittest.TestCase):
    def test_consistent_counts_pass(self):
        # 475 ham = 400 ana + 56 birleşme + 19 okunamadı
        be.check_consistency(raw=475, main=400, absorbed=56, unreadable=19)

    def test_inconsistent_counts_raise(self):
        with self.assertRaises(ValueError):
            be.check_consistency(raw=475, main=400, absorbed=55, unreadable=19)


class PossibleDuplicateTests(unittest.TestCase):
    def test_similar_unmerged_titles_are_reported(self):
        a = be.merge_group([entry("Kaynak Kodu", "Bill Gates", photo="p1.jpg")])
        b = be.merge_group([entry("Kaynak Kod", "Bill Gates", photo="p2.jpg")])
        c = be.merge_group([entry("Samizdat", "", photo="p3.jpg")])
        pairs = be.possible_duplicates([a, b, c])
        self.assertEqual(len(pairs), 1)
        self.assertEqual({pairs[0][0]["photo"], pairs[0][1]["photo"]}, {"p1.jpg", "p2.jpg"})
        self.assertGreaterEqual(pairs[0][2], 0.88)

    def test_incompatible_authors_not_reported(self):
        # Yapay Zekâ kitapları farklı yazarlı: gürültü, tekrar değil
        a = be.merge_group([entry("Yapay Zekâ", "Stuart Russell", photo="p1.jpg")])
        b = be.merge_group([entry("Yapay Zeka", "Nick Bostrom", photo="p2.jpg")])
        self.assertEqual(be.possible_duplicates([a, b]), [])

    def test_conflicting_publishers_not_reported(self):
        a = be.merge_group([entry("Hayvan Çiftliği", "George Orwell", photo="p1.jpg",
                                  publisher="Domingo (Çizgi Roman)")])
        b = be.merge_group([entry("Hayvan Çiftliği", "George Orwell", photo="p2.jpg",
                                  publisher="Can Yayınları")])
        self.assertEqual(be.possible_duplicates([a, b]), [])

    def test_different_volume_numbers_not_reported(self):
        a = be.merge_group([entry("Aromaterapi Karışımları 1", "", photo="p1.jpg")])
        b = be.merge_group([entry("Aromaterapi Karışımları 2", "", photo="p2.jpg")])
        self.assertEqual(be.possible_duplicates([a, b]), [])

    def test_same_photo_not_reported(self):
        a = be.merge_group([entry("Kaynak Kodu", "", photo="p1.jpg")])
        b = be.merge_group([entry("Kaynak Kod", "", photo="p1.jpg")])
        self.assertEqual(be.possible_duplicates([a, b]), [])


class SamePhotoNeverMergesTests(unittest.TestCase):
    def test_two_records_from_same_photo_stay_separate(self):
        # batch_05 / 20261017_093831.jpg: iki ayrı "Sefiller" kaydı
        entries = [
            entry("Sefiller", "Victor Hugo", photo="20261017_093831.jpg", subtitle="Cilt 1"),
            entry("Sefiller", "Victor Hugo", photo="20261017_093831.jpg", subtitle="Cilt 2"),
        ]
        self.assertEqual(len(be.group_entries(entries)), 2)

    def test_same_photo_blocks_merge_even_with_empty_fields(self):
        entries = [
            entry("Kitap", "", photo="p1.jpg"),
            entry("Kitap", "", photo="p1.jpg"),
            entry("Kitap", "", photo="p2.jpg"),
        ]
        groups = be.group_entries(entries)
        self.assertEqual(sorted(len(g) for g in groups), [1, 2])


class PublisherConflictTests(unittest.TestCase):
    def test_conflicting_publishers_do_not_merge(self):
        entries = [
            entry("Hayvan Çiftliği", "George Orwell", photo="p1.jpg", publisher="Domingo (Çizgi Roman)"),
            entry("Hayvan Çiftliği", "George Orwell", photo="p2.jpg", publisher="Can Yayınları"),
        ]
        self.assertEqual(len(be.group_entries(entries)), 2)

    def test_normalized_equal_publishers_merge(self):
        entries = [
            entry("Kitap", "", photo="p1.jpg", publisher="hayykitap"),
            entry("Kitap", "", photo="p2.jpg", publisher="Hayy Kitap"),
        ]
        self.assertEqual(len(be.group_entries(entries)), 1)

    def test_publisher_containment_merges(self):
        entries = [
            entry("Kitap", "", photo="p1.jpg", publisher="Can"),
            entry("Kitap", "", photo="p2.jpg", publisher="Can Yayınları"),
        ]
        self.assertEqual(len(be.group_entries(entries)), 1)

    def test_empty_publisher_is_compatible(self):
        entries = [
            entry("Kitap", "", photo="p1.jpg", publisher=""),
            entry("Kitap", "", photo="p2.jpg", publisher="Elma"),
        ]
        self.assertEqual(len(be.group_entries(entries)), 1)


class SubtitleConflictTests(unittest.TestCase):
    def test_conflicting_subtitles_do_not_merge(self):
        entries = [
            entry("Kitap", "", photo="p1.jpg", subtitle="Bir Tarihçinin Gözünden"),
            entry("Kitap", "", photo="p2.jpg", subtitle="Roman Uyarlaması"),
        ]
        self.assertEqual(len(be.group_entries(entries)), 2)

    def test_empty_or_equal_subtitles_merge(self):
        entries = [
            entry("Kitap", "", photo="p1.jpg", subtitle=""),
            entry("Kitap", "", photo="p2.jpg", subtitle="Alt Başlık"),
            entry("Kitap", "", photo="p3.jpg", subtitle="alt baslik"),
        ]
        self.assertEqual(len(be.group_entries(entries)), 1)


class TurkishSortExtraTests(unittest.TestCase):
    def test_q_w_x_in_latin_positions(self):
        items = ["Radyo", "Quantum", "Pusula"]
        self.assertEqual(sorted(items, key=be.tr_sort_key), ["Pusula", "Quantum", "Radyo"])

    def test_w_between_v_and_y(self):
        items = ["Yapay", "Wright Kardeşler", "Werner Heisenberg", "Vahşet", "Zeka"]
        self.assertEqual(sorted(items, key=be.tr_sort_key),
                         ["Vahşet", "Werner Heisenberg", "Wright Kardeşler", "Yapay", "Zeka"])

    def test_leading_punctuation_ignored(self):
        items = ['"Su"dan Cola', "Zeka", "Sefiller"]
        self.assertEqual(sorted(items, key=be.tr_sort_key), ["Sefiller", '"Su"dan Cola', "Zeka"])

    def test_digits_first(self):
        items = ["Zeka", "Yapay", "2001 Uzay", "1984"]
        self.assertEqual(sorted(items, key=be.tr_sort_key), ["1984", "2001 Uzay", "Yapay", "Zeka"])

    def test_accented_foreign_letters_use_base_letter_position(self):
        items = ["Zeynep", "Élise", "Dünya"]
        self.assertEqual(sorted(items, key=be.tr_sort_key), ["Dünya", "Élise", "Zeynep"])


class PartialReadingMergeTests(unittest.TestCase):
    """Kural: düşük güvenli kısmi okuma, başka fotoğraftaki düşük-olmayan kayda birleşir."""

    def _rows(self, entries):
        groups = be.absorb_partials(be.group_entries(entries))
        return [be.merge_group(g) for g in groups]

    def test_low_partial_merges_into_high_reading(self):
        entries = [
            entry("Zor Kadınlara Öğüt", "", confidence="low", photo="095022.jpg"),
            entry("Zor Kadınlara Övgü", "Karen Karbo", confidence="high", photo="095025.jpg"),
        ]
        rows = self._rows(entries)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Zor Kadınlara Övgü")
        self.assertEqual(rows[0]["author"], "Karen Karbo")
        self.assertEqual(rows[0]["confidence"], "high")
        self.assertEqual(rows[0]["photos"], ["095025.jpg", "095022.jpg"])

    def test_partial_merge_adds_note_about_absorbed_reading(self):
        entries = [
            entry("Zor Kadınlara Öğüt", "", confidence="low", photo="095022.jpg"),
            entry("Zor Kadınlara Övgü", "Karen Karbo", confidence="high", photo="095025.jpg"),
        ]
        rows = self._rows(entries)
        self.assertIn("095022.jpg", rows[0]["note"])

    def test_low_prefix_title_merges_by_substring(self):
        entries = [
            entry("Yaş Almak", "", confidence="low", photo="102419.jpg"),
            entry("Yaşasın Yaş Almak", "Prof. Dr. Osman Müftüoğlu", confidence="high", photo="102434.jpg"),
        ]
        rows = self._rows(entries)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Yaşasın Yaş Almak")
        self.assertEqual(rows[0]["photos"], ["102434.jpg", "102419.jpg"])

    def test_substring_candidate_beats_fuzzy_lookalike(self):
        # "Yaşamak" ratio'su yüksek ama farklı bir kitap; alt dize eşleşmesi "Yaşasın Yaş Almak" kazanmalı
        entries = [
            entry("Yaş Almak", "", confidence="low", photo="102419.jpg"),
            entry("Yaşamak", "Yu Hua", confidence="high", photo="100627.jpg"),
            entry("Yaşasın Yaş Almak", "Prof. Dr. Osman Müftüoğlu", confidence="high", photo="102434.jpg"),
        ]
        rows = self._rows(entries)
        titles = sorted(r["title"] for r in rows)
        self.assertEqual(titles, ["Yaşamak", "Yaşasın Yaş Almak"])
        yasasin = [r for r in rows if r["title"] == "Yaşasın Yaş Almak"][0]
        self.assertEqual(yasasin["photos"], ["102434.jpg", "102419.jpg"])

    def test_fuzzy_lookalike_with_different_word_count_does_not_merge(self):
        # "Yaş Almak" ~ "Yaşamak" (benzerlik 0.93) ama farklı kelime sayısı: birleşmez
        entries = [
            entry("Yaş Almak", "", confidence="low", photo="p1.jpg"),
            entry("Yaşamak", "Yu Hua", confidence="high", photo="p2.jpg"),
        ]
        self.assertEqual(len(self._rows(entries)), 2)

    def test_short_title_never_merges_partially(self):
        # norm("Ana") uzunluğu 2 < 6: alt dize olsa bile birleşmez
        entries = [
            entry("Ana", "", confidence="low", photo="p1.jpg"),
            entry("Ana Kadın Kitabı", "Yazar Adı", confidence="high", photo="p2.jpg"),
        ]
        self.assertEqual(len(self._rows(entries)), 2)

    def test_different_digit_runs_do_not_merge_partially(self):
        entries = [
            entry("Aromaterapi Karışımları 1", "", confidence="low", photo="p1.jpg"),
            entry("Aromaterapi Karışımları 2", "", confidence="high", photo="p2.jpg"),
        ]
        self.assertEqual(len(self._rows(entries)), 2)

    def test_conflicting_author_does_not_merge_partially(self):
        entries = [
            entry("Zor Kadınlara Öğüt", "Ali Veli", confidence="low", photo="p1.jpg"),
            entry("Zor Kadınlara Övgü", "Karen Karbo", confidence="high", photo="p2.jpg"),
        ]
        self.assertEqual(len(self._rows(entries)), 2)

    def test_conflicting_publisher_does_not_merge_partially(self):
        entries = [
            entry("Zor Kadınlara Öğüt", "", confidence="low", photo="p1.jpg", publisher="Can Yayınları"),
            entry("Zor Kadınlara Övgü", "Karen Karbo", confidence="high", photo="p2.jpg",
                  publisher="Domingo"),
        ]
        self.assertEqual(len(self._rows(entries)), 2)

    def test_same_photo_does_not_merge_partially(self):
        entries = [
            entry("Zor Kadınlara Öğüt", "", confidence="low", photo="p1.jpg"),
            entry("Zor Kadınlara Övgü", "Karen Karbo", confidence="high", photo="p1.jpg"),
        ]
        self.assertEqual(len(self._rows(entries)), 2)

    def test_ambiguous_equal_candidates_do_not_merge(self):
        entries = [
            entry("Zor Kadınlara Öğüt", "", confidence="low", photo="p1.jpg"),
            entry("Zor Kadınlara Övgü", "Karen Karbo", confidence="high", photo="p2.jpg",
                  publisher="Alfa Yayınevi"),
            entry("Zor Kadınlara Övgü", "Karen Karbo", confidence="high", photo="p3.jpg",
                  publisher="Beta Yayınevi"),
        ]
        self.assertEqual(len(self._rows(entries)), 3)

    def test_low_never_absorbs_into_low(self):
        entries = [
            entry("Yaş Almak", "", confidence="low", photo="p1.jpg"),
            entry("Yaşasın Yaş Almak", "", confidence="low", photo="p2.jpg"),
        ]
        self.assertEqual(len(self._rows(entries)), 2)


class VolumeLabelTests(unittest.TestCase):
    """Kural: aynı başlıklı ayrı satırlarda not 'Cilt …' içeriyorsa görünen başlığa (Cilt X) eklenir."""

    def test_volume_label_parsing(self):
        self.assertEqual(be.volume_label("Cilt I (sırtta 'SEFİLLER - I')"), "I")
        self.assertEqual(be.volume_label("Cilt II (sırtta 'SEFİLLER - II')"), "II")
        self.assertEqual(be.volume_label("Cilt 3."), "3")
        self.assertEqual(be.volume_label("Cilt Hasarları ve Hastalıkları"), "")
        self.assertEqual(be.volume_label("Cilt Ilık"), "")
        self.assertEqual(be.volume_label(""), "")

    def test_same_title_rows_get_volume_labels(self):
        main = [
            be.merge_group([entry("Sefiller", "Victor Hugo", photo="20261017_093831.jpg",
                                  note="Cilt I (sırtta 'SEFİLLER - I')")]),
            be.merge_group([entry("Sefiller", "Victor Hugo", photo="20261017_093831.jpg",
                                  note="Cilt II (sırtta 'SEFİLLER - II')")]),
        ]
        be.label_volumes(main)
        self.assertEqual([m["title"] for m in main], ["Sefiller (Cilt I)", "Sefiller (Cilt II)"])

    def test_no_volume_info_keeps_title(self):
        main = [
            be.merge_group([entry("Sefiller", "Victor Hugo", photo="p1.jpg")]),
            be.merge_group([entry("Sefiller", "Victor Hugo", photo="p2.jpg")]),
        ]
        be.label_volumes(main)
        self.assertEqual([m["title"] for m in main], ["Sefiller", "Sefiller"])

    def test_unique_title_is_not_labeled(self):
        main = [be.merge_group([entry("Sefiller", "Victor Hugo", photo="p1.jpg", note="Cilt I")])]
        be.label_volumes(main)
        self.assertEqual(main[0]["title"], "Sefiller")


class PartialConsistencyTests(unittest.TestCase):
    def test_build_tables_counts_partial_merge_consistently(self):
        photos = [{"photo": "p1.jpg", "photo_note": "", "count": 1},
                  {"photo": "p2.jpg", "photo_note": "", "count": 1},
                  {"photo": "p3.jpg", "photo_note": "", "count": 1}]
        entries = [
            entry("Zor Kadınlara Öğüt", "", confidence="low", photo="p1.jpg"),
            entry("Zor Kadınlara Övgü", "Karen Karbo", confidence="high", photo="p2.jpg"),
            entry("[okunamadı]", confidence="low", photo="p3.jpg"),
        ]
        stats = be.build_tables(photos, entries)["stats"]
        self.assertEqual(stats["raw"], 3)
        self.assertEqual(stats["main"], 1)
        self.assertEqual(stats["absorbed"], 1)
        self.assertEqual(stats["unreadable"], 1)


if __name__ == "__main__":
    unittest.main()
