"""The Unit of Work is the sole transaction and Session lifecycle owner."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from tests.fixtures.database import make_user
from warehouse_control_center.domain.exceptions import DuplicateUserError
from warehouse_control_center.infrastructure.database.engine import SessionFactory
from warehouse_control_center.infrastructure.database.models import UserModel
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


def _user_count(session_factory: SessionFactory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(UserModel)) or 0


def test_successful_commit_persists_data(session_factory: SessionFactory) -> None:
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.users.add(make_user())
        unit_of_work.commit()

    assert _user_count(session_factory) == 1


def test_explicit_rollback_removes_pending_changes(session_factory: SessionFactory) -> None:
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.users.add(make_user())
        unit_of_work.rollback()

    assert _user_count(session_factory) == 0


def test_uncommitted_context_is_rolled_back(session_factory: SessionFactory) -> None:
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.users.add(make_user())

    assert _user_count(session_factory) == 0


def test_exception_in_context_rolls_back(session_factory: SessionFactory) -> None:
    with pytest.raises(RuntimeError, match="forced failure"):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.users.add(make_user())
            raise RuntimeError("forced failure")

    assert _user_count(session_factory) == 0


def test_context_closes_session_permanently(session_factory: SessionFactory) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(session_factory)
    with unit_of_work:
        captured_session = unit_of_work.session

    assert unit_of_work.closed
    with pytest.raises(InvalidRequestError):
        captured_session.execute(select(UserModel))


def test_repository_captured_from_closed_uow_cannot_access_session(
    session_factory: SessionFactory,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(session_factory)
    with unit_of_work:
        captured_repository = unit_of_work.users

    with pytest.raises(InvalidRequestError):
        captured_repository.get_by_id(1)


def test_nested_entry_is_rejected_and_outer_transaction_rolls_back(
    session_factory: SessionFactory,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(session_factory)

    with pytest.raises(RuntimeError, match="more than once"):
        with unit_of_work:
            unit_of_work.users.add(make_user())
            with unit_of_work:
                pass

    assert _user_count(session_factory) == 0
    assert unit_of_work.closed


def test_integrity_error_during_flush_rolls_back_and_new_uow_recovers(
    session_factory: SessionFactory,
) -> None:
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.users.add(make_user("existing"))
        unit_of_work.commit()

    with pytest.raises(DuplicateUserError):
        with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
            unit_of_work.users.add(make_user("existing"))

    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.users.add(make_user("recovered"))
        unit_of_work.commit()

    assert _user_count(session_factory) == 2


def test_integrity_error_during_commit_can_be_rolled_back_and_session_reused(
    session_factory: SessionFactory,
) -> None:
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.users.add(make_user("existing"))
        unit_of_work.commit()

    duplicate = make_user("existing")
    with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.session.add(
            UserModel(
                username=duplicate.username,
                username_normalized=duplicate.username_normalized,
                password_hash=duplicate.password_hash,
                role=duplicate.role,
            )
        )
        with pytest.raises(IntegrityError):
            unit_of_work.commit()
        unit_of_work.rollback()
        assert unit_of_work.users.get_by_normalized_username("existing") is not None
        unit_of_work.users.add(make_user("same-session-recovery"))
        unit_of_work.commit()

    assert _user_count(session_factory) == 2


def test_uow_instance_can_be_reused_only_after_prior_exit(session_factory: SessionFactory) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(session_factory)
    with unit_of_work:
        unit_of_work.users.add(make_user("first"))
        unit_of_work.commit()
    with unit_of_work:
        unit_of_work.users.add(make_user("second"))
        unit_of_work.commit()

    assert _user_count(session_factory) == 2
