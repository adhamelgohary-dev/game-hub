"""Resolve, migrate, and safely relocate the local GameRewind data store."""

import json
import logging
import os
import shutil
import sqlite3
import stat
from collections.abc import Callable
from contextlib import closing
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4

from gamehub.core.library.paths import local_path
from gamehub.core.storage import controls, media, notes
from gamehub.core.storage.db import SCHEMA_VERSION, Database, StorageError

LOGGER = logging.getLogger(__name__)
BOOTSTRAP_NAME = "store-location.json"
BOOTSTRAP_VERSION = 1
MIGRATION_MARKER_NAME = ".migrated-from-gamehub"
_MAX_BOOTSTRAP_BYTES = 64 * 1024
_MAX_MEDIA_BYTES = 16 * 1024 * 1024
_MAX_MIGRATE_FILE_BYTES = 256 * 1024 * 1024


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _copy_safe_tree(source_dir: Path, target_dir: Path) -> None:
    """Recursively copy regular non-reparse files from source_dir into target_dir."""
    try:
        src_info = source_dir.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(src_info.st_mode) or _is_reparse(src_info):
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for entry in source_dir.iterdir():
        try:
            info = entry.lstat()
        except OSError:
            continue
        if _is_reparse(info):
            continue
        dest = target_dir / entry.name
        if stat.S_ISDIR(info.st_mode):
            _copy_safe_tree(entry, dest)
        elif stat.S_ISREG(info.st_mode) and info.st_size <= _MAX_MIGRATE_FILE_BYTES:
            shutil.copy2(entry, dest)


def _verify_migrated_database(db_path: Path) -> None:
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as check:
        check.execute("PRAGMA foreign_keys = ON")
        version = check.execute("PRAGMA user_version").fetchone()[0]
        if version < 1 or version > SCHEMA_VERSION:
            raise StorageError("Legacy database schema version cannot be migrated.")
        if check.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
            raise StorageError("Legacy database integrity check failed.")
        if check.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StorageError("Legacy database foreign-key check failed.")


def migrate_legacy_data_root(legacy_root: Path, new_root: Path) -> bool:
    """Automatically migrate existing %LOCALAPPDATA%\\GameHub data into %LOCALAPPDATA%\\GameRewind.

    Safe, atomic, and idempotent:
    - No-op if new_root already has gamehub.db or store-location.json.
    - Preserves custom store-location.json pointers without duplicating media.
    - Uses sqlite3.backup() + integrity checks + staging inside new_root.
    - Leaves legacy_root untouched as a non-destructive fallback.
    """
    legacy = legacy_root.absolute()
    target = new_root.absolute()
    if os.path.normcase(str(legacy)) == os.path.normcase(str(target)):
        return False

    if (target / "gamehub.db").exists() or (target / BOOTSTRAP_NAME).exists():
        return False

    try:
        legacy_info = legacy.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    if not stat.S_ISDIR(legacy_info.st_mode) or _is_reparse(legacy_info):
        return False

    validated_legacy = local_path(legacy)
    validated_target = local_path(target)
    if validated_legacy is None or validated_target is None:
        return False

    legacy_pointer = validated_legacy / BOOTSTRAP_NAME
    try:
        pointer_info = legacy_pointer.lstat()
    except FileNotFoundError:
        pointer_info = None
    except OSError:
        pointer_info = None

    if (
        pointer_info is not None
        and stat.S_ISREG(pointer_info.st_mode)
        and not _is_reparse(pointer_info)
    ):
        custom_root, err = resolve_data_root(validated_legacy)
        if err is None and os.path.normcase(str(custom_root)) != os.path.normcase(
            str(validated_legacy)
        ):
            try:
                _write_bootstrap(validated_target, custom_root)
                (validated_target / MIGRATION_MARKER_NAME).write_text(
                    f"migrated_pointer={custom_root}\n", encoding="utf-8"
                )
                return True
            except (OSError, StorageError):
                LOGGER.warning("legacy_pointer_migration_failed")
                return False

    legacy_db = validated_legacy / "gamehub.db"
    try:
        db_info = legacy_db.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    if not stat.S_ISREG(db_info.st_mode) or _is_reparse(db_info):
        return False

    try:
        validated_target.mkdir(parents=True, exist_ok=True)
        with (
            media.protect_directory(validated_target),
            TemporaryDirectory(prefix="gamerewind-migrate-", dir=validated_target) as stage_str,
        ):
            stage = Path(stage_str)
            staged_db = stage / "gamehub.db"
            with (
                closing(sqlite3.connect(f"{legacy_db.as_uri()}?mode=ro", uri=True)) as src_conn,
                closing(sqlite3.connect(staged_db)) as dst_conn,
            ):
                src_conn.backup(dst_conn)
            _verify_migrated_database(staged_db)

            for folder_name in ("media", "mods", "cache"):
                src_sub = validated_legacy / folder_name
                if src_sub.exists():
                    _copy_safe_tree(src_sub, stage / folder_name)

            override_src = validated_legacy / "protected_games_override.json"
            try:
                ov_info = override_src.lstat()
                if stat.S_ISREG(ov_info.st_mode) and not _is_reparse(ov_info):
                    shutil.copy2(override_src, stage / override_src.name)
            except OSError:
                pass

            (validated_target / "logs").mkdir(exist_ok=True)
            for folder_name in ("media", "mods", "cache"):
                staged_sub = stage / folder_name
                dest_sub = validated_target / folder_name
                if staged_sub.exists() and not dest_sub.exists():
                    shutil.move(str(staged_sub), str(dest_sub))
            staged_override = stage / "protected_games_override.json"
            dest_override = validated_target / "protected_games_override.json"
            if staged_override.exists() and not dest_override.exists():
                staged_override.replace(dest_override)
            staged_db.replace(validated_target / "gamehub.db")
            (validated_target / MIGRATION_MARKER_NAME).write_text(
                f"migrated_from={validated_legacy}\n", encoding="utf-8"
            )
            return True
    except (OSError, sqlite3.Error, StorageError):
        LOGGER.warning("legacy_data_migration_failed")
        return False


