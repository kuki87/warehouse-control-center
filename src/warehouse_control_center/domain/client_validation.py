"""Central validation policy for contract-client metadata."""

import unicodedata
from dataclasses import dataclass
from datetime import date

from warehouse_control_center.domain.exceptions import InvalidClientError

CLIENT_CODE_MAX_LENGTH = 64
COMPANY_NAME_MAX_LENGTH = 255
TAX_ID_MAX_LENGTH = 64
CLIENT_ADDRESS_MAX_LENGTH = 500
CLIENT_CITY_MAX_LENGTH = 255
CONTACT_NAME_MAX_LENGTH = 255
CLIENT_PHONE_MAX_LENGTH = 100
CLIENT_EMAIL_MAX_LENGTH = 320
CONTRACT_NUMBER_MAX_LENGTH = 100
CLIENT_NOTES_MAX_LENGTH = 4_000


@dataclass(frozen=True, slots=True)
class ValidatedClientFields:
    client_code: str
    company_name: str
    tax_id: str | None
    address: str
    city: str
    contact_name: str | None
    phone: str | None
    email: str | None
    contract_number: str | None
    contract_start: date | None
    contract_end: date | None
    notes: str | None


def validate_client_fields(
    *,
    client_code: object,
    company_name: object,
    tax_id: object | None,
    address: object,
    city: object,
    contact_name: object | None,
    phone: object | None,
    email: object | None,
    contract_number: object | None,
    contract_start: date | None,
    contract_end: date | None,
    notes: object | None,
) -> ValidatedClientFields:
    if contract_start is not None and not isinstance(contract_start, date):
        raise InvalidClientError("Contract start must be a date")
    if contract_end is not None and not isinstance(contract_end, date):
        raise InvalidClientError("Contract end must be a date")
    if contract_start is not None and contract_end is not None and contract_end < contract_start:
        raise InvalidClientError("Contract end must not be before contract start")
    canonical_email = _optional("Email", email, CLIENT_EMAIL_MAX_LENGTH)
    if canonical_email is not None and (
        "@" not in canonical_email
        or canonical_email.startswith("@")
        or canonical_email.endswith("@")
    ):
        raise InvalidClientError("Email must be a valid address")
    return ValidatedClientFields(
        client_code=_required("Client code", client_code, CLIENT_CODE_MAX_LENGTH),
        company_name=_required("Company name", company_name, COMPANY_NAME_MAX_LENGTH),
        tax_id=_optional("Tax ID", tax_id, TAX_ID_MAX_LENGTH),
        address=_required("Address", address, CLIENT_ADDRESS_MAX_LENGTH),
        city=_required("City", city, CLIENT_CITY_MAX_LENGTH),
        contact_name=_optional("Contact name", contact_name, CONTACT_NAME_MAX_LENGTH),
        phone=_optional("Phone", phone, CLIENT_PHONE_MAX_LENGTH),
        email=canonical_email,
        contract_number=_optional("Contract number", contract_number, CONTRACT_NUMBER_MAX_LENGTH),
        contract_start=contract_start,
        contract_end=contract_end,
        notes=_optional("Notes", notes, CLIENT_NOTES_MAX_LENGTH, allow_line_breaks=True),
    )


def validate_client_search(value: object | None) -> str | None:
    return _optional("Search", value, 500)


def _required(label: str, value: object, maximum: int) -> str:
    canonical = _optional(label, value, maximum)
    if canonical is None:
        raise InvalidClientError(f"{label} is required")
    return canonical


def _optional(
    label: str,
    value: object | None,
    maximum: int,
    *,
    allow_line_breaks: bool = False,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidClientError(f"{label} must be text")
    canonical = unicodedata.normalize("NFKC", value).strip()
    if not canonical:
        return None
    if len(canonical) > maximum:
        raise InvalidClientError(f"{label} must contain at most {maximum} characters")
    allowed = {"\n", "\r", "\t"} if allow_line_breaks else set()
    if any(
        unicodedata.category(character).startswith("C") and character not in allowed
        for character in canonical
    ):
        raise InvalidClientError(f"{label} must not contain control characters")
    return canonical
