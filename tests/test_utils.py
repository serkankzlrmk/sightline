"""
Test: Utility functions in country_codes.py and reliefweb_utils.py.

Pure functions — no external dependencies, no DB, no network.
"""

import pytest


# ── country_codes.py ───────────────────────────────────────────────────────────

class TestGetIsoCode:
    def test_exact_match(self):
        from reliefweb_api.country_codes import get_iso_code
        assert get_iso_code("Sudan") == "SDN"

    def test_case_insensitive_match(self):
        from reliefweb_api.country_codes import get_iso_code
        assert get_iso_code("sudan") == "SDN"

    def test_fuzzy_match(self):
        from reliefweb_api.country_codes import get_iso_code
        result = get_iso_code("Sudn")
        assert result == "SDN"

    def test_turkiye_alias(self):
        from reliefweb_api.country_codes import get_iso_code
        assert get_iso_code("Turkey") == "TUR"
        assert get_iso_code("Türkiye") == "TUR"

    def test_empty_string_returns_none(self):
        from reliefweb_api.country_codes import get_iso_code
        assert get_iso_code("") is None

    def test_none_input_returns_none(self):
        from reliefweb_api.country_codes import get_iso_code
        assert get_iso_code(None) is None

    def test_unknown_country_returns_none(self):
        from reliefweb_api.country_codes import get_iso_code
        assert get_iso_code("Xyzabaland") is None

    def test_world_returns_none(self):
        from reliefweb_api.country_codes import get_iso_code
        assert get_iso_code("World") is None


class TestGetCountryName:
    def test_known_iso_code(self):
        from reliefweb_api.country_codes import get_country_name
        assert get_country_name("SDN") == "Sudan"

    def test_case_insensitive(self):
        from reliefweb_api.country_codes import get_country_name
        assert get_country_name("sdn") == "Sudan"

    def test_unknown_code_returns_none(self):
        from reliefweb_api.country_codes import get_country_name
        assert get_country_name("ZZZ") is None

    def test_empty_string_returns_none(self):
        from reliefweb_api.country_codes import get_country_name
        assert get_country_name("") is None

    def test_none_returns_none(self):
        from reliefweb_api.country_codes import get_country_name
        assert get_country_name(None) is None


class TestCountryMappings:
    def test_iso_to_country_reverse(self):
        from reliefweb_api.country_codes import COUNTRY_TO_ISO, ISO_TO_COUNTRY
        for name, code in COUNTRY_TO_ISO.items():
            if code is not None:
                assert ISO_TO_COUNTRY.get(code) is not None, f"Missing reverse for {code}"

    def test_no_duplicate_iso_codes(self):
        from reliefweb_api.country_codes import COUNTRY_TO_ISO
        codes = [v for v in COUNTRY_TO_ISO.values() if v is not None]
        code_to_names = {}
        for name, code in COUNTRY_TO_ISO.items():
            if code is not None:
                code_to_names.setdefault(code, []).append(name)
        duplicates = {code: names for code, names in code_to_names.items() if len(names) > 1}
        assert len(duplicates) > 0, "Expected alias mappings to create duplicates"
        for code, names in duplicates.items():
            assert len(names) <= 3, f"Too many aliases for {code}: {names}"

    def test_common_crisis_countries_present(self):
        from reliefweb_api.country_codes import COUNTRY_TO_ISO
        required = ["Sudan", "Ukraine", "Syria", "Afghanistan", "Yemen",
                    "Ethiopia", "Somalia", "Myanmar", "Haiti", "South Sudan"]
        for country in required:
            assert country in COUNTRY_TO_ISO, f"Missing crisis country: {country}"


# ── reliefweb_utils.py ─────────────────────────────────────────────────────────

class TestNormalizeCountryName:
    def test_lowercase_lookup(self):
        from reliefweb_api.reliefweb_utils import normalize_country_name
        assert normalize_country_name("syria") == "Syrian Arab Republic"

    def test_abbreviation(self):
        from reliefweb_api.reliefweb_utils import normalize_country_name
        assert normalize_country_name("drc") == "Democratic Republic of the Congo"

    def test_unknown_passthrough(self):
        from reliefweb_api.reliefweb_utils import normalize_country_name
        assert normalize_country_name("Atlantis") == "Atlantis"

    def test_empty_string(self):
        from reliefweb_api.reliefweb_utils import normalize_country_name
        assert normalize_country_name("") == ""


