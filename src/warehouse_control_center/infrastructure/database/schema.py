"""Fail-fast verification of the deployed Alembic schema contract."""

from sqlalchemy import Engine, inspect, text

from warehouse_control_center.domain.exceptions import DatabaseSchemaError

EXPECTED_SCHEMA_REVISION = "0003_auth_hardening"
REQUIRED_SCHEMA_TABLES = frozenset(
    {
        "alembic_version",
        "audit_events",
        "couriers",
        "shipment_status_history",
        "shipments",
        "users",
    }
)


def verify_database_schema(engine: Engine) -> None:
    """Reject missing, unexpected, or structurally incomplete schemas."""
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables:
            raise DatabaseSchemaError(
                "Database schema is not initialized; run 'alembic upgrade head'"
            )

        revisions = set(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
        expected_revisions = {EXPECTED_SCHEMA_REVISION}
        if revisions != expected_revisions:
            found = ", ".join(sorted(revisions)) if revisions else "none"
            raise DatabaseSchemaError(
                f"Unsupported database revision(s): {found}; "
                f"expected {EXPECTED_SCHEMA_REVISION}. Run 'alembic upgrade head'"
            )

        missing_tables = REQUIRED_SCHEMA_TABLES - tables
        if missing_tables:
            missing = ", ".join(sorted(missing_tables))
            raise DatabaseSchemaError(
                f"Database claims revision {EXPECTED_SCHEMA_REVISION} but is missing: {missing}"
            )