def bootstrap_path(default_root: Path) -> Path:
    return default_root.absolute() / BOOTSTRAP_NAME


def resolve_data_root(default_root: Path) -> tuple[Path, str | None]:
    """Return the active data root or an error code if a custom root is unavailable."""
    default = default_root.absolute()
    pointer = bootstrap_path(default)
    try:
        pointer_info = pointer.lstat()
    except FileNotFoundError:
        return default, None
    except OSError:
        return default, "store_location_unavailable"
    if not stat.S_ISREG(pointer_info.st_mode) or _is_reparse(pointer_info):
        return default, "store_location_invalid"

    try:
        validated_pointer = local_path(pointer)
        if validated_pointer is None:
            return default, "store_location_invalid"
        raw = media.read_file(validated_pointer, _MAX_BOOTSTRAP_BYTES)
        if raw is None:
            return default, "store_location_invalid"
        payload = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("version") != BOOTSTRAP_VERSION
            or not isinstance(payload.get("data_root"), str)
        ):
            return default, "store_location_invalid"
        custom = local_path(payload["data_root"])
        if custom is None or not custom.is_dir():
            return default, "store_location_unavailable"
        db_file = local_path(custom / "gamehub.db")
        if db_file is None:
            return default, "store_location_invalid"
        db_info = db_file.lstat()
        if not stat.S_ISREG(db_info.st_mode) or _is_reparse(db_info):
            return default, "store_location_unavailable"
        return custom, None
    except (OSError, UnicodeDecodeError, ValueError):
        return default, "store_location_unavailable"


def _write_bootstrap(default_root: Path, target_root: Path) -> None:
    default = local_path(default_root.absolute())
    if default is None:
        raise StorageError("Default data folder is unsafe.")
    target = target_root.absolute()
    pointer = bootstrap_path(default)
    default.mkdir(parents=True, exist_ok=True)
    with media.protect_directory(default):
        staged = default / f"{BOOTSTRAP_NAME}.{uuid4().hex}.tmp"
        payload = json.dumps(
            {"version": BOOTSTRAP_VERSION, "data_root": str(target)}, indent=2
        ).encode("utf-8")
        with staged.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        staged.replace(pointer)


def _referenced_media_paths(connection: sqlite3.Connection) -> list[PurePosixPath]:
    refs: list[PurePosixPath] = []
    for row in connection.execute(
        "SELECT screenshots.id, screenshots.session_id, screenshots.path, sessions.game_id "
        "FROM screenshots JOIN sessions ON sessions.id = screenshots.session_id"
    ):
        if all(media.UUID.fullmatch(row[key]) for key in ("id", "session_id", "game_id")):
            rel = PurePosixPath("media", row["game_id"], row["session_id"], f"shot_{row['id']}.webp")
            if row["path"] == rel.as_posix():
                refs.append(rel)
    for row in connection.execute(
        "SELECT notes.id, notes.session_id, notes.path_or_text, sessions.game_id "
        "FROM notes JOIN sessions ON sessions.id = notes.session_id WHERE notes.kind = 'voice'"
    ):
        if all(media.UUID.fullmatch(row[key]) for key in ("id", "session_id", "game_id")):
            rel = notes.voice_path(row["game_id"], row["session_id"], row["id"])
            if row["path_or_text"] == rel.as_posix():
                refs.append(rel)
    for row in connection.execute(
        "SELECT id, game_id, path_or_text FROM controls WHERE kind = 'image'"
    ):
        if media.UUID.fullmatch(row["id"]) and media.UUID.fullmatch(row["game_id"]):
            rel = controls.control_image_path(row["game_id"], row["id"])
            if row["path_or_text"] == rel.as_posix():
                refs.append(rel)
    return refs