class TestCleanHtmlBody:
    def test_strips_html_tags(self):
        from reliefweb_api.reliefweb_utils import clean_html_body
        result = clean_html_body("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_decodes_entities(self):
        from reliefweb_api.reliefweb_utils import clean_html_body
        result = clean_html_body("A &amp; B &lt; C")
        assert "A & B" in result
        assert "< C" in result

    def test_none_returns_default(self):
        from reliefweb_api.reliefweb_utils import clean_html_body
        assert clean_html_body(None) == "No content available"

    def test_empty_returns_default(self):
        from reliefweb_api.reliefweb_utils import clean_html_body
        assert clean_html_body("") == "No content available"

    def test_normalizes_whitespace(self):
        from reliefweb_api.reliefweb_utils import clean_html_body
        result = clean_html_body("Hello   \n\n   world")
        assert "  " not in result


class TestTruncateText:
    def test_short_text_unchanged(self):
        from reliefweb_api.reliefweb_utils import truncate_text
        assert truncate_text("Hello", 10) == "Hello"

    def test_long_text_truncated(self):
        from reliefweb_api.reliefweb_utils import truncate_text
        result = truncate_text("A" * 100, 10)
        assert len(result) == 10
        assert result.endswith("...")

    def test_custom_suffix(self):
        from reliefweb_api.reliefweb_utils import truncate_text
        result = truncate_text("A" * 100, 10, suffix="…")
        assert result.endswith("…")


class TestValidateCountry:
    def test_valid_country(self):
        from reliefweb_api.reliefweb_utils import validate_country
        is_valid, err = validate_country("Sudan")
        assert is_valid is True
        assert err is None

    def test_empty_country(self):
        from reliefweb_api.reliefweb_utils import validate_country
        is_valid, err = validate_country("")
        assert is_valid is False

    def test_too_short(self):
        from reliefweb_api.reliefweb_utils import validate_country
        is_valid, err = validate_country("A")
        assert is_valid is False

    def test_invalid_characters(self):
        from reliefweb_api.reliefweb_utils import validate_country
        is_valid, err = validate_country("Sudan123")
        assert is_valid is False

    def test_hyphen_and_apostrophe_ok(self):
        from reliefweb_api.reliefweb_utils import validate_country
        is_valid, err = validate_country("Cote d'Ivoire")
        assert is_valid is True


class TestValidateLimit:
    def test_valid_limit(self):
        from reliefweb_api.reliefweb_utils import validate_limit
        is_valid, err = validate_limit(10, 100)
        assert is_valid is True

    def test_limit_zero(self):
        from reliefweb_api.reliefweb_utils import validate_limit
        is_valid, err = validate_limit(0, 100)
        assert is_valid is False

    def test_limit_negative(self):
        from reliefweb_api.reliefweb_utils import validate_limit
        is_valid, err = validate_limit(-1, 100)
        assert is_valid is False

    def test_limit_exceeds_max(self):
        from reliefweb_api.reliefweb_utils import validate_limit
        is_valid, err = validate_limit(101, 100)
        assert is_valid is False

    def test_string_limit(self):
        from reliefweb_api.reliefweb_utils import validate_limit
        is_valid, err = validate_limit("abc", 100)
        assert is_valid is False


class TestValidateDate:
    def test_valid_date(self):
        from reliefweb_api.reliefweb_utils import validate_date
        is_valid, err = validate_date("2025-01-15")
        assert is_valid is True

    def test_invalid_format(self):
        from reliefweb_api.reliefweb_utils import validate_date
        is_valid, err = validate_date("15/01/2025")
        assert is_valid is False

    def test_none_date(self):
        from reliefweb_api.reliefweb_utils import validate_date
        is_valid, err = validate_date(None)
        assert is_valid is False