from empi.standardize import (
    clean_address_line,
    clean_birth_date,
    clean_gender,
    clean_person_name,
    clean_phone,
    clean_postal,
    clean_ssn,
    clean_state,
    given_comparison_key,
    is_transposed_dob,
)


def test_phone_formats_collapse_to_ten_digits():
    assert clean_phone("(415) 555-0134") == ("4155550134", "ok")
    assert clean_phone("415.555.0134") == ("4155550134", "ok")
    assert clean_phone("1-415-555-0134") == ("4155550134", "ok")
    assert clean_phone("555-0134") == (None, "invalid")
    assert clean_phone("0000000000") == (None, "invalid")
    assert clean_phone("CALL OFFICE") == (None, "invalid")
    assert clean_phone("") == (None, "missing")
    assert clean_phone("N/A") == (None, "missing")


def test_ssn_structural_rules():
    assert clean_ssn("123-45-6789") == ("123456789", "ok")
    assert clean_ssn("123456789") == ("123456789", "ok")
    assert clean_ssn("000-12-3456") == (None, "invalid")
    assert clean_ssn("666-12-3456") == (None, "invalid")
    assert clean_ssn("900-12-3456") == (None, "invalid")
    assert clean_ssn("123-00-6789") == (None, "invalid")
    assert clean_ssn("123-45-0000") == (None, "invalid")
    assert clean_ssn("1234") == (None, "invalid")
    assert clean_ssn("") == (None, "missing")


def test_birth_date_parses_us_formats_and_rejects_impossible_dates():
    assert clean_birth_date("1990-03-04") == ("1990-03-04", "ok")
    assert clean_birth_date("3/4/1990") == ("1990-03-04", "ok")
    assert clean_birth_date("03/04/1990") == ("1990-03-04", "ok")
    assert clean_birth_date("19900304") == ("1990-03-04", "ok")
    assert clean_birth_date("02/31/1990")[1] == "invalid"
    assert clean_birth_date("1990-02-31")[1] == "invalid"
    assert clean_birth_date("13/04/1990")[1] == "invalid"
    assert clean_birth_date("2099-01-01")[1] == "invalid"
    assert clean_birth_date("1899-01-01")[1] == "invalid"
    assert clean_birth_date("") == (None, "missing")


def test_transposed_dob_detects_month_day_swap():
    assert is_transposed_dob("1990-03-04", "1990-04-03")
    assert not is_transposed_dob("1990-03-04", "1990-03-04")
    assert not is_transposed_dob("1990-03-04", "1991-07-08")


def test_names_nickname_key_and_punctuation():
    assert clean_person_name("  bill  ") == "BILL"
    assert given_comparison_key("BILL") == "WILLIAM"
    assert clean_person_name("O'Brien") == "OBRIEN"
    assert clean_person_name("Anne-Marie") == "ANNE MARIE"
    assert clean_person_name("Smith Jr.") == "SMITH"
    assert clean_person_name("Dr. William") == "WILLIAM"
    assert clean_person_name("   ") == ""


def test_address_state_postal_and_gender():
    assert clean_address_line("123 Main Street, Apt. 4") == "123 MAIN ST APT 4"
    assert clean_address_line("123 MAIN ST #4") == "123 MAIN ST APT 4"
    assert clean_address_line("123 Main Street Apartment 4") == "123 MAIN ST APT 4"
    assert clean_state("Texas") == ("TX", "ok")
    assert clean_state("tx") == ("TX", "ok")
    assert clean_state("ZZ") == ("", "invalid")
    assert clean_postal("78701-1234") == ("78701", "ok")
    assert clean_postal("AB12") == (None, "invalid")
    assert clean_gender("M") == ("male", "ok")
    assert clean_gender("female") == ("female", "ok")
    assert clean_gender("X") == ("other", "ok")
    assert clean_gender("") == ("unknown", "missing")
    assert clean_gender("N/A") == ("unknown", "missing")


def test_address_normalization_is_stable():
    once = clean_address_line("123 Main Street, Apt. 4")
    assert clean_address_line(once) == once
