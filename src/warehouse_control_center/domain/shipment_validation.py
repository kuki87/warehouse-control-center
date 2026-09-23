"""Central shipment field policy with Unicode-safe, non-truncating validation."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from warehouse_control_center.domain.enums import ProblemType
from warehouse_control_center.domain.exceptions import InvalidShipmentError

TRACKING_NUMBER_MAX_LENGTH = 255
BARCODE_MAX_LENGTH = 255
RECIPIENT_NAME_MAX_LENGTH = 255
RECIPIENT_ADDRESS_MAX_LENGTH = 500
RECIPIENT_CITY_MAX_LENGTH = 255
RECIPIENT_PHONE_MIN_LENGTH = 3
RECIPIENT_PHONE_MAX_LENGTH = 100
SENDER_NAME_MAX_LENGTH = 255
NOTES_MAX_LENGTH = 4_000
PROBLEM_DESCRIPTION_MAX_LENGTH = 2_000
STATUS_REASON_MAX_LENGTH = 1_000
SEARCH_MAX_LENGTH = 500

_PHONE_PUNCTUATION = frozenset("+()-./ ")


@dataclass(frozen=True, slots=True)
class ValidatedShipmentMetadata:
    recipient_name: str
    recipient_address: str
    recipient_city: str
    recipient_phone: str
    sender_name: str
    notes: str | None


@dataclass(frozen=True, slots=True)
class ValidatedShipmentFields(ValidatedShipmentMetadata):
    tracking_number: str
    barcode: str


def validate_shipment_metadata(
    *,
    recipient_name: str,
    recipient_address: str,
    recipient_city: str,
    recipient_phone: str,
    sender_name: str,
    notes: str | None,
) -> ValidatedShipmentMetadata:
    """Validate editable shipment metadata before allocating a sequence value."""
    return ValidatedShipmentMetadata(
        recipient_name=_required_text("Recipient name", recipient_name, RECIPIENT_NAME_MAX_LENGTH),
        recipient_address=_required_text(
            "Recipient address", recipient_address, RECIPIENT_ADDRESS_MAX_LENGTH
        ),
        recipient_city=_required_text("Recipient city", recipient_city, RECIPIENT_CITY_MAX_LENGTH),
        recipient_phone=validate_phone(recipient_phone),
        sender_name=_required_text("Sender name", sender_name, SENDER_NAME_MAX_LENGTH),
        notes=_optional_text("Notes", notes, NOTES_MAX_LENGTH, allow_line_breaks=True),
    )


def validate_shipment_fields(
    *,
    tracking_number: str,
    barcode: str,
    recipient_name: str,
    recipient_address: str,
    recipient_city: str,
    recipient_phone: str,
    sender_name: str,
    notes: str | None,
) -> ValidatedShipmentFields:
    """Validate and return canonical display values without silent truncation."""
    metadata = validate_shipment_metadata(
        recipient_name=recipient_name,
        recipient_address=recipient_address,
        recipient_city=recipient_city,
        recipient_phone=recipient_phone,
        sender_name=sender_name,
        notes=notes,
    )
    return ValidatedShipmentFields(
        recipient_name=metadata.recipient_name,
        recipient_address=metadata.recipient_address,
        recipient_city=metadata.recipient_city,
        recipient_phone=metadata.recipient_phone,
        sender_name=metadata.sender_name,
        notes=metadata.notes,
        tracking_number=_required_text(
            "Tracking number", tracking_number, TRACKING_NUMBER_MAX_LENGTH
        ),
        barcode=_required_text("Barcode", barcode, BARCODE_MAX_LENGTH),
    )


def validate_phone(value: str) -> str:
    canonical = _required_text("Recipient phone", value, RECIPIENT_PHONE_MAX_LENGTH)
    if len(canonical) < RECIPIENT_PHONE_MIN_LENGTH:
        raise InvalidShipmentError(
            f"Recipient phone must contain at least {RECIPIENT_PHONE_MIN_LENGTH} characters"
        )
    for character in canonical:
        if not (unicodedata.category(character) == "Nd" or character in _PHONE_PUNCTUATION):
            raise InvalidShipmentError("Recipient phone contains unsupported characters")
    return canonical


def validate_problem(
    problem_type: object,
    description: str | None,
) -> tuple[ProblemType, str | None]:
    if not isinstance(problem_type, ProblemType):
        raise InvalidShipmentError("Unsupported problem type")
    canonical = _optional_text(
        "Problem description",
        description,
        PROBLEM_DESCRIPTION_MAX_LENGTH,
        allow_line_breaks=True,
    )
    if problem_type is ProblemType.OTHER and canonical is None:
        raise InvalidShipmentError("A description is required for an OTHER problem")
    return problem_type, canonical


def validate_status_reason(value: str | None, *, required: bool) -> str | None:
    canonical = _optional_text(
        "Status reason", value, STATUS_REASON_MAX_LENGTH, allow_line_breaks=True
    )
    if required and canonical is None:
        raise InvalidShipmentError("A non-empty override reason is required")
    return canonical


def validate_optional_city(value: str | None) -> str | None:
    return _optional_text("Recipient city", value, RECIPIENT_CITY_MAX_LENGTH)


def validate_search_text(value: str | None) -> str | None:
    return _optional_text("Search", value, SEARCH_MAX_LENGTH)


def _required_text(label: str, value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidShipmentError(f"{label} must be text")
    canonical = unicodedata.normalize("NFKC", value).strip()
    if not canonical:
        raise InvalidShipmentError(f"{label} is required")
    _validate_text(label, canonical, maximum, allow_line_breaks=False)
    return canonical


def _optional_text(
    label: str,
    value: object,
    maximum: int,
    *,
    allow_line_breaks: bool = False,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidShipmentError(f"{label} must be text")
    canonical = unicodedata.normalize("NFKC", value).strip()
    if not canonical:
        return None
    _validate_text(label, canonical, maximum, allow_line_breaks=allow_line_breaks)
    return canonical


def _validate_text(
    label: str,
    value: str,
    maximum: int,
    *,
    allow_line_breaks: bool,
) -> None:
    if len(value) > maximum:
        raise InvalidShipmentError(f"{label} must contain at most {maximum} characters")
    allowed_controls = {"\n", "\r", "\t"} if allow_line_breaks else set()
    if any(
        unicodedata.category(character).startswith("C") and character not in allowed_controls
        for character in value
    ):
        raise InvalidShipmentError(f"{label} must not contain control characters")
