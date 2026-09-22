"""Pure, testable failed-login throttling policy."""

from datetime import timedelta

LOCKOUT_THRESHOLD = 5
INITIAL_LOCKOUT_SECONDS = 30
MAX_LOCKOUT_SECONDS = 15 * 60
_MAX_EXPONENTIAL_ATTEMPTS = LOCKOUT_THRESHOLD + 5


def lockout_duration(failed_attempts: int) -> timedelta | None:
    """Return the bounded lock duration for a consecutive failure count."""
    if failed_attempts < LOCKOUT_THRESHOLD:
        return None
    if failed_attempts >= _MAX_EXPONENTIAL_ATTEMPTS:
        return timedelta(seconds=MAX_LOCKOUT_SECONDS)
    exponent = failed_attempts - LOCKOUT_THRESHOLD
    seconds = min(INITIAL_LOCKOUT_SECONDS * (2**exponent), MAX_LOCKOUT_SECONDS)
    return timedelta(seconds=seconds)
