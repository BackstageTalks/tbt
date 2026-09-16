from tbt.services.countries import normalize_country_code


def test_common_alpha3_country_codes_are_normalized():
    assert normalize_country_code("SVK") == "SK"
    assert normalize_country_code("DEU") == "DE"
    assert normalize_country_code("USA") == "US"
    assert normalize_country_code("ARG") == "AR"


def test_alpha2_is_preserved_and_unknown_is_empty():
    assert normalize_country_code("sk") == "SK"
    assert normalize_country_code("ZZZ") == ""
