"""Contract-client persistence adapter."""

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from warehouse_control_center.domain.entities import Client
from warehouse_control_center.domain.exceptions import DuplicateClientCodeError
from warehouse_control_center.domain.normalization import normalize_client_code
from warehouse_control_center.infrastructure.database.models import ClientModel
from warehouse_control_center.infrastructure.database.repositories.mapping import (
    client_to_entity,
    client_to_model,
)


class SqlAlchemyClientRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, client: Client) -> Client:
        model = client_to_model(client)
        self._session.add(model)
        self._flush()
        return client_to_entity(model)

    def save(self, client: Client) -> Client:
        if client.id is None:
            raise ValueError("Cannot save a client without an id")
        model = self._session.get(ClientModel, client.id)
        if model is None:
            raise ValueError(f"Client {client.id} does not exist")
        for name in (
            "client_code",
            "client_code_normalized",
            "company_name",
            "tax_id",
            "address",
            "city",
            "contact_name",
            "phone",
            "email",
            "contract_number",
            "contract_start",
            "contract_end",
            "active",
            "notes",
            "updated_at",
        ):
            setattr(model, name, getattr(client, name))
        self._flush()
        return client_to_entity(model)

    def get_by_id(self, client_id: int) -> Client | None:
        model = self._session.get(ClientModel, client_id)
        return client_to_entity(model) if model is not None else None

    def get_by_normalized_code(self, client_code: str) -> Client | None:
        model = self._session.scalar(
            select(ClientModel).where(
                ClientModel.client_code_normalized == normalize_client_code(client_code)
            )
        )
        return client_to_entity(model) if model is not None else None

    def list_clients(self, *, search: str | None, active_only: bool) -> list[Client]:
        statement = select(ClientModel)
        if active_only:
            statement = statement.where(ClientModel.active.is_(True))
        if search:
            normalized = normalize_client_code(search)
            statement = statement.where(
                or_(
                    ClientModel.client_code_normalized.contains(normalized, autoescape=True),
                    ClientModel.company_name.contains(search.strip(), autoescape=True),
                    ClientModel.city.contains(search.strip(), autoescape=True),
                    ClientModel.contact_name.contains(search.strip(), autoescape=True),
                )
            )
        statement = statement.order_by(ClientModel.company_name, ClientModel.id)
        return [client_to_entity(model) for model in self._session.scalars(statement)]

    def _flush(self) -> None:
        try:
            self._session.flush()
        except IntegrityError as error:
            if "clients.client_code_normalized" in str(error).casefold():
                raise DuplicateClientCodeError("Client code is already reserved") from None
            raise
