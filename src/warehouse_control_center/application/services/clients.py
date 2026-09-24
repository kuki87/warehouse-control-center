"""Authorized contract-client use cases with atomic audit persistence."""

from dataclasses import asdict
from datetime import date

from warehouse_control_center.application.dto import ClientDTO, SessionContext
from warehouse_control_center.application.ports.clock import Clock
from warehouse_control_center.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from warehouse_control_center.application.services._actor import require_current_actor
from warehouse_control_center.application.services._audit import make_audit_event
from warehouse_control_center.application.services._time import utc_timestamp
from warehouse_control_center.domain.client_validation import (
    validate_client_fields,
    validate_client_search,
)
from warehouse_control_center.domain.entities import Client
from warehouse_control_center.domain.enums import AuditAction, Permission
from warehouse_control_center.domain.exceptions import (
    ClientNotFoundError,
    InvalidClientStateError,
)


class ClientService:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def create_client(
        self,
        session: SessionContext,
        *,
        client_code: str,
        company_name: str,
        address: str,
        city: str,
        tax_id: str | None = None,
        contact_name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        contract_number: str | None = None,
        contract_start: date | None = None,
        contract_end: date | None = None,
        notes: str | None = None,
    ) -> ClientDTO:
        fields = validate_client_fields(
            client_code=client_code,
            company_name=company_name,
            tax_id=tax_id,
            address=address,
            city=city,
            contact_name=contact_name,
            phone=phone,
            email=email,
            contract_number=contract_number,
            contract_start=contract_start,
            contract_end=contract_end,
            notes=notes,
        )
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.MANAGE_CLIENTS)
            now = utc_timestamp(self._clock.now())
            client = uow.clients.add(
                Client(**asdict(fields), active=True, created_at=now, updated_at=now)
            )
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.CLIENT_CREATED,
                    actor_id=actor.id,
                    actor_name=actor.username,
                    entity_id=client.id or client.client_code,
                    entity_type="CLIENT",
                    timestamp=now,
                    details={"client_code": client.client_code},
                )
            )
            uow.commit()
        return ClientDTO.from_entity(client)

    def update_client(
        self,
        session: SessionContext,
        client_id: int,
        **values: object,
    ) -> ClientDTO:
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.MANAGE_CLIENTS)
            existing = _get_client(uow, client_id)
            fields = validate_client_fields(
                client_code=values.get("client_code"),
                company_name=values.get("company_name"),
                tax_id=values.get("tax_id"),
                address=values.get("address"),
                city=values.get("city"),
                contact_name=values.get("contact_name"),
                phone=values.get("phone"),
                email=values.get("email"),
                contract_number=values.get("contract_number"),
                contract_start=values.get("contract_start"),  # type: ignore[arg-type]
                contract_end=values.get("contract_end"),  # type: ignore[arg-type]
                notes=values.get("notes"),
            )
            now = utc_timestamp(self._clock.now())
            updated = Client(
                id=existing.id,
                **asdict(fields),
                active=existing.active,
                created_at=existing.created_at,
                updated_at=now,
            )
            saved = uow.clients.save(updated)
            uow.audits.add(
                make_audit_event(
                    action=AuditAction.CLIENT_UPDATED,
                    actor_id=actor.id,
                    actor_name=actor.username,
                    entity_id=saved.id or client_id,
                    entity_type="CLIENT",
                    timestamp=now,
                    details={"client_code": saved.client_code},
                )
            )
            uow.commit()
        return ClientDTO.from_entity(saved)

    def get_client(self, session: SessionContext, client_id: int) -> ClientDTO:
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_CLIENTS)
            return ClientDTO.from_entity(_get_client(uow, client_id))

    def list_clients(
        self,
        session: SessionContext,
        *,
        search: str | None = None,
        active_only: bool = False,
    ) -> tuple[ClientDTO, ...]:
        canonical_search = validate_client_search(search)
        with self._uow_factory() as uow:
            require_current_actor(uow, session, Permission.VIEW_CLIENTS)
            return tuple(
                ClientDTO.from_entity(client)
                for client in uow.clients.list_clients(
                    search=canonical_search, active_only=active_only
                )
            )

    def activate_client(self, session: SessionContext, client_id: int) -> ClientDTO:
        return self._set_active(session, client_id, active=True)

    def deactivate_client(self, session: SessionContext, client_id: int) -> ClientDTO:
        return self._set_active(session, client_id, active=False)

    def _set_active(self, session: SessionContext, client_id: int, *, active: bool) -> ClientDTO:
        with self._uow_factory() as uow:
            actor = require_current_actor(uow, session, Permission.MANAGE_CLIENTS)
            client = _get_client(uow, client_id)
            if client.active is active:
                state = "active" if active else "inactive"
                raise InvalidClientStateError(f"Client is already {state}")
            now = utc_timestamp(self._clock.now())
            client.active = active
            client.updated_at = now
            saved = uow.clients.save(client)
            action = AuditAction.CLIENT_ACTIVATED if active else AuditAction.CLIENT_DEACTIVATED
            uow.audits.add(
                make_audit_event(
                    action=action,
                    actor_id=actor.id,
                    actor_name=actor.username,
                    entity_id=saved.id or client_id,
                    entity_type="CLIENT",
                    timestamp=now,
                    details={"client_code": saved.client_code},
                )
            )
            uow.commit()
        return ClientDTO.from_entity(saved)


def _get_client(uow: UnitOfWork, client_id: int) -> Client:
    client = uow.clients.get_by_id(client_id)
    if client is None:
        raise ClientNotFoundError(f"Client {client_id} does not exist")
    return client
