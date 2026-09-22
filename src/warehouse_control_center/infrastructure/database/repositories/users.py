"""User persistence adapter."""

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from warehouse_control_center.domain.entities import User
from warehouse_control_center.domain.enums import UserRole
from warehouse_control_center.domain.exceptions import DatabaseBusyError, DuplicateUserError
from warehouse_control_center.domain.normalization import normalize_username
from warehouse_control_center.infrastructure.database.models import UserModel
from warehouse_control_center.infrastructure.database.repositories.mapping import (
    user_to_entity,
    user_to_model,
)


class SqlAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> User:
        model = user_to_model(user)
        self._session.add(model)
        try:
            self._session.flush()
        except IntegrityError:
            raise DuplicateUserError("Username is already reserved") from None
        return user_to_entity(model)

    def save(self, user: User) -> User:
        if user.id is None:
            raise ValueError("Cannot save a user without an id")
        model = self._session.get(UserModel, user.id)
        if model is None:
            raise ValueError(f"User {user.id} does not exist")
        model.username = user.username
        model.username_normalized = user.username_normalized
        model.password_hash = user.password_hash
        model.role = user.role
        model.must_change_password = user.must_change_password
        model.active = user.active
        model.failed_login_attempts = user.failed_login_attempts
        model.credential_version = user.credential_version
        model.locked_until = user.locked_until
        model.archived_at = user.archived_at
        try:
            self._session.flush()
        except IntegrityError:
            raise DuplicateUserError("Username is already reserved") from None
        return user_to_entity(model)

    def get_by_id(self, user_id: int) -> User | None:
        model = self._session.get(UserModel, user_id)
        return user_to_entity(model) if model is not None else None

    def get_by_normalized_username(self, username: str) -> User | None:
        statement = select(UserModel).where(
            UserModel.username_normalized == normalize_username(username)
        )
        model = self._session.scalar(statement)
        return user_to_entity(model) if model is not None else None

    def list_users(
        self,
        *,
        search: str | None = None,
        include_archived: bool = False,
    ) -> list[User]:
        statement = select(UserModel)
        if not include_archived:
            statement = statement.where(UserModel.archived_at.is_(None))
        if search:
            normalized_search = normalize_username(search)
            statement = statement.where(
                UserModel.username_normalized.contains(normalized_search, autoescape=True)
            )
        statement = statement.order_by(UserModel.username_normalized)
        return [user_to_entity(model) for model in self._session.scalars(statement)]

    def count_users(self) -> int:
        return self._session.scalar(select(func.count()).select_from(UserModel)) or 0

    def count_active_admins(self) -> int:
        statement = (
            select(func.count())
            .select_from(UserModel)
            .where(
                UserModel.role == UserRole.ADMIN,
                UserModel.active.is_(True),
                UserModel.archived_at.is_(None),
            )
        )
        return self._session.scalar(statement) or 0

    def lock_for_administration(self) -> None:
        if self._session.in_transaction():
            raise RuntimeError("Administration lock must be acquired before database access")
        try:
            self._session.execute(text("BEGIN IMMEDIATE"))
        except OperationalError as error:
            if "database is locked" in str(error).casefold():
                raise DatabaseBusyError("Database is busy; retry the operation") from None
            raise