def _verify_staged_database(db_path: Path) -> None:
    with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as check:
        check.execute("PRAGMA foreign_keys = ON")
        version = check.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise StorageError("Staged database schema version mismatch.")
        if check.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
            raise StorageError("Staged database integrity check failed.")
        if check.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StorageError("Staged database foreign-key check failed.")


class StoreLocation:
    """Inspect and perform verified offline relocation of GameRewind's data root."""

    def __init__(self, default_root: Path, current_root: Path, database: Database) -> None:
        self._default_root = default_root.absolute()
        self._current_root = current_root.absolute()
        self._database = database

    def current(self) -> Path:
        return self._current_root

    def default(self) -> Path:
        return self._default_root

    def move(
        self,
        destination: Path,
        *,
        before_copy: Callable[[], None] | None = None,
    ) -> tuple[bool, str | None]:
        """Copy a consistent snapshot and referenced media, verify, and update the pointer."""
        validated = local_path(destination)
        if validated is None:
            return False, "location_invalid"

        dest = validated.absolute()
        curr_norm = os.path.normcase(str(self._current_root))
        dest_norm = os.path.normcase(str(dest))
        if dest_norm == curr_norm:
            return False, "location_same"
        if dest.is_relative_to(self._current_root) or self._current_root.is_relative_to(dest):
            return False, "location_nested"

        created_dest = False
        try:
            if dest.exists():
                if not dest.is_dir():
                    return False, "location_not_directory"
                if any(dest.iterdir()):
                    return False, "location_not_empty"
            else:
                dest.mkdir(parents=True, exist_ok=True)
                created_dest = True
        except OSError:
            return False, "location_unwritable"

        if before_copy is not None:
            before_copy()

        try:
            with (
                media.protect_directory(dest),
                TemporaryDirectory(prefix="gamehub-move-", dir=dest) as stage_str,
            ):
                stage = Path(stage_str)
                staged_db = stage / "gamehub.db"
                with self._database.read_snapshot() as source:
                    with closing(sqlite3.connect(staged_db)) as target_conn:
                        source.backup(target_conn)
                    refs = _referenced_media_paths(source)

                _verify_staged_database(staged_db)

                staged_media = stage / "media"
                copied_sizes: list[tuple[PurePosixPath, int]] = []
                for rel in refs:
                    src_file = self._current_root.joinpath(*rel.parts)
                    try:
                        src_info = src_file.lstat()
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(src_info.st_mode) or _is_reparse(src_info):
                        raise StorageError("Referenced media is not a regular file.")
                    data = media.read_file(src_file, _MAX_MEDIA_BYTES)
                    if data is None:
                        raise StorageError("Referenced media could not be verified.")
                    media.stage_file(staged_media, stage.joinpath(*rel.parts), data)
                    copied_sizes.append((rel, len(data)))

                for rel, expected_size in copied_sizes:
                    staged_file = stage.joinpath(*rel.parts)
                    if not staged_file.is_file() or staged_file.stat().st_size != expected_size:
                        raise StorageError("Staged media inventory verification failed.")

                # Promote verified database and media into the fresh destination.
                (dest / "logs").mkdir(exist_ok=True)
                if staged_media.exists():
                    shutil.move(str(staged_media), str(dest / "media"))
                staged_db.replace(dest / "gamehub.db")

            _write_bootstrap(self._default_root, dest)
        except (OSError, sqlite3.Error, StorageError):
            LOGGER.warning("store_location_move_failed")
            for child in (dest / "gamehub.db", dest / "media", dest / "logs"):
                try:
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    elif child.exists():
                        child.unlink(missing_ok=True)
                except OSError:
                    pass
            if created_dest:
                try:
                    dest.rmdir()
                except OSError:
                    pass
            return False, "location_move_failed"

        return True, None
