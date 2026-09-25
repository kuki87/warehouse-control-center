"""Explicit mappings keep SQLAlchemy models outside the application boundary."""

from warehouse_control_center.domain.entities import (
    AuditEvent,
    Client,
    Courier,
    Shipment,
    ShipmentProblem,
    ShipmentStatusHistory,
    ShipmentWeightCheck,
    User,
)
from warehouse_control_center.domain.measurements import (
    dimension_cm_to_mm,
    dimension_mm_to_cm,
)
from warehouse_control_center.infrastructure.database.models import (
    AuditEventModel,
    ClientModel,
    CourierModel,
    ShipmentModel,
    ShipmentProblemModel,
    ShipmentServiceModel,
    ShipmentStatusHistoryModel,
    ShipmentWeightCheckModel,
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


def client_to_model(client: Client) -> ClientModel:
    return ClientModel(
        id=client.id,
        client_code=client.client_code,
        client_code_normalized=client.client_code_normalized,
        company_name=client.company_name,
        tax_id=client.tax_id,
        address=client.address,
        city=client.city,
        contact_name=client.contact_name,
        phone=client.phone,
        email=client.email,
        contract_number=client.contract_number,
        contract_start=client.contract_start,
        contract_end=client.contract_end,
        active=client.active,
        notes=client.notes,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


def client_to_entity(model: ClientModel) -> Client:
    return Client(
        id=model.id,
        client_code=model.client_code,
        client_code_normalized=model.client_code_normalized,
        company_name=model.company_name,
        tax_id=model.tax_id,
        address=model.address,
        city=model.city,
        contact_name=model.contact_name,
        phone=model.phone,
        email=model.email,
        contract_number=model.contract_number,
        contract_start=model.contract_start,
        contract_end=model.contract_end,
        active=model.active,
        notes=model.notes,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def shipment_to_model(shipment: Shipment) -> ShipmentModel:
    return ShipmentModel(
        id=shipment.id,
        shipment_number=shipment.shipment_number,
        shipment_number_normalized=shipment.shipment_number_normalized,
        recipient_name=shipment.recipient_name,
        recipient_address=shipment.recipient_address,
        recipient_city=shipment.recipient_city,
        recipient_phone=shipment.recipient_phone,
        sender_name=shipment.sender_name,
        sender_client_id=shipment.sender_client_id,
        package_count=shipment.package_count,
        length_mm=dimension_cm_to_mm(shipment.length_cm),
        width_mm=dimension_cm_to_mm(shipment.width_cm),
        height_mm=dimension_cm_to_mm(shipment.height_cm),
        declared_weight_g=shipment.declared_weight_g,
        declared_value_fen=shipment.declared_value_fen,
        cod_enabled=shipment.cod_enabled,
        cod_amount_fen=shipment.cod_amount_fen,
        payer=shipment.payer,
        payment_method=shipment.payment_method,
        service_rows=[
            ShipmentServiceModel(service_type=service, created_at=shipment.created_at)
            for service in sorted(shipment.services, key=lambda item: item.value)
        ],
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
        shipment_number=model.shipment_number,
        shipment_number_normalized=model.shipment_number_normalized,
        recipient_name=model.recipient_name,
        recipient_address=model.recipient_address,
        recipient_city=model.recipient_city,
        recipient_phone=model.recipient_phone,
        sender_name=model.sender_name,
        sender_client_id=model.sender_client_id,
        package_count=model.package_count,
        length_cm=dimension_mm_to_cm(model.length_mm),
        width_cm=dimension_mm_to_cm(model.width_mm),
        height_cm=dimension_mm_to_cm(model.height_mm),
        declared_weight_g=model.declared_weight_g,
        declared_value_fen=model.declared_value_fen,
        cod_enabled=model.cod_enabled,
        cod_amount_fen=model.cod_amount_fen,
        payer=model.payer,
        payment_method=model.payment_method,
        services=frozenset(row.service_type for row in model.service_rows),
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


def weight_check_to_model(check: ShipmentWeightCheck) -> ShipmentWeightCheckModel:
    return ShipmentWeightCheckModel(
        id=check.id,
        shipment_id=check.shipment_id,
        declared_weight_g_snapshot=check.declared_weight_g_snapshot,
        measured_weight_g=check.measured_weight_g,
        absolute_difference_g=check.absolute_difference_g,
        difference_percent=check.difference_percent,
        tolerance_abs_g_snapshot=check.tolerance_abs_g_snapshot,
        tolerance_percent_snapshot=check.tolerance_percent_snapshot,
        result=check.result,
        checked_by_user_id=check.checked_by_user_id,
        checked_at=check.checked_at,
        note=check.note,
    )


def weight_check_to_entity(model: ShipmentWeightCheckModel) -> ShipmentWeightCheck:
    return ShipmentWeightCheck(
        id=model.id,
        shipment_id=model.shipment_id,
        declared_weight_g_snapshot=model.declared_weight_g_snapshot,
        measured_weight_g=model.measured_weight_g,
        absolute_difference_g=model.absolute_difference_g,
        difference_percent=model.difference_percent,
        tolerance_abs_g_snapshot=model.tolerance_abs_g_snapshot,
        tolerance_percent_snapshot=model.tolerance_percent_snapshot,
        result=model.result,
        checked_by_user_id=model.checked_by_user_id,
        checked_at=model.checked_at,
        note=model.note,
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
