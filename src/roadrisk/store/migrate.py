"""Migrations: numbered SQL files, applied in order, recorded once.

**Why not Alembic.** Autogeneration wants ORM models to diff against, and there are none
here — the data model is six tables of scalars around a `jsonb` payload, and an ORM over
that would be indirection bought with nothing. What is left of Alembic once
autogeneration is gone is a version table and an ordering, which is this file. The SQL
stays readable, which matters for a schema whose whole job is to be reviewed.

**Every migration is recorded with the hash of the file that produced it.** Applying
`0001` from one checkout and finding a different `0001` in the next is not a conflict any
`IF NOT EXISTS` can save you from, and a database that has silently diverged from the
migration that claims to describe it is worse than one that has not been migrated at all.
So the mismatch is refused, loudly, naming the file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roadrisk.store.base import StoreError

MIGRATIONS = Path(__file__).parent / "migrations"

VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     text PRIMARY KEY,
    sha256      text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationMismatch(StoreError):
    """An applied migration's file has changed since it ran."""


@dataclass(frozen=True)
class Migration:
    """One numbered SQL file."""

    version: str
    path: Path
    sql: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover(directory: Path | None = None) -> list[Migration]:
    """Every migration on disk, in version order.

    Ordering is by filename, which is why they are zero-padded. `10` sorting before `9`
    is a class of bug worth spending two characters to make impossible.
    """
    root = directory or MIGRATIONS
    found = []
    for path in sorted(root.glob("*.sql")):
        version = path.stem.split("_", 1)[0]
        found.append(
            Migration(
                version=version,
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )
    return found


def applied(connection: Any) -> dict[str, str]:
    """Versions already in the database, mapped to the hash that was applied."""
    with connection.cursor() as cursor:
        cursor.execute(VERSION_TABLE)
        cursor.execute("SELECT version, sha256 FROM schema_migration")
        return {row[0]: row[1] for row in cursor.fetchall()}


def migrate(connection: Any, directory: Path | None = None) -> list[str]:
    """Bring a database up to date. Returns the versions applied by this call.

    Idempotent: running it against a current database applies nothing and returns an
    empty list.

    Raises:
        MigrationMismatch: A migration already applied has a different hash on disk.
    """
    already = applied(connection)
    ran: list[str] = []

    for migration in discover(directory):
        recorded = already.get(migration.version)
        if recorded is not None:
            if recorded != migration.sha256:
                raise MigrationMismatch(
                    f"Migration {migration.version} was applied from a different file "
                    f"than {migration.path.name} now holds. The database and this "
                    "checkout disagree about what the schema is, and applying it again "
                    "would not reconcile them. Recorded "
                    f"{recorded[:12]}, on disk {migration.sha256[:12]}."
                )
            continue

        with connection.cursor() as cursor:
            cursor.execute(migration.sql)
            cursor.execute(
                "INSERT INTO schema_migration (version, sha256) VALUES (%s, %s)",
                (migration.version, migration.sha256),
            )
        ran.append(migration.version)

    connection.commit()
    return ran
