"""Non-GUI application bootstrap and first-run administrator initialization."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Engine, text

from warehouse_control_center.application.dto import TemporaryCredential
from warehouse_control_center.application.ports.unit_of_work import UnitOfWork
from warehouse_control_center.application.services import (
    AuthenticationService,
    ClientService,
    FirstRunAdministratorService,
    ShipmentService,
    ShipmentSmsService,
    UserService,
)
from warehouse_control_center.config.settings import Settings
from warehouse_control_center.infrastructure.clock import UtcClock
from warehouse_control_center.infrastructure.database.engine import (
    create_session_factory,
    create_sqlite_engine,
)
from warehouse_control_center.infrastructure.database.schema import verify_database_schema
from warehouse_control_center.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from warehouse_control_center.infrastructure.logging.configuration import (
    configure_logging,
    shutdown_logging,
)
from warehouse_control_center.infrastructure.security import (
    Argon2PasswordHasher,
    SecureTemporaryPasswordGenerator,
)


@dataclass(slots=True)
class ApplicationResources:
    settings: Settings
    logger: logging.Logger
    engine: Engine
    authentication: AuthenticationService
    users: UserService
    clients: ClientService
    shipments: ShipmentService
    shipment_sms: ShipmentSmsService
    initial_administrator: TemporaryCredential | None

    def shutdown(self) -> None:
        self.logger.info("Warehouse Control Center shutdown complete")
        self.engine.dispose()
        shutdown_logging(self.logger)


def bootstrap(settings: Settings | None = None) -> ApplicationResources:
    """Verify infrastructure and assemble application services for the desktop UI."""
    active_settings = settings or Settings.load()
    active_settings.runtime_paths.create()
    logger = configure_logging(active_settings)
    logger.info(
        "Warehouse Control Center startup environment=%s",
        active_settings.environment,
    )
    engine: Engine | None = None
    try:
        engine = create_sqlite_engine(active_settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Database connectivity verified")
        verify_database_schema(engine)
        logger.info("Database schema verified")
        session_factory = create_session_factory(engine)

        def uow_factory() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(session_factory)

        password_hasher = Argon2PasswordHasher()
        password_generator = SecureTemporaryPasswordGenerator()
        clock = UtcClock()
        first_run = FirstRunAdministratorService(
            uow_factory,
            password_hasher,
            password_generator,
            clock,
        )
        initial_administrator = first_run.initialize()
        authentication = AuthenticationService(uow_factory, password_hasher, clock)
        users = UserService(
            uow_factory,
            password_hasher,
            password_generator,
            clock,
        )
        shipments = ShipmentService(uow_factory, clock)
        shipment_sms = ShipmentSmsService(uow_factory, clock)
        clients = ClientService(uow_factory, clock)
        if initial_administrator is not None:
            logger.info("First-run administrator initialized; temporary credential not logged")
        return ApplicationResources(
            settings=active_settings,
            logger=logger,
            engine=engine,
            authentication=authentication,
            users=users,
            shipments=shipments,
            shipment_sms=shipment_sms,
            clients=clients,
            initial_administrator=initial_administrator,
        )
    except Exception:
        logger.exception("Application startup failed")
        if engine is not None:
            engine.dispose()
        shutdown_logging(logger)
        raise
