import pytest

from empi.stringmatch import jaro_similarity, jaro_winkler, soundex


def test_soundex_standard_examples():
    assert soundex("Smith") == "S530"
    assert soundex("Smyth") == "S530"
    assert soundex("Robert") == "R163"
    assert soundex("Rupert") == "R163"
    assert soundex("Ashcraft") == "A261"
    assert soundex("Tymczak") == "T522"
    assert soundex("Pfister") == "P236"
    assert soundex("Jackson") == "J250"
    assert soundex("") == ""


def test_jaro_winkler_standard_examples():
    assert jaro_similarity("MARTHA", "MARHTA") == pytest.approx(0.944, abs=0.001)
    assert jaro_winkler("MARTHA", "MARHTA") == pytest.approx(0.961, abs=0.001)
    assert jaro_similarity("DIXON", "DICKSONX") == pytest.approx(0.767, abs=0.001)
    assert jaro_winkler("DIXON", "DICKSONX") == pytest.approx(0.813, abs=0.001)
    assert jaro_winkler("JELLYFISH", "SMELLYFISH") == pytest.approx(0.896, abs=0.001)
    assert jaro_winkler("WILLIAM", "WILLIAM") == 1


def test_jaro_winkler_empty_strings():
    assert jaro_winkler("", "") == 1
    assert jaro_similarity("A", "") == 0
