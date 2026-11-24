"""Crash-safe backup, deploy, conflict resolution, and restore engine for Translations & Mods."""

from __future__ import annotations

import hashlib
import json
import logging
import ntpath
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from threading import Lock
from time import monotonic
from uuid import uuid4

from gamehub.core.library.models import GameSummary
from gamehub.core.library.paths import local_path
from gamehub.core.protection.catalog import ProtectedGamesCatalog
from gamehub.core.protection.guard import (
    ProcessScanner,
    ServiceProbe,
    ToolhelpProcessScanner,
    WindowsServiceProbe,
)
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.modules.mods.manifest import extract_verified_package, normalize_rel_path
from gamehub.modules.mods.models import (
    GameModsState,
    GameRunningModError,
    ModConflict,
    ModFilesystemError,
    ModItem,
    ProtectedGameModError,
)
from gamehub.modules.mods.repository import ModBackupRecord, ModsRepository

LOGGER = logging.getLogger(__name__)
_MAX_SCAN_DEPTH = 4
_MAX_SCANNED_ENTRIES = 2000


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(128 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy_file(
    src: Path, dst: Path, *, expected_sha256: str | None = None
) -> str:
    """Atomically copy src -> dst, verifying SHA-256 BEFORE replacing dst."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.{uuid4().hex}.grtmp"
    digest = hashlib.sha256()
    try:
        with src.open("rb") as reader, tmp.open("xb") as writer:
            while True:
                chunk = reader.read(128 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        actual = digest.hexdigest()
        if expected_sha256 is not None and actual != expected_sha256:
            tmp.unlink(missing_ok=True)
            raise ModFilesystemError(f"File checksum mismatch before writing {dst.name!r}.")
        tmp.replace(dst)
        return actual
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _ensure_no_reparse_in_chain(root: Path, target: Path) -> None:
    """Verify root and every existing path component between root and target is not a reparse point."""
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise ModFilesystemError("Folder is not accessible.") from exc
    if not stat.S_ISDIR(root_info.st_mode) or _is_reparse(root_info):
        raise ModFilesystemError("Folder cannot be a symlink or junction.")

    rel_parts = target.relative_to(root).parts
    current = root
    for part in rel_parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ModFilesystemError("Could not inspect folder path safely.") from exc
        if _is_reparse(info):
            raise ModFilesystemError("Symlinks and junctions inside managed folders are not allowed.")


def _cleanup_empty_dirs(root: Path, leaf_dir: Path) -> None:
    current = leaf_dir
    resolved_root = root.resolve()
    while current != root:
        try:
            if not current.resolve().is_relative_to(resolved_root):
                break
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _scan_dir_exes(root: Path, *, max_depth: int = _MAX_SCAN_DEPTH) -> set[str]:
    """Bounded, symlink-safe scan for .exe basenames inside a game's install_dir."""
    found: set[str] = set()
    validated = local_path(root)
    if validated is None or not validated.is_dir():
        return found
    scanned = 0
    stack: list[tuple[Path, int]] = [(validated, 0)]
    while stack and scanned < _MAX_SCANNED_ENTRIES:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    scanned += 1
                    if scanned > _MAX_SCANNED_ENTRIES:
                        break
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if _is_reparse(info):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        if depth < max_depth:
                            stack.append((Path(entry.path), depth + 1))
                    elif stat.S_ISREG(info.st_mode) and entry.name.lower().endswith(".exe"):
                        found.add(ntpath.normcase(entry.name))
        except OSError:
            continue
    return found


def _paths_overlap(a: Path, b: Path) -> bool:
    try:
        ra = Path(os.path.normcase(str(a.resolve())))
        rb = Path(os.path.normcase(str(b.resolve())))
        return ra == rb or ra.is_relative_to(rb) or rb.is_relative_to(ra)
    except OSError:
        return False


class ModsEngine:
    """Safe, crash-recoverable manager for single-player translations and mods."""

    def __init__(
        self,
        database: Database,
        data_root: Path,
        library: LibraryRepository,
        catalog: ProtectedGamesCatalog,
        *,
        is_any_game_running: Callable[[], bool] | None = None,
        process_scanner: ProcessScanner | None = None,
        service_probe: ServiceProbe | None = None,
    ) -> None:
        self._repo = ModsRepository(database)
        self._data_root = data_root.absolute()
        self._mods_root = self._data_root / "mods"
        self._library = library
        self._catalog = catalog
        self._is_any_game_running = is_any_game_running or (lambda: False)
        self._scanner = process_scanner if process_scanner is not None else ToolhelpProcessScanner()
        self._service_probe = service_probe if service_probe is not None else WindowsServiceProbe()
        self._op_lock = Lock()
        self._protected_cache: dict[
            tuple[str, str, str, str, str, str, int], tuple[float, bool, str]
        ] = {}

    def invalidate_protection_cache(self) -> None:
        self._protected_cache.clear()

    def is_game_protected(
        self, game: GameSummary, *, use_cache: bool = True
    ) -> tuple[bool, str]:
        """Return (True, reason) for ANY protected/online/strict game (even if user overrode mode).

        Checks:
        1. Catalog match on source/source_id + registered target basenames + normalized title.
        2. Deep bounded scan of game.install_dir for ANY protected exe basename.
        3. Path overlap with any protected game's install_dir in the library.
        4. Explicit strict protection mode.
        """
        cache_key: tuple[str, str, str, str, str, str, int] | None = None
        now = monotonic()
        if use_cache:
            dir_str = str(game.install_dir) if game.install_dir is not None else ""
            dir_mtime = 0
            if game.install_dir is not None:
                safe_dir = local_path(game.install_dir)
                if safe_dir is None:
                    dir_mtime = -2
                else:
                    try:
                        info = safe_dir.lstat()
                        dir_mtime = -2 if _is_reparse(info) else info.st_mtime_ns
                    except OSError:
                        dir_mtime = -1
            cache_key = (
                game.id,
                game.source.value,
                game.source_id,
                game.name,
                game.protection_mode,
                dir_str,
                dir_mtime,
            )
            cached = self._protected_cache.get(cache_key)
            if cached is not None and (now - cached[0]) <= 15.0:
                return cached[1], cached[2]

        result = self._compute_game_protected(game)
        if cache_key is not None:
            if len(self._protected_cache) > 512:
                self._protected_cache.clear()
            self._protected_cache[cache_key] = (now, result[0], result[1])
        return result

    def _compute_game_protected(self, game: GameSummary) -> tuple[bool, str]:
        basenames_by_game = self._library.list_target_basenames()
        exes = set(basenames_by_game.get(game.id, ()))
        if game.install_dir is not None:
            exes.update(_scan_dir_exes(game.install_dir))
        matched = self._catalog.match_game(
            game.source, game.source_id, exes, game_name=game.name
        )
        if matched is not None:
            return True, matched.anti_cheat
        if game.protection_mode == "strict":
            return True, "Strict mode"
        if (
            self._catalog.effective_mode(
                game.protection_mode, game.source, game.source_id, exes, game_name=game.name
            )
            == "strict"
        ):
            return True, "Protected game"

        if game.install_dir is not None:
            for other in self._library.list_games():
                if other.id == game.id or other.install_dir is None:
                    continue
                other_exes = basenames_by_game.get(other.id, ())
                other_match = self._catalog.match_game(
                    other.source, other.source_id, other_exes, game_name=other.name
                )
                if (other_match is not None or other.protection_mode == "strict") and _paths_overlap(
                    game.install_dir, other.install_dir
                ):
                    return True, other_match.anti_cheat if other_match is not None else "Strict mode"
        return False, ""

    def _require_game(self, game_id: str) -> GameSummary:
        game = self._library.get_game(game_id)
        if game is None:
            raise ModFilesystemError("Game was not found in your library.")
        return game

    def _assert_not_protected(self, game: GameSummary) -> None:
        # Always perform a fresh uncached disk/catalog verification before any mutation.
        protected, _reason = self.is_game_protected(game, use_cache=False)
        if protected:
            raise ProtectedGameModError(
                "Mods and translations are turned off for online games to protect your account."
            )

    def _collect_known_game_exes(self, target_game: GameSummary | None = None) -> set[str]:
        exes: set[str] = set(self._catalog.all_exe_names())
        for names in self._library.list_target_basenames().values():
            for name in names:
                norm = ntpath.normcase(ntpath.basename(name))
                if norm:
                    exes.add(norm)
        if target_game is not None and target_game.install_dir is not None:
            exes.update(_scan_dir_exes(target_game.install_dir))
        return exes

    def _assert_no_game_running(self, target_game: GameSummary | None = None) -> None:
        if self._is_any_game_running():
            raise GameRunningModError(
                "Close your running game before changing translations or mods."
            )
        try:
            running = self._scanner.list_processes()
        except Exception as exc:
            raise GameRunningModError(
                "Could not verify that no game is running. Please try again."
            ) from exc
        known_exes = self._collect_known_game_exes(target_game)
        for _pid, raw_name in running:
            base = ntpath.normcase(ntpath.basename(raw_name))
            if base in known_exes:
                raise GameRunningModError(
                    "Close your running game before changing translations or mods."
                )
        try:
            active_svcs = self._service_probe.running_services(self._catalog.anti_cheat_services)
        except Exception as exc:
            raise GameRunningModError(
                "Could not verify anti-cheat service status. Please try again."
            ) from exc
        if active_svcs:
            raise GameRunningModError(
                "Close your running game before changing translations or mods."
            )

    def _validated_install_dir(self, game: GameSummary) -> Path:
        if game.install_dir is None:
            raise ModFilesystemError("This game does not have a local install folder configured.")
        validated = local_path(game.install_dir)
        if validated is None or not validated.is_dir():
            raise ModFilesystemError("This game's install folder is not accessible.")
        info = validated.lstat()
        if _is_reparse(info):
            raise ModFilesystemError("Game install folder cannot be a symlink or junction.")
        if _paths_overlap(validated, self._data_root):
            raise ModFilesystemError("Game install folder cannot overlap GameRewind's data folder.")
        return validated

    def _safe_game_target(self, install_dir: Path, rel_path: str) -> Path:
        norm = normalize_rel_path(rel_path)
        candidate = install_dir.joinpath(*PurePosixPath(norm).parts)
        validated = local_path(candidate)
        if validated is None:
            raise ModFilesystemError(f"Unsafe target path rejected: {rel_path!r}")
        if not validated.resolve().is_relative_to(install_dir.resolve()):
            raise ModFilesystemError(f"Target path escaped game folder: {rel_path!r}")
        _ensure_no_reparse_in_chain(install_dir, validated)
        return validated

    def _resolve_mods_subpath(
        self, stored_path: str, expected_prefix: str, *, require_child: bool = False
    ) -> Path:
        """Resolve a DB-stored package or backup path strictly under data_root/mods/<prefix>."""
        base = (self._mods_root / expected_prefix).absolute()
        base.mkdir(parents=True, exist_ok=True)
        raw = Path(stored_path)
        if raw.is_absolute():
            candidate = raw.absolute()
        else:
            norm = normalize_rel_path(stored_path)
            candidate = self._mods_root.joinpath(*PurePosixPath(norm).parts)
        validated = local_path(candidate)
        if validated is None or not validated.resolve().is_relative_to(base.resolve()):
            raise ModFilesystemError("Stored mod path escaped managed mods directory.")
        if require_child and validated.resolve() == base.resolve():
            raise ModFilesystemError("Stored mod path cannot equal the container root directory.")
        _ensure_no_reparse_in_chain(self._mods_root, validated)
        return validated

    def _package_storage_rel(self, game_id: str, item_id: str) -> str:
        return f"packages/{game_id}/{item_id}"

    def _backup_rel(self, game_id: str, rel_path: str) -> str:
        norm = normalize_rel_path(rel_path)
        return f"backups/{game_id}/{norm}"

    def _backup_file_path(self, game_id: str, rel_path: str) -> tuple[str, Path]:
        rel = self._backup_rel(game_id, rel_path)
        path = self._resolve_mods_subpath(rel, f"backups/{game_id}")
        return rel, path

    @staticmethod
    def _casefold_map(records: dict[str, object]) -> dict[str, tuple[str, object]]:
        return {k.casefold(): (k, v) for k, v in records.items()}

    def _compute_conflicts(
        self, items: tuple[ModItem, ...], choices: dict[str, str]
    ) -> tuple[ModConflict, ...]:
        enabled_items = [item for item in items if item.enabled]
        choices_ci = {k.casefold(): v for k, v in choices.items()}
        by_path_ci: dict[str, tuple[str, list[ModItem]]] = {}
        for item in enabled_items:
            for f in item.manifest.files:
                key = f.dest.casefold()
                if key not in by_path_ci:
                    by_path_ci[key] = (f.dest, [])
                by_path_ci[key][1].append(item)

        pair_paths: dict[tuple[str, str], list[str]] = {}
        by_id = {item.id: item for item in enabled_items}
        for _key, (display_path, owners) in sorted(by_path_ci.items()):
            if len(owners) < 2:
                continue
            for idx in range(len(owners)):
                for jdx in range(idx + 1, len(owners)):
                    a, b = owners[idx], owners[jdx]
                    if b.kind == "translation" and a.kind != "translation":
                        a, b = b, a
                    pair_paths.setdefault((a.id, b.id), []).append(display_path)

        conflicts: list[ModConflict] = []
        for (a_id, b_id), paths in pair_paths.items():
            a = by_id[a_id]
            b = by_id[b_id]
            winner = choices_ci.get(paths[0].casefold())
            if winner not in {a_id, b_id}:
                winner = a_id
            conflicts.append(
                ModConflict(
                    item_a=a,
                    item_b=b,
                    rel_paths=tuple(sorted(paths)),
                    winner_item_id=winner,
                )
            )
        return tuple(conflicts)

    def _desired_file_map(
        self, items: tuple[ModItem, ...], choices: dict[str, str]
    ) -> dict[str, tuple[str, ModItem, str]]:
        """Map casefold(rel_path) -> (canonical_dest, winning ModItem, expected_sha256)."""
        enabled = [item for item in items if item.enabled]
        choices_ci = {k.casefold(): v for k, v in choices.items()}
        owners_by_key: dict[str, list[tuple[str, ModItem, str]]] = {}
        for item in enabled:
            for f in item.manifest.files:
                owners_by_key.setdefault(f.dest.casefold(), []).append((f.dest, item, f.sha256))

        desired: dict[str, tuple[str, ModItem, str]] = {}
        for key, candidates in owners_by_key.items():
            if len(candidates) == 1:
                desired[key] = candidates[0]
                continue
            chosen_id = choices_ci.get(key)
            matched = next((c for c in candidates if c[1].id == chosen_id), None)
            if matched is not None:
                desired[key] = matched
            else:
                translations = [c for c in candidates if c[1].kind == "translation"]
                desired[key] = translations[0] if translations else candidates[0]
        return desired

    def get_state(self, game_id: str) -> GameModsState:
        game = self._require_game(game_id)
        protected, reason = self.is_game_protected(game)
        install_ok = False
        if not protected and game.install_dir is not None:
            validated = local_path(game.install_dir)
            install_ok = (
                validated is not None
                and validated.is_dir()
                and not _paths_overlap(validated, self._data_root)
            )
        items = self._repo.list_items(game_id)
        choices = self._repo.list_conflict_choices(game_id)
        backups = self._repo.list_backups(game_id)
        deployed = self._repo.list_deployed(game_id)
        conflicts = () if protected else self._compute_conflicts(items, choices)
        return GameModsState(
            game_id=game.id,
            game_name=game.name,
            protected=protected,
            protected_reason=reason,
            install_dir_available=install_ok,
            backed_up_count=len(backups),
            has_mod_changes=bool(deployed) or any(item.enabled for item in items),
            items=items,
            conflicts=conflicts,
        )

    def import_zip(self, game_id: str, zip_path: Path, *, enable: bool = True) -> ModItem:
        with self._op_lock:
            game = self._require_game(game_id)
            self._assert_not_protected(game)
            self._assert_no_game_running(game)
            self._validated_install_dir(game)

            temp_id = uuid4().hex
            staging_dir = self._mods_root / "staging" / temp_id
            old_backup_dir: Path | None = None
            prev_item: ModItem | None = None
            upserted_id: str | None = None
            try:
                manifest = extract_verified_package(zip_path, staging_dir)
                existing = self._repo.get_item_by_package_id(game_id, manifest.id)
                prev_item = existing
                final_id = existing.id if existing is not None else temp_id
                rel_storage = self._package_storage_rel(game_id, final_id)
                final_dir = self._resolve_mods_subpath(
                    rel_storage, f"packages/{game_id}", require_child=True
                )
                final_dir.parent.mkdir(parents=True, exist_ok=True)
                if final_dir.exists():
                    old_backup_dir = final_dir.with_name(f"{final_id}.prev.{uuid4().hex}")
                    final_dir.replace(old_backup_dir)
                shutil.move(str(staging_dir), str(final_dir))
                item = self._repo.upsert_item(
                    item_id=final_id,
                    game_id=game_id,
                    manifest=manifest,
                    storage_dir=rel_storage,
                    enabled=enable,
                )
                upserted_id = item.id
                self._reconcile_game(game, operation=f"import:{item.package_id}")
                if old_backup_dir is not None:
                    shutil.rmtree(old_backup_dir, ignore_errors=True)
                return item
            except BaseException:
                shutil.rmtree(staging_dir, ignore_errors=True)
                if old_backup_dir is not None and old_backup_dir.exists():
                    target_restore = self._mods_root / "packages" / game_id / final_id
                    if target_restore.exists():
                        shutil.rmtree(target_restore, ignore_errors=True)
                    old_backup_dir.replace(target_restore)
                # Keep SQLite in sync with rolled-back disk package on failed import/re-import.
                if upserted_id is not None:
                    try:
                        if prev_item is not None:
                            self._repo.upsert_item(
                                item_id=prev_item.id,
                                game_id=game_id,
                                manifest=prev_item.manifest,
                                storage_dir=prev_item.storage_dir,
                                enabled=prev_item.enabled,
                            )
                        else:
                            self._repo.delete_item(game_id, upserted_id)
                    except Exception:  # noqa: BLE001
                        LOGGER.warning("mods_import_db_rollback_failed game_id=%s", game_id)
                raise

    def set_enabled(self, game_id: str, item_id: str, enabled: bool) -> GameModsState:
        with self._op_lock:
            game = self._require_game(game_id)
            self._assert_not_protected(game)
            self._assert_no_game_running(game)
            self._validated_install_dir(game)
            item = self._repo.get_item(game_id, item_id)
            if item is None:
                raise ModFilesystemError("Selected translation or mod was not found.")
            self._repo.set_enabled(game_id, item_id, enabled)
            self._reconcile_game(game, operation=f"toggle:{item_id}:{int(enabled)}")
            return self.get_state(game_id)

    def choose_conflict_winner(
        self,
        game_id: str,
        item_a_id: str,
        item_b_id: str,
        winner_item_id: str,
    ) -> GameModsState:
        with self._op_lock:
            game = self._require_game(game_id)
            self._assert_not_protected(game)
            self._assert_no_game_running(game)
            self._validated_install_dir(game)
            if winner_item_id not in {item_a_id, item_b_id}:
                raise ModFilesystemError("Invalid conflict winner choice.")
            items = self._repo.list_items(game_id)
            by_id = {i.id: i for i in items}
            if item_a_id not in by_id or item_b_id not in by_id:
                raise ModFilesystemError("Conflicting item was not found.")
            paths_a = {f.dest.casefold() for f in by_id[item_a_id].manifest.files}
            paths_b = {f.dest.casefold() for f in by_id[item_b_id].manifest.files}
            shared_keys = tuple(sorted(paths_a & paths_b))
            if shared_keys:
                self._repo.set_conflict_winner(game_id, shared_keys, winner_item_id)
                self._reconcile_game(game, operation=f"conflict:{winner_item_id}")
            return self.get_state(game_id)

    def remove_item(self, game_id: str, item_id: str) -> GameModsState:
        with self._op_lock:
            game = self._require_game(game_id)
            self._assert_not_protected(game)
            self._assert_no_game_running(game)
            self._validated_install_dir(game)
            item = self._repo.get_item(game_id, item_id)
            if item is None:
                return self.get_state(game_id)
            self._repo.set_enabled(game_id, item_id, False)
            self._reconcile_game(game, operation=f"remove:{item_id}")
            self._repo.delete_item(game_id, item_id)
            try:
                pkg_dir = self._resolve_mods_subpath(
                    item.storage_dir, f"packages/{game_id}", require_child=True
                )
                if pkg_dir.exists():
                    shutil.rmtree(pkg_dir, ignore_errors=True)
            except ModFilesystemError:
                LOGGER.warning("mods_skip_unsafe_package_dir game_id=%s", game_id)
            return self.get_state(game_id)

    def restore_original(self, game_id: str) -> GameModsState:
        with self._op_lock:
            game = self._require_game(game_id)
            self._assert_not_protected(game)
            self._assert_no_game_running(game)
            self._validated_install_dir(game)
            self._repo.disable_all(game_id)
            self._reconcile_game(game, operation="restore_original")
            return self.get_state(game_id)

    def _cleanup_staging_and_temps(self, install_dir: Path | None = None) -> None:
        staging_root = self._mods_root / "staging"
        if staging_root.is_dir():
            shutil.rmtree(staging_root, ignore_errors=True)
        if install_dir is not None and install_dir.is_dir():
            stack: list[Path] = [install_dir]
            while stack:
                current = stack.pop()
                try:
                    cur_info = current.lstat()
                    if _is_reparse(cur_info):
                        continue
                    with os.scandir(current) as it:
                        for entry in it:
                            try:
                                info = entry.stat(follow_symlinks=False)
                            except OSError:
                                continue
                            if _is_reparse(info):
                                continue
                            if stat.S_ISDIR(info.st_mode):
                                stack.append(Path(entry.path))
                            elif stat.S_ISREG(info.st_mode) and entry.name.endswith(".grtmp"):
                                try:
                                    Path(entry.path).unlink(missing_ok=True)
                                except OSError:
                                    pass
                except OSError:
                    continue

    def recover_incomplete(self) -> int:
        """Recover any interrupted journaled operations cleanly on startup."""
        with self._op_lock:
            self._cleanup_staging_and_temps()
            incomplete = self._repo.list_incomplete_journals()
            if not incomplete:
                return 0
            by_game: dict[str, list] = {}
            for entry in incomplete:
                by_game.setdefault(entry.game_id, []).append(entry)

            recovered = 0
            for game_id, entries in by_game.items():
                game = self._library.get_game(game_id)
                if game is None:
                    for entry in entries:
                        self._repo.finish_journal(entry.id, "rolled_back")
                    continue
                protected, _ = self.is_game_protected(game, use_cache=False)
                if protected:
                    for entry in entries:
                        self._repo.finish_journal(entry.id, "rolled_back")
                    continue
                extra_restore_paths: set[str] = set()
                for entry in entries:
                    try:
                        payload = json.loads(entry.payload_json)
                        for p in payload.get("desired_paths", ()):
                            if isinstance(p, str):
                                extra_restore_paths.add(p)
                    except ValueError:
                        pass
                try:
                    self._assert_no_game_running(game)
                    install_dir = self._validated_install_dir(game)
                    self._cleanup_staging_and_temps(install_dir)
                    self._reconcile_game(
                        game,
                        operation=f"recover:{entries[-1].id}",
                        force_restore_candidates=extra_restore_paths,
                    )
                    for entry in entries:
                        self._repo.finish_journal(entry.id, "rolled_back")
                    recovered += 1
                except (GameRunningModError, ModFilesystemError, OSError):
                    LOGGER.warning("mods_journal_recovery_deferred game_id=%s", game_id)
            return recovered

    def _resolve_backup_source(self, game_id: str, backup: ModBackupRecord) -> Path:
        if not backup.backup_path:
            raise ModFilesystemError(f"Original backup path is missing for {backup.rel_path!r}.")
        return self._resolve_mods_subpath(backup.backup_path, f"backups/{game_id}")

    def _reconcile_game(
        self,
        game: GameSummary,
        *,
        operation: str,
        force_restore_candidates: set[str] | None = None,
    ) -> None:
        install_dir = self._validated_install_dir(game)
        items = self._repo.list_items(game.id)
        choices = self._repo.list_conflict_choices(game.id)
        desired = self._desired_file_map(items, choices)
        deployed_raw = self._repo.list_deployed(game.id)
        backups_raw = self._repo.list_backups(game.id)

        deployed_ci = {k.casefold(): (k, v) for k, v in deployed_raw.items()}
        backups_ci = {k.casefold(): (k, v) for k, v in backups_raw.items()}

        journal_id = uuid4().hex
        self._repo.begin_journal(
            journal_id,
            game.id,
            operation,
            {
                "desired_paths": sorted(v[0] for v in desired.values()),
                "deployed_paths": sorted(deployed_raw.keys()),
            },
        )

        # 1. Back up every target file we haven't backed up yet BEFORE touching install_dir.
        for key in sorted(desired.keys()):
            if key in backups_ci:
                continue
            self._assert_no_game_running(game)
            rel_path, _winner, _sha = desired[key]
            target = self._safe_game_target(install_dir, rel_path)
            if target.exists():
                info = target.lstat()
                if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
                    raise ModFilesystemError(f"Target file is not a regular file: {rel_path!r}")
                backup_rel, backup_dst = self._backup_file_path(game.id, rel_path)
                orig_sha = _atomic_copy_file(target, backup_dst)
                self._repo.record_backup(
                    game_id=game.id,
                    rel_path=rel_path,
                    existed=True,
                    backup_path=backup_rel,
                    orig_sha256=orig_sha,
                )
            else:
                self._repo.record_backup(
                    game_id=game.id,
                    rel_path=rel_path,
                    existed=False,
                    backup_path=None,
                    orig_sha256=None,
                )
            backups_raw = self._repo.list_backups(game.id)
            backups_ci = {k.casefold(): (k, v) for k, v in backups_raw.items()}

        # 2. Restore/remove files no longer in desired (including crash leftovers & restore_original).
        restore_keys: set[str] = set(deployed_ci.keys()) - set(desired.keys())
        if force_restore_candidates:
            for p in force_restore_candidates:
                if p.casefold() not in desired:
                    restore_keys.add(p.casefold())
        if not desired:
            restore_keys |= set(backups_ci.keys())

        for key in sorted(restore_keys):
            self._assert_no_game_running(game)
            dep_entry = deployed_ci.get(key)
            bak_entry = backups_ci.get(key)
            rel_path = (
                bak_entry[0]
                if bak_entry is not None
                else (dep_entry[0] if dep_entry is not None else key)
            )
            target = self._safe_game_target(install_dir, rel_path)
            backup = bak_entry[1] if bak_entry is not None else None
            if backup is not None and backup.existed and backup.backup_path:
                backup_src = self._resolve_backup_source(game.id, backup)
                if not backup_src.is_file():
                    raise ModFilesystemError(f"Original backup file is missing for {rel_path!r}.")
                _atomic_copy_file(backup_src, target, expected_sha256=backup.orig_sha256)
            elif backup is not None and not backup.existed:
                if target.exists():
                    info = target.lstat()
                    if _is_reparse(info):
                        raise ModFilesystemError("Refusing to remove a symlink inside game folder.")
                    target.unlink()
                    _cleanup_empty_dirs(install_dir, target.parent)
            elif target.exists() and dep_entry is not None:
                info = target.lstat()
                if _is_reparse(info):
                    raise ModFilesystemError("Refusing to remove a symlink inside game folder.")
                target.unlink()
                _cleanup_empty_dirs(install_dir, target.parent)
            if dep_entry is not None:
                self._repo.delete_deployed_file(game.id, dep_entry[0])

        # 3. Deploy every desired file atomically with verify-before-replace SHA-256 check.
        for key in sorted(desired.keys()):
            rel_path, winner_item, expected_sha = desired[key]
            dep_entry = deployed_ci.get(key)
            current = dep_entry[1] if dep_entry is not None else None
            target = self._safe_game_target(install_dir, rel_path)
            if (
                current is not None
                and current.item_id == winner_item.id
                and current.deployed_sha256 == expected_sha
                and target.is_file()
                and _sha256_file(target) == expected_sha
            ):
                continue
            self._assert_no_game_running(game)
            pkg_dir = self._resolve_mods_subpath(winner_item.storage_dir, f"packages/{game.id}")
            src_file = pkg_dir / "files" / PurePosixPath(rel_path)
            if not src_file.is_file():
                raise ModFilesystemError(f"Stored package file is missing: {rel_path!r}")
            actual_sha = _atomic_copy_file(src_file, target, expected_sha256=expected_sha)
            if dep_entry is not None and dep_entry[0] != rel_path:
                self._repo.delete_deployed_file(game.id, dep_entry[0])
            self._repo.set_deployed_file(
                game_id=game.id,
                rel_path=rel_path,
                item_id=winner_item.id,
                deployed_sha256=actual_sha,
            )

        self._repo.finish_journal(journal_id, "committed")
