"""Pruebas del codec de share codes y códigos de autenticación."""

import pytest

from app.services.matchmaking.sharecode import (
    ShareCodeError,
    canonical_share_code,
    decode_share_code,
    encode_share_code,
    mask_share_code,
    match_id_from_filename,
    validate_auth_code,
)

MATCH_ID = (1_700_000_000 << 32) | 0x01020304
RESERVATION_ID = 123456789


def test_encode_and_decode_roundtrip():
    code = encode_share_code(MATCH_ID, RESERVATION_ID, 37020)

    assert code.startswith("CSGO-")
    assert len(code.split("-")) == 6
    assert all(len(group) == 5 for group in code.split("-")[1:])

    decoded = decode_share_code(code)
    assert decoded.match_id == MATCH_ID
    assert decoded.reservation_id == RESERVATION_ID
    assert decoded.tv_port == 37020


def test_canonical_accepts_missing_dashes_and_lowercase_prefix():
    code = encode_share_code(MATCH_ID, RESERVATION_ID, 1)
    compact = code.replace("-", "")

    assert canonical_share_code(compact) == code
    assert canonical_share_code("  " + code + "  ") == code


@pytest.mark.parametrize(
    "value",
    [
        "",
        "CSGO-12345-12345-12345-12345",
        "CSGO-ABCDE-ABCDE-ABCDE-ABCDE-ABCD0",
        "not-a-share-code",
        None,
    ],
)
def test_invalid_share_codes_are_rejected(value):
    with pytest.raises(ShareCodeError):
        canonical_share_code(value)


def test_mask_share_code_hides_payload():
    code = encode_share_code(MATCH_ID, RESERVATION_ID, 1)
    masked = mask_share_code(code)

    assert masked[:10] == code[:10]
    assert masked[10:] == "-*****-*****-*****-*****"
    assert mask_share_code("invalid") is None


def test_validate_auth_code_normalizes_and_rejects():
    assert validate_auth_code(" abcd-12345-efgh ") == "ABCD-12345-EFGH"
    for value in ("ABCD-1234-EFGH", "ABCD-12345-EFG", "", None):
        with pytest.raises(ShareCodeError):
            validate_auth_code(value)


def test_match_id_from_filename():
    name = "match730_003123456789012345678_1712345678_100.dem"
    assert match_id_from_filename(name) == 3123456789012345678
    assert match_id_from_filename("random.dem") is None
    assert match_id_from_filename(None) is None
