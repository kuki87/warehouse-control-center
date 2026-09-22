"""Courier persistence adapter."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from warehouse_control_center.domain.entities import Courier
from warehouse_control_center.domain.normalization import normalize_courier_code
from warehouse_control_center.infrastructure.database.models import CourierModel
from warehouse_control_center.infrastructure.database.repositories.mapping import (
    courier_to_entity,
    courier_to_model,
)


class SqlAlchemyCourierRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, courier: Courier) -> Courier:
        model = courier_to_model(courier)
        self._session.add(model)
        self._session.flush()
        return courier_to_entity(model)

    def get_by_id(self, courier_id: int) -> Courier | None:
        model = self._session.get(CourierModel, courier_id)
        return courier_to_entity(model) if model is not None else None

    def get_by_normalized_code(self, courier_code: str) -> Courier | None:
        statement = select(CourierModel).where(
            CourierModel.courier_code_normalized == normalize_courier_code(courier_code)
        )
        model = self._session.scalar(statement)
        return courier_to_entity(model) if model is not None else None
