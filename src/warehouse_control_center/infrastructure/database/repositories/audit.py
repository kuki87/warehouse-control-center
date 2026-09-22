"""Append-only audit persistence adapter."""

from sqlalchemy.orm import Session

from warehouse_control_center.domain.entities import AuditEvent
from warehouse_control_center.infrastructure.database.models import AuditEventModel
from warehouse_control_center.infrastructure.database.repositories.mapping import (
    audit_to_entity,
    audit_to_model,
)


class SqlAlchemyAuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> AuditEvent:
        model = audit_to_model(event)
        self._session.add(model)
        self._session.flush()
        return audit_to_entity(model)

    def get_by_id(self, event_id: int) -> AuditEvent | None:
        model = self._session.get(AuditEventModel, event_id)
        return audit_to_entity(model) if model is not None else None
