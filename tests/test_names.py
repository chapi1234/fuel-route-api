import pytest

from geo.names import gazetteer_name_variants, place_key


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Mc Kees Rocks", "McKees Rocks"),
        ("St. Louis", "Saint Louis"),
        ("Sault Ste Marie", "Sault Sainte Marie"),
        ("Ft. Worth", "Fort Worth"),
        ("O'Neill", "ONeill"),
        ("Effingham        ", "effingham"),
        ("De Witt", "DeWitt"),
    ],
)
def test_place_key_matches_spelling_variants(a, b):
    assert place_key(a) == place_key(b)


def test_place_key_keeps_distinct_names_apart():
    assert place_key("Bay City") != place_key("Bay")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Abbeville city", "Abbeville"),
        ("Bay City city", "Bay City"),
        ("Bow town", "Bow"),
        ("Indianapolis city (balance)", "Indianapolis"),
        ("Nashville-Davidson metropolitan government (balance)", "Nashville"),
    ],
)
def test_gazetteer_variants_end_with_the_plain_name(name, expected):
    assert gazetteer_name_variants(name)[-1] == expected
