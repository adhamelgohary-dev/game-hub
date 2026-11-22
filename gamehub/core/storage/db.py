"""Open the local database and apply versioned schema changes."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

INITIAL_SCHEMA = (
    """
    CREATE TABLE games (
        id TEXT PRIMARY KEY NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('steam', 'epic', 'xbox', 'manual')),
        source_id TEXT NOT NULL,
        name TEXT NOT NULL,
        install_dir TEXT,
        cover_path TEXT,
        added_at INTEGER NOT NULL,
        hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
        installed INTEGER NOT NULL DEFAULT 1 CHECK (installed IN (0, 1)),
        launch_kind TEXT CHECK (launch_kind IN ('steam_uri', 'epic_uri', 'exe')),
        launch_value TEXT,
        UNIQUE (source, source_id),
        CHECK ((launch_kind IS NULL) = (launch_value IS NULL))
    ) STRICT
    """,
    """
    CREATE TABLE game_targets (
        id TEXT PRIMARY KEY NOT NULL,
        game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT,
        kind TEXT NOT NULL CHECK (kind IN ('exe_path', 'package_id')),
        match_key TEXT NOT NULL,
        origin TEXT NOT NULL CHECK (origin IN ('discovery', 'manual')),
        UNIQUE (game_id, kind, match_key)
    ) STRICT
    """,
    "CREATE INDEX game_targets_match ON game_targets (kind, match_key)",
    """
    CREATE UNIQUE INDEX game_targets_manual_owner ON game_targets (kind, match_key)
    WHERE origin = 'manual'
    """,
    """
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY NOT NULL,
        game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT,
        started_at INTEGER NOT NULL,
        ended_at INTEGER,
        last_seen_at INTEGER NOT NULL,
        duration_sec INTEGER NOT NULL DEFAULT 0 CHECK (duration_sec >= 0),
        status TEXT NOT NULL CHECK (status IN ('open', 'completed', 'interrupted')),
        CHECK ((status = 'open') = (ended_at IS NULL))
    ) STRICT
    """,
    "CREATE INDEX sessions_timeline ON sessions (game_id, started_at DESC, id)",
    "CREATE UNIQUE INDEX sessions_open_game ON sessions (game_id) WHERE status = 'open'",
)


class StorageError(RuntimeError):
    """The application cannot safely complete a local storage operation."""


class Database:
    """A database path with short-lived connections owned by the caller's thread."""

    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StorageError("Game Hub could not open its data folder.") from error

        with self._connection("rwc") as connection, self._transaction(connection):
            self._initialize(connection)

    @contextmanager
    def _connection(self, mode: str) -> Iterator[sqlite3.Connection]:
        uri = f"{self.path.as_uri()}?mode={mode}"
        try:
            with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                yield connection
        except sqlite3.Error as error:
            raise StorageError("Game Hub could not access its database.") from error

    @staticmethod
    @contextmanager
    def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
        # SQLite grants one writer at a time, including across background threads.
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise StorageError("This database requires a newer version of Game Hub.")
        if connection.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
            raise StorageError("Game Hub could not verify its database.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StorageError("Game Hub found inconsistent records in its database.")

        if version == 0:
            if connection.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone() is not None:
                raise StorageError("Game Hub found an unrecognized database schema.")
            for statement in INITIAL_SCHEMA:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Open a read-only connection and close it when finished."""
        with self._connection("ro") as connection:
            yield connection

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Commit all writes together or roll them back on any failure."""
        with self._connection("rw") as connection, self._transaction(connection):
            yield connection
