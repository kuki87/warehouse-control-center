"""Small, secret-free audit event factory shared by application services."""

from datetime import datetime

from warehouse_control_center.domain.entities import AuditEvent
from warehouse_control_center.domain.enums import AuditAction


def make_audit_event(
    *,
    action: AuditAction,
    actor_name: str,
    entity_id: int | str,
    timestamp: datetime,
    actor_id: int | None = None,
    details: dict[str, object] | None = None,
    entity_type: str = "USER",
) -> AuditEvent:
    return AuditEvent(
        action=action.value,
        actor_id=actor_id,
        actor_name_snapshot=actor_name,
        entity_type=entity_type,
        entity_id=str(entity_id),
        timestamp=timestamp,
        details={} if details is None else details,
    )
