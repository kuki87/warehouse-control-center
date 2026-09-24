# Warehouse Control Center

Warehouse Control Center is a desktop operations system for receiving, sorting, assigning,
and dispatching parcel shipments. The repository contains the first production PySide6
desktop UI plus the Phase 3A shipment-domain backend. Login, one-time first-run administrator
handling, mandatory password change, permission-based navigation, user administration, and
logout are available in the UI. Shipment operations are implemented behind application
services and the shipment UI. Courier,
reporting, audit-log, and settings workflows remain placeholders for later phases.

## Architecture

Dependencies point inward:

```text
PySide6 UI -> application services/ports -> domain
                                  ^
                                  |
                   infrastructure adapters
```

The SQLAlchemy models stay in the infrastructure layer. Application-facing repositories
exchange domain entities. Repositories may flush but never commit; the Unit of Work owns
the transaction boundary.

## Shipment-domain behavior

The canonical shipment number is normalized with Unicode NFKC, whitespace
removal, and case folding to uppercase for indexed equality. Punctuation is preserved:
`ABC-123` and `ABC123` are intentionally different identifiers. Creation starts
a shipment in `RECEIVED`; status history begins with the first real transition rather than a
synthetic `NULL -> RECEIVED` record.

Normal status changes follow the centralized workflow policy. Invalid transitions require
the override permission and a recorded reason. Reporting a problem is the only normal path
into `PROBLEM`, and a shipment may have only one unresolved problem. A second unresolved
problem is rejected. Resolving a problem returns to its previous status by default, or to an
explicit recovery status accepted by the workflow policy. Shipment mutations, history,
problem records, and audit events share one Unit-of-Work transaction.

Shipment queries use bounded database pagination, allow-listed sorting, and indexed exact
shipment-number lookup. Archived shipments are excluded unless explicitly requested. The
SQLite deployment remains a single-workstation design; optimistic version checks prevent a
stale editor from silently overwriting a newer shipment update.

## Requirements

- Windows, macOS, or Linux
- Python 3.13 or newer
- SQLite supplied by Python

SQLite V1 is intended for a single workstation. **Do not place the SQLite database on a
shared network drive.** Later multi-user operation will require PostgreSQL and a server
boundary.

## Environment setup

PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

POSIX shells:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The lock snapshot can be installed before the editable project when exact reproduction is
required:

```powershell
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

The lock is an exact Windows/Python 3.13 environment snapshot. To regenerate it after an
intentional `pyproject.toml` dependency change, create a clean Python 3.13 environment,
install `.[dev]`, run `pip check`, and then write the snapshot:

```powershell
'# Generated from the Python 3.13 Phase 1 environment.' | Set-Content requirements.lock
'# pyproject.toml remains the dependency source of truth.' | Add-Content requirements.lock
python -m pip freeze --exclude-editable | Add-Content requirements.lock
```

Review the resulting diff and verify a fresh install before accepting it.

## Initialize or upgrade the database

Apply migrations before the first bootstrap and after installing a version with new
migrations:

```powershell
alembic upgrade head
alembic current
```

For a wheel installation where `alembic.ini` is not present, run the packaged manual
migration command instead:

```powershell
warehouse-control-center-db
```

The application never migrates automatically. It refuses startup when the schema is
missing, incomplete, outdated, or at an unexpected revision.

## Run the desktop application

```powershell
python -m warehouse_control_center.main
```

The bootstrap resolves runtime paths, initializes logging, verifies SQLite and the schema,
and assembles authentication and user-management services before opening the PySide6 login
flow. If the database has no users, it creates `admin` with a cryptographically random
temporary password and displays it once in a dedicated dialog. The value is consumed by
that dialog, is never logged or written to settings, and must be changed before the account
can use the application. Later runs never regenerate it.

Potentially blocking service calls run through Qt workers. Each service call obtains its own
Unit of Work and SQLAlchemy session in the worker thread; GUI updates return to the Qt event
thread. A busy SQLite database produces a retryable message instead of freezing the window.

Phase 2 sessions are immutable in-memory values and are internal capabilities; they must not
be constructed from deserialized or otherwise untrusted input. There is no general session
revocation registry, but every high-risk `MANAGE_USERS` operation rechecks the acting user's
current database role, active state, archive state, and credential version. Password changes
and administrator resets increment that version, immediately invalidating older privileged
session capabilities. Other future application services must choose an equivalent freshness
check where stale authorization would be dangerous.

Password changes require the new password to differ from the current password. Unicode,
spaces, leading/trailing spaces, and control characters are otherwise preserved as supplied;
passwords are never silently normalized or truncated.

Temporary credentials from first run, user creation, and password reset are shown once and
cleared from their dialog when it closes. The Copy action intentionally places the value on
the operating-system clipboard, so administrators should paste it only into an appropriate
secure channel and clear the clipboard afterward.

## Runtime data

Writable state uses `platformdirs` and lives outside the source/installation directory.
The root contains:

```text
data/warehouse.db
logs/app.log
backups/
exports/
```

For controlled development or smoke tests, set `WCC_ENVIRONMENT=development` and
`WCC_RUNTIME_ROOT` to an isolated directory. Production configuration rejects writable
paths inside the repository, installation tree, or temporary directory. Integration tests
always use pytest temporary directories and refuse paths that overlap production data.

The default warehouse/display timezone is the IANA zone `Europe/Sarajevo`. Persistent
timestamps are stored and restored as UTC.

Create future revisions only after reviewing generated operations:

```powershell
alembic revision --autogenerate -m "description"
```

Persistent schemas must be managed through Alembic; `create_all()` is not the production
schema-management mechanism.

## Quality commands

```powershell
pytest
ruff check .
ruff format --check .
mypy src
alembic check
```

## Project structure

```text
src/warehouse_control_center/
  application/ports/       repository, security, clock, and Unit-of-Work interfaces
  application/services/    authentication, user-management, and shipment use cases
  config/                  typed settings and platform runtime paths
  domain/                  entities, enums, normalization, exceptions
  infrastructure/database/ SQLAlchemy models, adapters, Unit of Work
  infrastructure/logging/  rotating, idempotent logging
  presentation/qt/         PySide6 windows, pages, dialogs, widgets, and workers
  bootstrap.py             resource and first-admin initialization
  main.py                  PySide6 desktop entry point
src/warehouse_control_center/migrations/  packaged, versioned schema migrations
tests/                     unit, integration, and headless Qt safety tests
scripts/                   future maintenance scripts
packaging/                 future release configuration
```

## Environment variables

- `WCC_APPLICATION_NAME`
- `WCC_ENVIRONMENT` (`development`, `test`, or `production`)
- `WCC_RUNTIME_ROOT`
- `WCC_DATABASE_PATH`
- `WCC_LOG_DIRECTORY`
- `WCC_BACKUP_DIRECTORY`
- `WCC_EXPORT_DIRECTORY`
- `WCC_TIMEZONE`
- `WCC_SQLITE_TIMEOUT`
- `WCC_LOG_LEVEL`
- `WCC_LOG_MAX_BYTES`
- `WCC_LOG_BACKUP_COUNT`

## Current UI boundary

Only user administration is functional. Dashboard, Shipments, Scan, Couriers, Reports,
Audit Log, and Settings say "Coming in a later phase" and do not simulate unavailable
business behavior.
