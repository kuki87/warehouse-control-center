"""Centralized logging configuration."""

from warehouse_control_center.infrastructure.logging.configuration import (
    configure_logging,
    shutdown_logging,
)

__all__ = ["configure_logging", "shutdown_logging"]
