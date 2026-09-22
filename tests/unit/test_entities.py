"""Domain entities do not expose sensitive fields through routine diagnostics."""

from warehouse_control_center.domain.entities import User
from warehouse_control_center.domain.enums import UserRole


def test_user_repr_does_not_include_password_hash() -> None:
    user = User(
        username="admin",
        password_hash=(
            "$argon2id$v=19$m=1024,t=1,p=1$uym6DDygRmSpHGPrLLvt/w$VdqOimLEoz+M7OQ4qVVsXZLSf8TC1UlslPiZi2f4K1I"
        ),
        role=UserRole.ADMIN,
    )

    rendered = repr(user)

    assert "VdqOimLEoz" not in rendered
    assert "password_hash" not in rendered
