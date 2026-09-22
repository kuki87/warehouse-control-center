"""Explicit mappings keep SQLAlchemy models outside the application boundary."""

from warehouse_control_center.domain.entities import (
    AuditEvent,
    Courier,
    Shipment,
    ShipmentProblem,
    ShipmentStatusHistory,
    User,
)
from warehouse_control_center.infrastructure.database.models import (
    AuditEventModel,
    CourierModel,
    ShipmentModel,
    ShipmentProblemModel,
    ShipmentStatusHistoryModel,
    UserModel,
)


def user_to_model(user: User) -> UserModel:
    return UserModel(
        username=user.username,
        username_normalized=user.username_normalized,
        password_hash=user.password_hash,
        role=user.role,
        must_change_password=user.must_change_password,
        active=user.active,
        failed_login_attempts=user.failed_login_attempts,
        credential_version=user.credential_version,
        locked_until=user.locked_until,
        created_at=user.created_at,
        updated_at=user.updated_at,
        archived_at=user.archived_at,
    )


def user_to_entity(model: UserModel) -> User:
    return User(
        id=model.id,
        username=model.username,
        username_normalized=model.username_normalized,
        password_hash=model.password_hash,
        role=model.role,
        must_change_password=model.must_change_password,
        active=model.active,
        failed_login_attempts=model.failed_login_attempts,
        credential_version=model.credential_version,
        locked_until=model.locked_until,
        created_at=model.created_at,
        updated_at=model.updated_at,
        archived_at=model.archived_at,
    )


def courier_to_model(courier: Courier) -> CourierModel:
    return CourierModel(
        courier_code=courier.courier_code,
        courier_code_normalized=courier.courier_code_normalized,
        first_name=courier.first_name,
        last_name=courier.last_name,
        phone=courier.phone,
        active=courier.active,
        created_at=courier.created_at,
        updated_at=courier.updated_at,
        archived_at=courier.archived_at,
    )


def courier_to_entity(model: CourierModel) -> Courier:
    return Courier(
        id=model.id,
        courier_code=model.courier_code,
        courier_code_normalized=model.courier_code_normalized,
        first_name=model.first_name,
        last_name=model.last_name,
        phone=model.phone,
        active=model.active,
        created_at=model.created_at,
        updated_at=model.updated_at,
        archived_at=model.archived_at,
    )


def shipment_to_model(shipment: Shipment) -> ShipmentModel:
    return ShipmentModel(
        id=shipment.id,
        tracking_number=shipment.tracking_number,
        tracking_number_normalized=shipment.tracking_number_normalized,
        barcode=shipment.barcode,
        barcode_normalized=shipment.barcode_normalized,
        recipient_name=shipment.recipient_name,
        recipient_address=shipment.recipient_address,
        recipient_city=shipment.recipient_city,
        recipient_phone=shipment.recipient_phone,
        sender_name=shipment.sender_name,
        courier_id=shipment.courier_id,
        status=shipment.status,
        received_at=shipment.received_at,
        sorted_at=shipment.sorted_at,
        assigned_at=shipment.assigned_at,
        dispatched_at=shipment.dispatched_at,
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
        created_by=shipment.created_by,
        notes=shipment.notes,
        archived_at=shipment.archived_at,
        version=shipment.version,
    )


def history_to_model(history: ShipmentStatusHistory) -> ShipmentStatusHistoryModel:
    return ShipmentStatusHistoryModel(
        id=history.id,
        shipment_id=history.shipment_id,
        old_status=history.old_status,
        new_status=history.new_status,
        changed_by=history.changed_by,
        timestamp=history.timestamp,
        reason=history.reason,
        is_admin_override=history.is_admin_override,
    )


def history_to_entity(model: ShipmentStatusHistoryModel) -> ShipmentStatusHistory:
    return ShipmentStatusHistory(
        id=model.id,
        shipment_id=model.shipment_id,
        old_status=model.old_status,
        new_status=model.new_status,
        changed_by=model.changed_by,
        timestamp=model.timestamp,
        reason=model.reason,
        is_admin_override=model.is_admin_override,
    )


def problem_to_model(problem: ShipmentProblem) -> ShipmentProblemModel:
    return ShipmentProblemModel(
        id=problem.id,
        shipment_id=problem.shipment_id,
        problem_type=problem.problem_type,
        description=problem.description,
        previous_status=problem.previous_status,
        reported_by=problem.reported_by,
        reported_at=problem.reported_at,
        resolved_by=problem.resolved_by,
        resolved_at=problem.resolved_at,
    )


def problem_to_entity(model: ShipmentProblemModel) -> ShipmentProblem:
    return ShipmentProblem(
        id=model.id,
        shipment_id=model.shipment_id,
        problem_type=model.problem_type,
        description=model.description,
        previous_status=model.previous_status,
        reported_by=model.reported_by,
        reported_at=model.reported_at,
        resolved_by=model.resolved_by,
        resolved_at=model.resolved_at,
    )


def shipment_to_entity(model: ShipmentModel) -> Shipment:
    return Shipment(
        id=model.id,
        tracking_number=model.tracking_number,
        tracking_number_normalized=model.tracking_number_normalized,
        barcode=model.barcode,
        barcode_normalized=model.barcode_normalized,
        recipient_name=model.recipient_name,
        recipient_address=model.recipient_address,
        recipient_city=model.recipient_city,
        recipient_phone=model.recipient_phone,
        sender_name=model.sender_name,
        courier_id=model.courier_id,
        status=model.status,
        received_at=model.received_at,
        sorted_at=model.sorted_at,
        assigned_at=model.assigned_at,
        dispatched_at=model.dispatched_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
        created_by=model.created_by,
        notes=model.notes,
        archived_at=model.archived_at,
        version=model.version,
    )


def audit_to_model(event: AuditEvent) -> AuditEventModel:
    return AuditEventModel(
        timestamp=event.timestamp,
        actor_id=event.actor_id,
        actor_name_snapshot=event.actor_name_snapshot,
        action=event.action,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        details_json=event.details,
    )


def audit_to_entity(model: AuditEventModel) -> AuditEvent:
    return AuditEvent(
        id=model.id,
        timestamp=model.timestamp,
        actor_id=model.actor_id,
        actor_name_snapshot=model.actor_name_snapshot,
        action=model.action,
        entity_type=model.entity_type,
        entity_id=model.entity_id,
        details=model.details_json,
    )
