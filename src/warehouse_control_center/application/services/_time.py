"""Defensive UTC normalization for injected application clocks."""

from datetime import UTC, datetime


def utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Clock must return a timezone-aware datetime")
    return value.astimezone(UTC)
