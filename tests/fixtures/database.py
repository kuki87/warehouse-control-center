"""Database fixtures and factories shared by integration tests."""

from __future__ import annotations

from warehouse_control_center.config.settings import Settings
from warehouse_control_center.domain.entities import Courier, Shipment, User
from warehouse_control_center.domain.enums import UserRole
from warehouse_control_center.infrastructure.database.migration_runner import (
    upgrade_to_head as run_upgrade_to_head,
)


def upgrade_to_head(settings: Settings) -> None:
    run_upgrade_to_head(settings)


def make_user(username: str = "operator") -> User:
    return User(
        username=username,
        password_hash="$argon2id$v=19$m=1024,t=1,p=1$uym6DDygRmSpHGPrLLvt/w$VdqOimLEoz+M7OQ4qVVsXZLSf8TC1UlslPiZi2f4K1I",
        role=UserRole.ADMIN,
    )


def make_courier(code: str = "1878") -> Courier:
    return Courier(courier_code=code, first_name="Milan", last_name="Kovačević")


def make_shipment(
    created_by: int,
    *,
    shipment_number: str = "SHP-100",
) -> Shipment:
    return Shipment(
        shipment_number=shipment_number,
        recipient_name="Željko Šarić",
        recipient_address="Ćirila i Metodija 10",
        recipient_city="Banja Luka",
        recipient_phone="+387 65 123 456",
        sender_name="Đorđe Čavić",
        created_by=created_by,
    )
