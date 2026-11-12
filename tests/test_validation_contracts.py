"""Boundary values and exact messages for shared and media validation."""
import pytest

from app.errors import ApiError
from app.validators import parse_non_negative_int, parse_url
from app.services.media_validation import public_https_url
from app.services.workshop_service import _validate_payload


@pytest.mark.parametrize("value,expected,message", [
    (None, None, None), ("  ", None, None),
    (" https://example.test/a ", "https://example.test/a", None),
    ("javascript:alert(1)", None, "url must be an http(s) URL"),
    ("https://u:p@example.test", None, "url must not include credentials"),
    ("https://[bad", None, "url must be a valid URL"),
    ("https://wrong.test", None, "url must point to example.test"),
])
def test_url_contract(value, expected, message):
    errors = {}
    result = parse_url(value, "url", errors, allowed_host="example.test")
    assert (result, errors) == (expected, {} if message is None else {"url": message})


def test_url_length_limit_precedes_parsing():
    errors = {}
    assert parse_url("https://[bad", "url", errors, max_length=3) is None
    assert errors == {"url": "url must be at most 3 characters"}


@pytest.mark.parametrize("value,expected,invalid", [
    (None, 7, False), ("", 7, False), (0, 0, False), ("2", 2, False),
    (2.5, 2, False), (True, 7, True), (False, 7, True), (-1, 7, True), ("bad", 7, True),
])
def test_counter_contract(value, expected, invalid):
    errors = {}
    result = parse_non_negative_int(value, "kills", errors, default=7)
    expected_errors = {"kills": "kills must be a non-negative integer"} if invalid else {}
    assert (result, errors) == (expected, expected_errors)


@pytest.mark.parametrize("url,message", [
    ("http://example.test/a", "Use a public HTTPS URL"),
    ("https://example.test:444/a", "Use a public HTTPS URL"),
    ("https://example.test:bad/a", "Use a public HTTPS URL"),
    ("https://service.internal/a", "Use a public HTTPS URL"),
    ("https://127.0.0.1/a", "Private addresses are not allowed"),
    ("http://127.0.0.1:8080/a", "Private addresses are not allowed"),
    ("https://u:p@example.test/a", "url must not include credentials"),
])
def test_media_rejection_preserves_error_precedence(url, message):
    with pytest.raises(ApiError) as error:
        public_https_url(url)
    assert (error.value.status_code, error.value.fields) == (400, {"url": message})


def test_media_accepts_public_https_without_fetching():
    assert public_https_url(" https://example.test:443/a ") == "https://example.test:443/a"


def test_partial_workshop_validation_does_not_reset_other_fields():
    assert _validate_payload({"description": " new "}, partial=True) == ({}, {"description": "new"})
    assert _validate_payload({}, partial=True) == ({}, {})
