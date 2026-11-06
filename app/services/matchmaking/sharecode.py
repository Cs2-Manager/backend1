"""Codec de match share codes de CS:GO/CS2.

Implementa el formato comunitario documentado por `akiver/csgo-sharecode`
(MIT): 25 caracteres en base 57 que codifican, en 18 bytes little-endian,
`match_id` (8), `reservation_id`/outcome (8) y `tv_port` (2).

No se usa ninguna dependencia externa y no se realizan llamadas de red.
"""

import re

ALPHABET = "ABCDEFGHJKLMNOPQRSTUVWXYZabcdefhijkmnopqrstuvwxyz23456789"
BASE = len(ALPHABET)
CHAR_COUNT = 25
BYTE_COUNT = 18

_SHARE_CODE_RE = re.compile(
    r"^CSGO-?([" + re.escape(ALPHABET) + r"]{5})"
    r"-?([" + re.escape(ALPHABET) + r"]{5})"
    r"-?([" + re.escape(ALPHABET) + r"]{5})"
    r"-?([" + re.escape(ALPHABET) + r"]{5})"
    r"-?([" + re.escape(ALPHABET) + r"]{5})$"
)
_AUTH_CODE_RE = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{5}-[A-Z0-9]{4}$")
_DEMO_NAME_RE = re.compile(r"match730_(\d{8,21})_", re.IGNORECASE)


class ShareCodeError(ValueError):
    """Share code ausente, mal formado o fuera de rango."""


class ShareCode:
    __slots__ = ("match_id", "reservation_id", "tv_port")

    def __init__(self, match_id, reservation_id, tv_port):
        self.match_id = int(match_id)
        self.reservation_id = int(reservation_id)
        self.tv_port = int(tv_port)

    def __eq__(self, other):
        return (
            isinstance(other, ShareCode)
            and self.match_id == other.match_id
            and self.reservation_id == other.reservation_id
            and self.tv_port == other.tv_port
        )

    def __repr__(self):
        return (
            f"ShareCode(match_id={self.match_id}, "
            f"reservation_id={self.reservation_id}, tv_port={self.tv_port})"
        )


def canonical_share_code(value):
    """Devuelve el share code con el formato `CSGO-xxxxx-...` o lanza."""
    if not isinstance(value, str):
        raise ShareCodeError("Share code must be a string")
    text = value.strip()
    match = _SHARE_CODE_RE.match(text)
    if match is None:
        raise ShareCodeError("Invalid share code format")
    groups = match.groups()
    return "CSGO-" + "-".join(groups)


def decode_share_code(value):
    canonical = canonical_share_code(value)
    chars = canonical.replace("CSGO", "").replace("-", "")
    number = 0
    for char in reversed(chars):
        index = ALPHABET.index(char)
        number = number * BASE + index
    if number >= 1 << (BYTE_COUNT * 8):
        raise ShareCodeError("Share code is out of range")
    data = number.to_bytes(BYTE_COUNT, "big")
    return ShareCode(
        match_id=int.from_bytes(data[0:8], "little"),
        reservation_id=int.from_bytes(data[8:16], "little"),
        tv_port=int.from_bytes(data[16:18], "little"),
    )


def encode_share_code(match_id, reservation_id, tv_port=0):
    for name, value, limit in (
        ("match_id", match_id, 1 << 64),
        ("reservation_id", reservation_id, 1 << 64),
        ("tv_port", tv_port, 1 << 16),
    ):
        if not isinstance(value, int) or value < 0 or value >= limit:
            raise ShareCodeError(f"{name} is out of range")
    data = (
        int(match_id).to_bytes(8, "little")
        + int(reservation_id).to_bytes(8, "little")
        + int(tv_port).to_bytes(2, "little")
    )
    number = int.from_bytes(data, "big")
    chars = ""
    for _ in range(CHAR_COUNT):
        chars += ALPHABET[number % BASE]
        number //= BASE
    return (
        "CSGO-"
        + "-".join(chars[i : i + 5] for i in range(0, CHAR_COUNT, 5))
    )


def mask_share_code(value):
    """Versión para terceros: conserva el prefijo y oculta el resto."""
    try:
        canonical = canonical_share_code(value)
    except ShareCodeError:
        return None
    return canonical[:10] + "-*****-*****-*****-*****"


def validate_auth_code(value):
    """Valida y normaliza el *game authentication code* de Steam."""
    if not isinstance(value, str):
        raise ShareCodeError("Authentication code must be a string")
    text = value.strip().upper()
    if not _AUTH_CODE_RE.match(text):
        raise ShareCodeError("Invalid authentication code format")
    return text


def match_id_from_filename(filename):
    """Extrae el match id del nombre estándar `match730_<id>_<stamp>.dem`."""
    if not filename:
        return None
    match = _DEMO_NAME_RE.search(str(filename))
    if match is None:
        return None
    return int(match.group(1))
