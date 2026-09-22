"""Logging setup is repeatable, rotating, UTF-8, and redacts obvious secrets."""

import logging
from dataclasses import replace
from pathlib import Path

import pytest

from warehouse_control_center.config.settings import Settings
from warehouse_control_center.infrastructure.logging.configuration import (
    configure_logging,
    shutdown_logging,
)


def test_repeated_logging_initialization_has_one_handler(tmp_path: Path) -> None:
    settings = Settings.for_testing(tmp_path)
    logger = configure_logging(settings)
    logger = configure_logging(settings)

    try:
        assert len(logger.handlers) == 1
    finally:
        shutdown_logging(logger)


def test_logging_configuration_reenables_a_disabled_logger(tmp_path: Path) -> None:
    application_logger = logging.getLogger("warehouse_control_center")
    application_logger.disabled = True

    logger = configure_logging(Settings.for_testing(tmp_path))
    try:
        logger.info("logging restored")
    finally:
        shutdown_logging(logger)

    content = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "logging restored" in content


def test_logging_writes_unicode_and_redacts_password(tmp_path: Path) -> None:
    settings = Settings.for_testing(tmp_path)
    logger = configure_logging(settings)

    try:
        logger.info("Operator čćžšđ password=never-write-this")
    finally:
        shutdown_logging(logger)

    content = (settings.log_directory / "app.log").read_text(encoding="utf-8")
    assert "čćžšđ" in content
    assert "never-write-this" not in content
    assert "password=<redacted>" in content


def test_logging_redacts_supported_sensitive_fields(tmp_path: Path) -> None:
    settings = Settings.for_testing(tmp_path)
    logger = configure_logging(settings)
    secrets = {
        "password": "password-value",
        "password_hash": "hash-value",
        "temporary_password": "temporary-value",
        "token": "token-value",
        "secret": "secret-value",
        "authorization": "Bearer authorization-value",
        "api_key": "api-key-value",
    }

    try:
        for field, value in secrets.items():
            logger.info("%s=%s", field, value)
        logger.info("payload={'password_hash': 'quoted-hash'}")
    finally:
        shutdown_logging(logger)

    content = (settings.log_directory / "app.log").read_text(encoding="utf-8")
    assert content.count("<redacted>") == len(secrets) + 1
    assert all(value not in content for value in (*secrets.values(), "quoted-hash"))


def test_exception_traceback_is_preserved_and_redacted(tmp_path: Path) -> None:
    settings = Settings.for_testing(tmp_path)
    logger = configure_logging(settings)

    try:
        try:
            raise RuntimeError("authorization=Bearer traceback-secret")
        except RuntimeError:
            logger.exception("Failure token=message-secret")
    finally:
        shutdown_logging(logger)

    content = (settings.log_directory / "app.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in content
    assert "message-secret" not in content
    assert "traceback-secret" not in content
    assert content.count("<redacted>") >= 2


@pytest.mark.parametrize(
    ("payload", "forbidden"),
    [
        ("password=LEAK-simple", "LEAK-simple"),
        ("password = LEAK value with spaces", "LEAK value with spaces"),
        ("PASSWORD=LEAK-upper", "LEAK-upper"),
        ('"password":"LEAK json value"', "LEAK json value"),
        ("'password': 'LEAK single quoted'", "LEAK single quoted"),
        ("password_hash=$argon2id$LEAK-hash", "$argon2id$LEAK-hash"),
        ("temporary_password=LEAK temporary value", "LEAK temporary value"),
        ("authorization: Bearer LEAK-token", "LEAK-token"),
        ("api_key=LEAK-key", "LEAK-key"),
        ("token=LEAK-token", "LEAK-token"),
        ("secret=LEAK-unicode-šifra", "LEAK-unicode-šifra"),
        ('password="LEAK-line1\\"quoted\\" value"', "LEAK-line1"),
        ('password="LEAK-line1\nLEAK-line2"', "LEAK-line"),
        ('password="LEAK\\backslash"', "LEAK\\backslash"),
    ],
)
def test_logging_redaction_resists_realistic_format_bypasses(
    tmp_path: Path,
    payload: str,
    forbidden: str,
) -> None:
    settings = Settings.for_testing(tmp_path)
    logger = configure_logging(settings)
    try:
        logger.info("%s", payload)
    finally:
        shutdown_logging(logger)

    content = (settings.log_directory / "app.log").read_text(encoding="utf-8")
    assert forbidden not in content
    assert "<redacted>" in content


def test_logging_rotates_at_configured_size(tmp_path: Path) -> None:
    settings = replace(Settings.for_testing(tmp_path), log_max_bytes=200, log_backup_count=2)
    logger = configure_logging(settings)

    try:
        for index in range(20):
            logger.info("rotation line %s %s", index, "x" * 40)
    finally:
        shutdown_logging(logger)

    assert (settings.log_directory / "app.log").is_file()
    assert (settings.log_directory / "app.log.1").is_file()


def test_unknown_log_level_fails_configuration(tmp_path: Path) -> None:
    settings = replace(Settings.for_testing(tmp_path), log_level="VERBOSE")

    with pytest.raises(ValueError, match="Unknown log level"):
        configure_logging(settings)
