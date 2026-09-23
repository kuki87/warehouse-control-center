"""Presentation-only formatting for shipment values."""

from datetime import datetime
from zoneinfo import ZoneInfo


def display_timestamp(value: datetime | None, timezone_name: str) -> str:
    if value is None:
        return "—"
    return value.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M %Z")


def display_enum(value: str) -> str:
    return value.replace("_", " ").title()
