"""Warehouse Control Center PySide6 desktop entry point."""

from __future__ import annotations

from warehouse_control_center.bootstrap import bootstrap
from warehouse_control_center.presentation.qt.application import (
    run_qt_application,
    show_startup_error,
)


def main() -> int:
    try:
        resources = bootstrap()
    except Exception as error:
        show_startup_error(error)
        return 1
    return run_qt_application(resources)


if __name__ == "__main__":
    raise SystemExit(main())
