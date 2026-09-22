"""Operating-system appropriate runtime path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """All writable runtime locations used by the application."""

    root: Path
    data: Path
    logs: Path
    backups: Path
    exports: Path

    @property
    def database(self) -> Path:
        """Return the default SQLite database location."""
        return self.data / "warehouse.db"

    def create(self) -> None:
        """Create runtime directories idempotently."""
        for directory in (self.root, self.data, self.logs, self.backups, self.exports):
            directory.mkdir(parents=True, exist_ok=True)


def resolve_runtime_paths(
    application_name: str = "Warehouse Control Center",
    *,
    root_override: Path | None = None,
) -> RuntimePaths:
    """Resolve runtime paths, optionally rooted in a caller-controlled directory."""
    root = (
        root_override.expanduser().resolve()
        if root_override is not None
        else Path(user_data_path(application_name, appauthor=False, roaming=False)).resolve()
    )
    return RuntimePaths(
        root=root,
        data=root / "data",
        logs=root / "logs",
        backups=root / "backups",
        exports=root / "exports",
    )
