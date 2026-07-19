"""SQLite access for the Frosthaven Arbiter.

`Database` is the single seam other modules use to obtain connections.
It owns migration application, pragmas, and connection lifecycle. Callers
use plain SQL through `sqlite3.Connection`; there is no ORM layer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

_MIGRATIONS_PACKAGE = "frosthaven_arbiter.migrations"


def _migration_files() -> list[tuple[int, str]]:
    package = resources.files(_MIGRATIONS_PACKAGE)
    migrations: list[tuple[int, str]] = []
    for entry in package.iterdir():
        if entry.name.endswith(".sql"):
            version = int(entry.name.split("_", 1)[0])
            migrations.append((version, entry.name))
    return sorted(migrations)


class Database:
    """Owns one SQLite file: pragmas, migrations, and connections."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @property
    def path(self) -> Path:
        return self._path

    def _connect_raw(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self) -> None:
        conn = self._connect_raw()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            package = resources.files(_MIGRATIONS_PACKAGE)
            for version, filename in _migration_files():
                if version in applied:
                    continue
                sql = (package / filename).read_text(encoding="utf-8")
                # sqlite3.executescript issues an implicit COMMIT of any pending
                # transaction before running, so migrations cannot be wrapped in
                # an explicit BEGIN/COMMIT here. Each DDL statement is atomic.
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
                    (version,),
                )
        finally:
            conn.close()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect_raw()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect_raw()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
