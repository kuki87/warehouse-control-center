"""Shipment persistence adapter."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from warehouse_control_center.domain.entities import Shipment
from warehouse_control_center.domain.normalization import (
    normalize_barcode,
    normalize_tracking_number,
)
from warehouse_control_center.infrastructure.database.models import ShipmentModel
from warehouse_control_center.infrastructure.database.repositories.mapping import (
    shipment_to_entity,
    shipment_to_model,
)


class SqlAlchemyShipmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, shipment: Shipment) -> Shipment:
        model = shipment_to_model(shipment)
        self._session.add(model)
        self._session.flush()
        return shipment_to_entity(model)

    def get_by_id(self, shipment_id: int) -> Shipment | None:
        model = self._session.get(ShipmentModel, shipment_id)
        return shipment_to_entity(model) if model is not None else None

    def get_by_normalized_tracking_number(self, tracking_number: str) -> Shipment | None:
        statement = select(ShipmentModel).where(
            ShipmentModel.tracking_number_normalized == normalize_tracking_number(tracking_number)
        )
        model = self._session.scalar(statement)
        return shipment_to_entity(model) if model is not None else None

    def get_by_normalized_barcode(self, barcode: str) -> Shipment | None:
        statement = select(ShipmentModel).where(
            ShipmentModel.barcode_normalized == normalize_barcode(barcode)
        )
        model = self._session.scalar(statement)
        return shipment_to_entity(model) if model is not None else None
