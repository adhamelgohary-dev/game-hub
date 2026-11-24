"""Open the local database and apply versioned schema changes."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

SCHEMA_VERSION = 6

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

SCREENSHOT_SCHEMA = (
    """
    CREATE TABLE screenshots (
        id TEXT PRIMARY KEY NOT NULL,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
        path TEXT NOT NULL UNIQUE,
        captured_at INTEGER NOT NULL,
        is_last_moment INTEGER NOT NULL DEFAULT 0 CHECK (is_last_moment IN (0, 1))
    ) STRICT
    """,
    "CREATE INDEX screenshots_timeline ON screenshots (session_id, captured_at, id)",
)

NOTE_SCHEMA = (
    """
    CREATE TABLE notes (
        id TEXT PRIMARY KEY NOT NULL,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
        kind TEXT NOT NULL CHECK (kind IN ('voice', 'text')),
        path_or_text TEXT NOT NULL CHECK (length(trim(path_or_text)) > 0),
        created_at INTEGER NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('popup', 'hotkey')),
        CHECK (kind != 'text' OR source = 'popup')
    ) STRICT
    """,
    "CREATE INDEX notes_timeline ON notes (session_id, kind, created_at DESC, id)",
    "CREATE UNIQUE INDEX notes_voice_path ON notes (path_or_text) WHERE kind = 'voice'",
    """
    CREATE TABLE settings (
        key TEXT PRIMARY KEY NOT NULL,
        value TEXT NOT NULL CHECK (
            json_valid(value) AND json_type(value) NOT IN ('array', 'object')
        )
    ) STRICT
    """,
)

CONTROLS_SCHEMA = (
    """
    CREATE TABLE controls (
        id TEXT PRIMARY KEY NOT NULL,
        game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT,
        kind TEXT NOT NULL CHECK (kind IN ('image', 'text')),
        path_or_text TEXT NOT NULL CHECK (length(trim(path_or_text)) > 0),
        created_at INTEGER NOT NULL
    ) STRICT
    """,
    "CREATE INDEX controls_timeline ON controls (game_id, created_at, id)",
    "CREATE UNIQUE INDEX controls_image_path ON controls (path_or_text) WHERE kind = 'image'",
)

PROTECTION_SCHEMA = (
    """
    ALTER TABLE games
    ADD COLUMN protection_mode TEXT NOT NULL DEFAULT 'auto'
    CHECK (protection_mode IN ('auto', 'strict', 'full'))
    """,
    """
    ALTER TABLE games
    ADD COLUMN exit_after_launch INTEGER NOT NULL DEFAULT 0
    CHECK (exit_after_launch IN (0, 1))
    """,
    """
    CREATE TABLE pending_notes (
        id TEXT PRIMARY KEY NOT NULL,
        game_id TEXT NOT NULL REFERENCES games(id) ON DELETE RESTRICT,
        launched_at INTEGER NOT NULL
    ) STRICT
    """,
    "CREATE INDEX pending_notes_game ON pending_notes (launched_at DESC, id)",
    "DELETE FROM settings WHERE key = 'app.start_with_windows'",
)

V12_SCHEMA = (
    """
    CREATE TABLE games_v6 (
        id TEXT PRIMARY KEY NOT NULL,
        source TEXT NOT NULL CHECK (
            source IN (
                'steam', 'epic', 'riot', 'gog', 'ea', 'ubisoft',
                'battlenet', 'itch', 'xbox', 'folder', 'manual'
            )
        ),
        source_id TEXT NOT NULL,
        name TEXT NOT NULL,
        install_dir TEXT,
        cover_path TEXT,
        added_at INTEGER NOT NULL,
        hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
        installed INTEGER NOT NULL DEFAULT 1 CHECK (installed IN (0, 1)),
        launch_kind TEXT CHECK (
            launch_kind IN (
                'steam_uri', 'epic_uri', 'riot_client', 'ea_uri',
                'ubisoft_uri', 'gog_uri', 'battlenet_uri', 'xbox_uri', 'exe'
            )
        ),
        launch_value TEXT,
        protection_mode TEXT NOT NULL DEFAULT 'auto'
            CHECK (protection_mode IN ('auto', 'strict', 'full')),
        exit_after_launch INTEGER NOT NULL DEFAULT 0 CHECK (exit_after_launch IN (0, 1)),
        custom_cover INTEGER NOT NULL DEFAULT 0 CHECK (custom_cover IN (0, 1)),
        UNIQUE (source, source_id),
        CHECK ((launch_kind IS NULL) = (launch_value IS NULL))
    ) STRICT
    """,
    """
    INSERT INTO games_v6 (
        id, source, source_id, name, install_dir, cover_path, added_at,
        hidden, installed, launch_kind, launch_value, protection_mode,
        exit_after_launch, custom_cover
    )
    SELECT
        id, source, source_id, name, install_dir, cover_path, added_at,
        hidden, installed, launch_kind, launch_value, protection_mode,
        exit_after_launch, 0
    FROM games
    """,
    "DROP TABLE games",
    "ALTER TABLE games_v6 RENAME TO games",
    """
    CREATE TABLE scan_folders (
        path TEXT PRIMARY KEY NOT NULL,
        added_at INTEGER NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE scan_folder_choices (
        exe_path TEXT PRIMARY KEY NOT NULL,
        folder_path TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('include', 'ignore')),
        custom_name TEXT,
        updated_at INTEGER NOT NULL
    ) STRICT
    """,
    "CREATE INDEX scan_folder_choices_folder ON scan_folder_choices (folder_path)",
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

        with self._connection("rwc") as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            needs_rebuild = version < SCHEMA_VERSION
            if needs_rebuild:
                # SQLite requires PRAGMA foreign_keys = OFF outside a transaction to rebuild
                # tables referenced by foreign keys (migration v5 -> v6 expands games CHECKs).
                connection.execute("PRAGMA foreign_keys = OFF")
            try:
                with self._transaction(connection):
                    self._initialize(connection)
            finally:
                if needs_rebuild:
                    connection.execute("PRAGMA foreign_keys = ON")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise StorageError("Game Hub found inconsistent records in its database.")

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

    def _initialize(self, connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise StorageError("This database requires a newer version of Game Hub.")
        if version < 0:
            raise StorageError("Game Hub found an unrecognized database schema.")
        if connection.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
            raise StorageError("Game Hub could not verify its database.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StorageError("Game Hub found inconsistent records in its database.")

        if version == 0 and connection.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone() is not None:
            raise StorageError("Game Hub found an unrecognized database schema.")
        if 0 < version < SCHEMA_VERSION:
            self._backup(version)

        migrations = (
            INITIAL_SCHEMA,
            SCREENSHOT_SCHEMA,
            NOTE_SCHEMA,
            CONTROLS_SCHEMA,
            PROTECTION_SCHEMA,
            V12_SCHEMA,
        )
        for next_version, statements in enumerate(migrations[version:], start=version + 1):
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {next_version}")

    def _backup(self, version: int) -> None:
        # The updating connection reserves the writer lock. A separate reader
        # can take a consistent backup while that lock prevents competing writes.
        backup = self.path.with_name(f"{self.path.name}-v{version}.bak")
        try:
            with TemporaryDirectory(prefix="gamehub-upgrade-", dir=self.path.parent) as folder:
                staged = Path(folder) / backup.name
                with self.read() as source, closing(sqlite3.connect(staged)) as destination:
                    source.backup(destination)
                staged.replace(backup)
        except OSError as error:
            raise StorageError("Game Hub could not back up its database before upgrading.") from error

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Open a read-only connection and close it when finished."""
        with self._connection("ro") as connection:
            yield connection

    @contextmanager
    def read_snapshot(self) -> Iterator[sqlite3.Connection]:
        """Run multiple read queries against a single consistent SQLite snapshot."""
        with self._connection("ro") as connection:
            connection.execute("BEGIN DEFERRED")
            try:
                yield connection
            finally:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Commit all writes together or roll them back on any failure."""
        with self._connection("rw") as connection, self._transaction(connection):
            yield connection
