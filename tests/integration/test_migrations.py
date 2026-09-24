"""Alembic creates and safely rechecks the complete Phase 1 schema."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from tests.fixtures.database import upgrade_to_head
from warehouse_control_center.config.settings import Settings
from warehouse_control_center.infrastructure.database.base import Base
from warehouse_control_center.infrastructure.database.migration_runner import alembic_config
from warehouse_control_center.infrastructure.database.schema import EXPECTED_SCHEMA_REVISION

EXPECTED_TABLES = {
    "alembic_version",
    "users",
    "couriers",
    "clients",
    "shipments",
    "shipment_number_sequences",
    "shipment_problems",
    "shipment_status_history",
    "shipment_weight_checks",
    "audit_events",
}

VALID_HASH = (
    "$argon2id$v=19$m=1024,t=1,p=1$uym6DDygRmSpHGPrLLvt/w$"
    "VdqOimLEoz+M7OQ4qVVsXZLSf8TC1UlslPiZi2f4K1I"
)


def test_upgrade_empty_database_to_head(test_settings: Settings) -> None:
    assert not test_settings.database_path.exists()
    test_settings.runtime_paths.create()

    upgrade_to_head(test_settings)

    engine = create_engine(test_settings.database_url)
    try:
        assert EXPECTED_TABLES == set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_already_current_database_is_safe(test_settings: Settings) -> None:
    test_settings.runtime_paths.create()
    upgrade_to_head(test_settings)
    upgrade_to_head(test_settings)

    engine = create_engine(test_settings.database_url)
    try:
        assert EXPECTED_TABLES == set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_phase1_database_with_referenced_user_to_head(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0001_phase1")

    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) VALUES "
                    "('operator', 'operator', "
                    ":password_hash, 'ADMIN') "
                    "RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, "
                    "barcode_normalized, recipient_name, recipient_address, recipient_city, "
                    "recipient_phone, sender_name, status, received_at, created_by, version) "
                    "VALUES ('T', 'T', 'T', 'T', 'Name', 'Address', 'City', '123', "
                    "'Sender', 'RECEIVED', CURRENT_TIMESTAMP, :user_id, 1)"
                ),
                {"user_id": user_id},
            )
    finally:
        engine.dispose()

    upgrade_to_head(test_settings)

    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM users")) == 1
            assert connection.scalar(text("SELECT COUNT(*) FROM shipments")) == 1
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                EXPECTED_SCHEMA_REVISION
            )
    finally:
        engine.dispose()


def test_upgrade_populated_authentication_head_to_shipment_domain(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0003_auth_hardening")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, "
                    "'WAREHOUSE_OPERATOR') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            shipment_id = connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, "
                    "barcode_normalized, recipient_name, recipient_address, recipient_city, "
                    "recipient_phone, sender_name, status, received_at, created_by, version) "
                    "VALUES ('TRK-1', 'TRK-1', 'TRK-1', 'TRK-1', 'Željko', "
                    "'Ćirila i Metodija 10', 'Banja Luka', '+387 65 123 456', "
                    "'Đorđe', 'SORTING', CURRENT_TIMESTAMP, :user_id, 1) RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipment_status_history "
                    "(shipment_id, old_status, new_status, changed_by, reason) "
                    "VALUES (:shipment_id, 'RECEIVED', 'SORTING', :user_id, 'sorted')"
                ),
                {"shipment_id": shipment_id, "user_id": user_id},
            )
    finally:
        engine.dispose()

    upgrade_to_head(test_settings)
    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM shipments")) == 1
            assert connection.scalar(text("SELECT COUNT(*) FROM shipment_status_history")) == 1
            assert connection.scalar(text("SELECT COUNT(*) FROM shipment_problems")) == 0
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                EXPECTED_SCHEMA_REVISION
            )
    finally:
        engine.dispose()


def test_shipment_domain_migration_rejects_corrupt_legacy_history(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0003_auth_hardening")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            shipment_id = connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, "
                    "barcode_normalized, recipient_name, recipient_address, recipient_city, "
                    "recipient_phone, sender_name, status, received_at, created_by, version) "
                    "VALUES ('TRK', 'TRK', 'BAR', 'BAR', 'Name', 'Address', 'City', "
                    "'123', 'Sender', 'RECEIVED', CURRENT_TIMESTAMP, :user_id, 1) RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipment_status_history "
                    "(shipment_id, old_status, new_status, changed_by) "
                    "VALUES (:shipment_id, 'RECEIVED', 'RECEIVED', :user_id)"
                ),
                {"shipment_id": shipment_id, "user_id": user_id},
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="shipment-domain constraints"):
        upgrade_to_head(test_settings)
    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0003_auth_hardening"
            )
            assert connection.scalar(text("SELECT COUNT(*) FROM shipment_status_history")) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("tracking_number", "tracking_number_normalized", "recipient_phone"),
    [
        ("", "", "123"),
        ("   ", "   ", "123"),
        ("ABC-123", "WRONG", "123"),
        ("TRK", "TRK", "CALL-ME"),
    ],
)
def test_shipment_domain_migration_rejects_invalid_populated_rows(
    test_settings: Settings,
    tracking_number: str,
    tracking_number_normalized: str,
    recipient_phone: str,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0003_auth_hardening")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, "
                    "barcode_normalized, recipient_name, recipient_address, recipient_city, "
                    "recipient_phone, sender_name, status, received_at, created_by, version) "
                    "VALUES (:tracking_number, :tracking_number_normalized, 'BAR', 'BAR', "
                    "'Name', 'Address', 'City', :recipient_phone, 'Sender', 'RECEIVED', "
                    "CURRENT_TIMESTAMP, :user_id, 1)"
                ),
                {
                    "user_id": user_id,
                    "tracking_number": tracking_number,
                    "tracking_number_normalized": tracking_number_normalized,
                    "recipient_phone": recipient_phone,
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="shipment-domain constraints"):
        upgrade_to_head(test_settings)
    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0003_auth_hardening"
            )
            assert connection.scalar(text("SELECT tracking_number FROM shipments")) == (
                tracking_number
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("password_hash", "expected_revision"),
    [
        ("", "0001_phase1"),
        ("plaintext", "0001_phase1"),
        (
            "$argon2i$v=19$m=1024,t=1,p=1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtl",
            "0001_phase1",
        ),
        (
            "$argon2d$v=19$m=1024,t=1,p=1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtl",
            "0001_phase1",
        ),
        ("$argon2id$garbage", "0002_authentication"),
        (
            "$argon2id$v=19$m=999999999,t=1,p=1$c2FsdHNhbHQ$ZmFrZWhhc2hmYWtl",
            "0002_authentication",
        ),
    ],
)
def test_authentication_hardening_rejects_unsupported_stored_credentials(
    test_settings: Settings,
    password_hash: str,
    expected_revision: str,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0001_phase1")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('legacy', 'legacy', :password_hash, 'WAREHOUSE_OPERATOR')"
                ),
                {"password_hash": password_hash},
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        with pytest.raises(RuntimeError, match="authentication constraints|stored credential"):
            command.upgrade(config, "head")

    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT password_hash FROM users")) == password_hash
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                expected_revision
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("normalized", "must_change", "active"),
    [(" legacy ", 0, 1), ("legacy", 2, 1), ("legacy", 0, 7)],
)
def test_authentication_hardening_rejects_invalid_legacy_user_state(
    test_settings: Settings,
    normalized: str,
    must_change: int,
    active: int,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0001_phase1")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role, "
                    "must_change_password, active) "
                    "VALUES ('legacy', :normalized, :password_hash, 'ADMIN', "
                    ":must_change, :active)"
                ),
                {
                    "normalized": normalized,
                    "password_hash": VALID_HASH,
                    "must_change": must_change,
                    "active": active,
                },
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        with pytest.raises(RuntimeError, match="state invariants"):
            command.upgrade(config, "head")

    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0002_authentication"
            )
            assert connection.scalar(text("SELECT username_normalized FROM users")) == normalized
    finally:
        engine.dispose()


def test_phase1_users_of_all_roles_and_archive_states_upgrade_without_loss(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0001_phase1")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            for index, (role, active, archived_at) in enumerate(
                [
                    ("ADMIN", 1, None),
                    ("WAREHOUSE_OPERATOR", 0, None),
                    ("SUPERVISOR", 0, "2026-01-01 00:00:00"),
                ],
                start=1,
            ):
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(username, username_normalized, password_hash, role, active, archived_at) "
                        "VALUES (:username, :username, :password_hash, :role, :active, "
                        ":archived_at)"
                    ),
                    {
                        "username": f"user-{index}",
                        "password_hash": VALID_HASH,
                        "role": role,
                        "active": active,
                        "archived_at": archived_at,
                    },
                )
    finally:
        engine.dispose()

    upgrade_to_head(test_settings)
    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT role, active, archived_at FROM users ORDER BY id")
            ).all() == [
                ("ADMIN", 1, None),
                ("WAREHOUSE_OPERATOR", 0, None),
                ("SUPERVISOR", 0, "2026-01-01 00:00:00"),
            ]
    finally:
        engine.dispose()


def test_hardening_downgrade_and_reupgrade_preserve_user_data(
    test_settings: Settings,
) -> None:
    upgrade_to_head(test_settings)
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('admin', 'admin', :password_hash, 'ADMIN')"
                ),
                {"password_hash": VALID_HASH},
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        command.downgrade(config, "0002_authentication")
        command.upgrade(config, "head")

    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT username, password_hash, role FROM users")
            ).one() == ("admin", VALID_HASH, "ADMIN")
    finally:
        engine.dispose()


def test_required_indexes_exist(engine: object) -> None:
    database_inspector = inspect(engine)
    shipment_indexes = {index["name"] for index in database_inspector.get_indexes("shipments")}
    assert {
        "ix_shipments_status",
        "ix_shipments_courier_id_status",
        "ix_shipments_received_at",
        "ix_shipments_status_received_at",
        "ix_shipments_recipient_city",
        "ix_shipments_updated_at",
    } <= shipment_indexes
    history_indexes = {
        index["name"] for index in database_inspector.get_indexes("shipment_status_history")
    }
    assert "ix_shipment_status_history_shipment_timestamp" in history_indexes
    problem_indexes = {
        index["name"] for index in database_inspector.get_indexes("shipment_problems")
    }
    assert {
        "ix_shipment_problems_shipment_reported",
        "uq_shipment_problems_one_open",
    } <= problem_indexes
    audit_indexes = {index["name"] for index in database_inspector.get_indexes("audit_events")}
    assert {
        "ix_audit_events_timestamp",
        "ix_audit_events_entity_type_entity_id",
    } <= audit_indexes


def test_orm_metadata_has_no_migration_drift(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        assert compare_metadata(context, Base.metadata) == []


def test_runtime_expected_revision_matches_alembic_head(test_settings: Settings) -> None:
    with alembic_config(test_settings) as config:
        script = ScriptDirectory.from_config(config)

        assert script.get_heads() == [EXPECTED_SCHEMA_REVISION]


@pytest.mark.parametrize(
    ("identifiers", "expected_next"),
    [
        ([], 1),
        (["ABC123", "X018123456"], 1),
        (["E000000001"], 2),
        (["E000000001", "E000000009", "E000000004"], 10),
        (["E123456789"], 123_456_790),
        (["E999999999"], 1_000_000_000),
        (["e000000010", "E0000010", "E00000001A"], 1),
    ],
)
def test_automatic_numbering_migration_initializes_from_exact_legacy_identifiers(
    test_settings: Settings,
    identifiers: list[str],
    expected_next: int,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0004_shipments_domain")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            for index, identifier in enumerate(identifiers, start=1):
                connection.execute(
                    text(
                        "INSERT INTO shipments "
                        "(tracking_number, tracking_number_normalized, barcode, "
                        "barcode_normalized, recipient_name, recipient_address, "
                        "recipient_city, recipient_phone, sender_name, status, received_at, "
                        "created_by, version) VALUES (:tracking, :tracking, :barcode, "
                        ":barcode, 'Name', 'Address', 'City', '123', 'Sender', "
                        "'RECEIVED', CURRENT_TIMESTAMP, :user_id, 1)"
                    ),
                    {
                        "tracking": identifier,
                        "barcode": f"LEGACY-BAR-{index}",
                        "user_id": user_id,
                    },
                )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        command.upgrade(config, "0005_automatic_shipment_numbering")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT next_value FROM shipment_number_sequences "
                        "WHERE name = 'shipment_number'"
                    )
                )
                == expected_next
            )
            assert (
                list(
                    connection.execute(
                        text("SELECT tracking_number FROM shipments ORDER BY id")
                    ).scalars()
                )
                == identifiers
            )
    finally:
        engine.dispose()


def test_automatic_numbering_migration_considers_compatible_legacy_barcodes(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0004_shipments_domain")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, "
                    "barcode_normalized, recipient_name, recipient_address, recipient_city, "
                    "recipient_phone, sender_name, status, received_at, created_by, version) "
                    "VALUES ('LEGACY-1', 'LEGACY-1', 'E000000050', 'E000000050', "
                    "'Name', 'Address', 'City', '123', 'Sender', 'RECEIVED', "
                    "CURRENT_TIMESTAMP, :user_id, 1)"
                ),
                {"user_id": user_id},
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        command.upgrade(config, "0005_automatic_shipment_numbering")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT next_value FROM shipment_number_sequences")) == 51
            assert connection.execute(
                text("SELECT tracking_number, barcode FROM shipments")
            ).one() == ("LEGACY-1", "E000000050")
    finally:
        engine.dispose()


def test_automatic_numbering_downgrade_and_reupgrade_recomputes_safely(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0005_automatic_shipment_numbering")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, "
                    "barcode_normalized, recipient_name, recipient_address, recipient_city, "
                    "recipient_phone, sender_name, status, received_at, created_by, version) "
                    "VALUES ('E000000007', 'E000000007', 'E000000007', 'E000000007', "
                    "'Name', 'Address', 'City', '123', 'Sender', 'RECEIVED', "
                    "CURRENT_TIMESTAMP, :user_id, 1)"
                ),
                {"user_id": user_id},
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        command.downgrade(config, "0004_shipments_domain")
        command.upgrade(config, "head")

    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT next_value FROM shipment_number_sequences")) == 8
            assert connection.scalar(text("SELECT tracking_number FROM shipments")) == (
                "E000000007"
            )
    finally:
        engine.dispose()


def test_unified_identifier_migration_preserves_matching_and_archived_shipments(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0005_automatic_shipment_numbering")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, "
                    "barcode_normalized, recipient_name, recipient_address, recipient_city, "
                    "recipient_phone, sender_name, status, received_at, created_by, "
                    "archived_at, version) VALUES ('LEGACY-42', 'LEGACY-42', "
                    "'LEGACY-42', 'LEGACY-42', 'Name', 'Address', 'City', '123', "
                    "'Sender', 'RECEIVED', CURRENT_TIMESTAMP, :user_id, "
                    "'2026-01-02 03:04:05', 1)"
                ),
                {"user_id": user_id},
            )
            connection.execute(
                text(
                    "UPDATE shipment_number_sequences SET next_value = 42 "
                    "WHERE name = 'shipment_number'"
                )
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        command.upgrade(config, "head")

    engine = create_engine(test_settings.database_url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("shipments")}
        assert "tracking_number" in columns
        assert "tracking_number_normalized" in columns
        assert "barcode" not in columns
        assert "barcode_normalized" not in columns
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT tracking_number, tracking_number_normalized, archived_at FROM shipments"
                )
            ).one() == ("LEGACY-42", "LEGACY-42", "2026-01-02 03:04:05")
            assert connection.scalar(text("SELECT next_value FROM shipment_number_sequences")) == 42
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("tracking", "tracking_normalized", "barcode", "barcode_normalized"),
    [
        ("LEGACY-1", "LEGACY-1", "LEGACY-2", "LEGACY-2"),
        ("LEGACY-1", "LEGACY-1", "LEGACY-1", "DIFFERENT"),
    ],
)
def test_unified_identifier_migration_rejects_inconsistent_duplicates(
    test_settings: Settings,
    tracking: str,
    tracking_normalized: str,
    barcode: str,
    barcode_normalized: str,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0005_automatic_shipment_numbering")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, barcode, "
                    "barcode_normalized, recipient_name, recipient_address, recipient_city, "
                    "recipient_phone, sender_name, status, received_at, created_by, version) "
                    "VALUES (:tracking, :tracking_normalized, :barcode, :barcode_normalized, "
                    "'Name', 'Address', 'City', '123', 'Sender', 'RECEIVED', "
                    "CURRENT_TIMESTAMP, :user_id, 1)"
                ),
                {
                    "tracking": tracking,
                    "tracking_normalized": tracking_normalized,
                    "barcode": barcode,
                    "barcode_normalized": barcode_normalized,
                    "user_id": user_id,
                },
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        with pytest.raises(RuntimeError, match="identifiers.*disagree"):
            command.upgrade(config, "head")

    engine = create_engine(test_settings.database_url)
    try:
        assert inspect(engine).has_table("shipments")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0005_automatic_shipment_numbering"
            )
            assert connection.execute(
                text("SELECT tracking_number, barcode FROM shipments")
            ).one() == (tracking, barcode)
    finally:
        engine.dispose()


def test_unified_identifier_downgrade_and_reupgrade_are_reversible(
    test_settings: Settings,
) -> None:
    upgrade_to_head(test_settings)
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, recipient_name, "
                    "recipient_address, recipient_city, recipient_phone, sender_name, status, "
                    "received_at, created_by, version) VALUES ('E000000123', 'E000000123', "
                    "'Name', 'Address', 'City', '123', 'Sender', 'RECEIVED', "
                    "CURRENT_TIMESTAMP, :user_id, 1)"
                ),
                {"user_id": user_id},
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        command.downgrade(config, "0005_automatic_shipment_numbering")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT tracking_number, barcode FROM shipments")
            ).one() == ("E000000123", "E000000123")
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        command.upgrade(config, "head")
    engine = create_engine(test_settings.database_url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("shipments")}
        assert "barcode" not in columns
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT tracking_number FROM shipments")) == (
                "E000000123"
            )
    finally:
        engine.dispose()


def test_exact_identifier_lookups_use_unique_indexes(engine: Engine) -> None:
    queries = {
        "users": "username_normalized",
        "couriers": "courier_code_normalized",
        "shipments": "tracking_number_normalized",
    }
    tables = {
        "users": "users",
        "couriers": "couriers",
        "shipments": "shipments",
    }

    with engine.connect() as connection:
        for label, column in queries.items():
            rows = connection.exec_driver_sql(
                f"EXPLAIN QUERY PLAN SELECT id FROM {tables[label]} WHERE {column} = ?",
                ("probe",),
            ).all()
            plan = " ".join(str(value) for row in rows for value in row).upper()
            assert "USING" in plan and "INDEX" in plan, (label, plan)


def test_phase4a_upgrade_preserves_populated_0006_shipments(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0006_unify_shipment_identifier")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, recipient_name, "
                    "recipient_address, recipient_city, recipient_phone, sender_name, status, "
                    "received_at, created_by, archived_at, version) "
                    "VALUES ('E000000321', 'E000000321', 'Name', 'Address', 'City', '123', "
                    "'Legacy sender', 'RECEIVED', CURRENT_TIMESTAMP, :user_id, "
                    "'2026-01-02 03:04:05', 1)"
                ),
                {"user_id": user_id},
            )
    finally:
        engine.dispose()

    upgrade_to_head(test_settings)

    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT tracking_number, sender_name, sender_client_id, package_count, "
                    "length_mm, width_mm, height_mm, declared_weight_g, archived_at "
                    "FROM shipments"
                )
            ).one()
            assert row == (
                "E000000321",
                "Legacy sender",
                None,
                1,
                None,
                None,
                None,
                None,
                "2026-01-02 03:04:05",
            )
            assert connection.scalar(text("SELECT COUNT(*) FROM clients")) == 0
            assert connection.scalar(text("SELECT COUNT(*) FROM shipment_weight_checks")) == 0
    finally:
        engine.dispose()


def test_phase4a_downgrade_and_reupgrade_preserve_legacy_shipment(
    test_settings: Settings,
) -> None:
    test_settings.runtime_paths.create()
    with alembic_config(test_settings) as config:
        command.upgrade(config, "0006_unify_shipment_identifier")
    engine = create_engine(test_settings.database_url)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users "
                    "(username, username_normalized, password_hash, role) "
                    "VALUES ('operator', 'operator', :password_hash, 'ADMIN') RETURNING id"
                ),
                {"password_hash": VALID_HASH},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shipments "
                    "(tracking_number, tracking_number_normalized, recipient_name, "
                    "recipient_address, recipient_city, recipient_phone, sender_name, status, "
                    "received_at, created_by, version) "
                    "VALUES ('E000000654', 'E000000654', 'Name', 'Address', 'City', '123', "
                    "'Legacy sender', 'RECEIVED', CURRENT_TIMESTAMP, :user_id, 1)"
                ),
                {"user_id": user_id},
            )
    finally:
        engine.dispose()

    with alembic_config(test_settings) as config:
        command.upgrade(config, "head")
        command.downgrade(config, "0006_unify_shipment_identifier")
        command.upgrade(config, "head")

    engine = create_engine(test_settings.database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT tracking_number, sender_name, package_count FROM shipments")
            ).one() == ("E000000654", "Legacy sender", 1)
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                EXPECTED_SCHEMA_REVISION
            )
    finally:
        engine.dispose()
