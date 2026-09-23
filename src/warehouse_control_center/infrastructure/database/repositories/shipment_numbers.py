"""Transactional allocation of human-facing shipment numbers.

The counter update participates in the shipment Unit of Work. A failed insert,
audit, or commit therefore rolls the allocation back; another transaction may
reuse that never-committed value. The system does not promise gap-free numbers.
"""

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from warehouse_control_center.domain.exceptions import (
    DatabaseBusyError,
    ShipmentNumberAllocationError,
    ShipmentNumberExhaustedError,
)
from warehouse_control_center.domain.shipment_numbering import (
    SHIPMENT_NUMBER_MAX_VALUE,
    SHIPMENT_NUMBER_SEQUENCE_NAME,
    format_shipment_number,
)
from warehouse_control_center.infrastructure.database.models import (
    ShipmentNumberSequenceModel,
)


class SqlAlchemyShipmentNumberRepository:
    """Use one atomic row update so concurrent transactions cannot allocate duplicates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def allocate(self) -> str:
        statement = (
            update(ShipmentNumberSequenceModel)
            .where(
                ShipmentNumberSequenceModel.name == SHIPMENT_NUMBER_SEQUENCE_NAME,
                ShipmentNumberSequenceModel.next_value <= SHIPMENT_NUMBER_MAX_VALUE,
            )
            .values(next_value=ShipmentNumberSequenceModel.next_value + 1)
            .returning(ShipmentNumberSequenceModel.next_value)
        )
        try:
            incremented_value = self._session.scalar(statement)
        except OperationalError as error:
            if "database is locked" in str(error).casefold():
                raise DatabaseBusyError("Database is busy; retry the operation") from None
            raise ShipmentNumberAllocationError("Shipment number allocation failed") from error
        if incremented_value is not None:
            return format_shipment_number(incremented_value - 1)

        current_value = self._session.scalar(
            select(ShipmentNumberSequenceModel.next_value).where(
                ShipmentNumberSequenceModel.name == SHIPMENT_NUMBER_SEQUENCE_NAME
            )
        )
        if current_value is None:
            raise ShipmentNumberAllocationError("Shipment number sequence is unavailable")
        raise ShipmentNumberExhaustedError("Shipment number capacity is exhausted")
