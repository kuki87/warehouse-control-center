"""Canonical identifiers used before uniqueness checks."""

import unicodedata


def normalize_username(value: str) -> str:
    return _normalized_text(value).casefold()


def normalize_shipment_number(value: str) -> str:
    return _compact_identifier(value).upper()


def normalize_courier_code(value: str) -> str:
    return _compact_identifier(value).casefold()


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _compact_identifier(value: str) -> str:
    return "".join(_normalized_text(value).split())
