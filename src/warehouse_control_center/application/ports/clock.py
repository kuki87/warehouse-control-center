"""Injectable UTC clock for deterministic security policy tests."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...
