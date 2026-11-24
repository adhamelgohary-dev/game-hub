"""Crash-safe backup, deploy, conflict resolution, and restore engine for Translations & Mods."""

from __future__ import annotations

import hashlib
import logging
import ntpath
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from uuid import uuid4

from gamehub.core.library.models import GameSummary
from gamehub.core.library.paths import local_path
from gamehub.core.protection.catalog import ProtectedGamesCatalog
from gamehub.core.protection.guard import ProcessScanner, ToolhelpProcessScanner
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
from gamehub.modules.mods.repository import ModsRepository

LOGGER = logging.getLogger(__name__)


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


def _atomic_copy_file(src: Path, dst: Path) -> str:
    """Atomically copy src -> dst inside dst.parent with fsync and return sha256."""
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
        tmp.replace(dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def _ensure_no_reparse_in_chain(root: Path, target: Path) -> None:
    """Verify root and every existing path component between root and target is not a reparse point."""
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise ModFilesystemError("Game folder is not accessible.") from exc
    if not stat.S_ISDIR(root_info.st_mode) or _is_reparse(root_info):
        raise ModFilesystemError("Game folder cannot be a symlink or junction.")

    rel_parts = target.relative_to(root).parts
    current = root
    for part in rel_parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise ModFilesystemError("Could not inspect game folder path safely.") from exc
        if _is_reparse(info):
            raise ModFilesystemError("Symlinks and junctions inside game folders are not allowed.")


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
    ) -> None:
        self._repo = ModsRepository(database)
        self._data_root = data_root.absolute()
        self._library = library
        self._catalog = catalog
        self._is_any_game_running = is_any_game_running or (lambda: False)
        self._scanner = process_scanner if process_scanner is not None else ToolhelpProcessScanner()

    def is_game_protected(self, game: GameSummary) -> tuple[bool, str]:
        """Return (True, reason) for any protected/online/strict game (even if user overrode mode)."""
        exes = self._library.list_target_basenames().get(game.id, ())
        matched = self._catalog.match_game(game.source, game.source_id, exes)
        if matched is not None:
            return True, matched.anti_cheat
        if game.protection_mode == "strict":
            return True, "Strict mode"
        if self._catalog.effective_mode(game.protection_mode, game.source, game.source_id, exes) == "strict":
            return True, "Protected game"
        return False, ""

    def _require_game(self, game_id: str) -> GameSummary:
        game = self._library.get_game(game_id)
        if game is None:
            raise ModFilesystemError("Game was not found in your library.")
        return game

    def _assert_not_protected(self, game: GameSummary) -> None:
        protected, _reason = self.is_game_protected(game)
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
            try:
                install_root = local_path(target_game.install_dir)
                if install_root is not None and install_root.is_dir():
                    for child in install_root.iterdir():
                        if child.suffix.lower() == ".exe":
                            exes.add(ntpath.normcase(child.name))
            except OSError:
                pass
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

    def _validated_install_dir(self, game: GameSummary) -> Path:
        if game.install_dir is None:
            raise ModFilesystemError("This game does not have a local install folder configured.")
        validated = local_path(game.install_dir)
        if validated is None or not validated.is_dir():
            raise ModFilesystemError("This game's install folder is not accessible.")
        info = validated.lstat()
        if _is_reparse(info):
            raise ModFilesystemError("Game install folder cannot be a symlink or junction.")
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

    def _package_storage_dir(self, game_id: str, item_id: str) -> Path:
        return self._data_root / "mods" / "packages" / game_id / item_id

    def _backup_file_path(self, game_id: str, rel_path: str) -> Path:
        norm = normalize_rel_path(rel_path)
        backups_root = self._data_root / "mods" / "backups" / game_id
        backups_root.mkdir(parents=True, exist_ok=True)
        path = backups_root.joinpath(*PurePosixPath(norm).parts)
        if not path.resolve().is_relative_to(backups_root.resolve()):
            raise ModFilesystemError("Backup path escaped backup directory.")
        return path

    def _compute_conflicts(
        self, items: tuple[ModItem, ...], choices: dict[str, str]
    ) -> tuple[ModConflict, ...]:
        enabled_items = [item for item in items if item.enabled]
        by_path: dict[str, list[ModItem]] = {}
        for item in enabled_items:
            for f in item.manifest.files:
                by_path.setdefault(f.dest, []).append(item)

        pair_paths: dict[tuple[str, str], list[str]] = {}
        by_id = {item.id: item for item in enabled_items}
        for rel_path, owners in sorted(by_path.items()):
            if len(owners) < 2:
                continue
            # Pairwise conflicts (primary pair: first two owners, or all distinct pairs)
            for idx in range(len(owners)):
                for jdx in range(idx + 1, len(owners)):
                    a, b = owners[idx], owners[jdx]
                    # Put translation first when pairing a translation with a mod
                    if b.kind == "translation" and a.kind != "translation":
                        a, b = b, a
                    pair_paths.setdefault((a.id, b.id), []).append(rel_path)

        conflicts: list[ModConflict] = []
        for (a_id, b_id), paths in pair_paths.items():
            a = by_id[a_id]
            b = by_id[b_id]
            winner = choices.get(paths[0])
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
    ) -> dict[str, tuple[ModItem, str]]:
        """Map each target rel_path -> (winning ModItem, expected_sha256)."""
        enabled = [item for item in items if item.enabled]
        owners_by_path: dict[str, list[tuple[ModItem, str]]] = {}
        for item in enabled:
            for f in item.manifest.files:
                owners_by_path.setdefault(f.dest, []).append((item, f.sha256))

        desired: dict[str, tuple[ModItem, str]] = {}
        for rel_path, candidates in owners_by_path.items():
            if len(candidates) == 1:
                desired[rel_path] = candidates[0]
                continue
            chosen_id = choices.get(rel_path)
            matched = next((c for c in candidates if c[0].id == chosen_id), None)
            if matched is not None:
                desired[rel_path] = matched
            else:
                # Deterministic default: translation wins over mod, otherwise first installed
                translations = [c for c in candidates if c[0].kind == "translation"]
                desired[rel_path] = translations[0] if translations else candidates[0]
        return desired

    def get_state(self, game_id: str) -> GameModsState:
        game = self._require_game(game_id)
        protected, reason = self.is_game_protected(game)
        install_ok = False
        if not protected and game.install_dir is not None:
            validated = local_path(game.install_dir)
            install_ok = validated is not None and validated.is_dir()
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
        game = self._require_game(game_id)
        self._assert_not_protected(game)
        self._assert_no_game_running(game)
        self._validated_install_dir(game)

        item_id = uuid4().hex
        staging_dir = self._data_root / "mods" / "staging" / item_id
        try:
            manifest = extract_verified_package(zip_path, staging_dir)
            existing = self._repo.get_item_by_package_id(game_id, manifest.id)
            final_id = existing.id if existing is not None else item_id
            final_dir = self._package_storage_dir(game_id, final_id)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            if final_dir.exists():
                shutil.rmtree(final_dir)
            shutil.move(str(staging_dir), str(final_dir))
        except BaseException:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        item = self._repo.upsert_item(
            item_id=final_id,
            game_id=game_id,
            manifest=manifest,
            storage_dir=str(final_dir),
            enabled=enable,
        )
        self._reconcile_game(game, operation=f"import:{item.package_id}")
        return item

    def set_enabled(self, game_id: str, item_id: str, enabled: bool) -> GameModsState:
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
        paths_a = {f.dest for f in by_id[item_a_id].manifest.files}
        paths_b = {f.dest for f in by_id[item_b_id].manifest.files}
        shared = tuple(sorted(paths_a & paths_b))
        if shared:
            self._repo.set_conflict_winner(game_id, shared, winner_item_id)
            self._reconcile_game(game, operation=f"conflict:{winner_item_id}")
        return self.get_state(game_id)

    def remove_item(self, game_id: str, item_id: str) -> GameModsState:
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
        pkg_dir = Path(item.storage_dir)
        if pkg_dir.exists() and pkg_dir.resolve().is_relative_to(
            (self._data_root / "mods" / "packages").resolve()
        ):
            shutil.rmtree(pkg_dir, ignore_errors=True)
        return self.get_state(game_id)

    def restore_original(self, game_id: str) -> GameModsState:
        game = self._require_game(game_id)
        self._assert_not_protected(game)
        self._assert_no_game_running(game)
        self._validated_install_dir(game)
        self._repo.disable_all(game_id)
        self._reconcile_game(game, operation="restore_original")
        return self.get_state(game_id)

    def recover_incomplete(self) -> int:
        """Recover any interrupted journaled operations cleanly on startup."""
        incomplete = self._repo.list_incomplete_journals()
        if not incomplete:
            return 0
        recovered = 0
        seen_games: set[str] = set()
        for entry in incomplete:
            if entry.game_id in seen_games:
                self._repo.finish_journal(entry.id, "rolled_back")
                continue
            seen_games.add(entry.game_id)
            game = self._library.get_game(entry.game_id)
            if game is None:
                self._repo.finish_journal(entry.id, "rolled_back")
                continue
            protected, _ = self.is_game_protected(game)
            if protected:
                self._repo.finish_journal(entry.id, "rolled_back")
                continue
            try:
                self._assert_no_game_running(game)
                self._reconcile_game(game, operation=f"recover:{entry.id}")
                self._repo.finish_journal(entry.id, "rolled_back")
                recovered += 1
            except (GameRunningModError, ModFilesystemError, OSError):
                LOGGER.warning("mods_journal_recovery_deferred game_id=%s", entry.game_id)
        return recovered

    def _reconcile_game(self, game: GameSummary, *, operation: str) -> None:
        install_dir = self._validated_install_dir(game)
        items = self._repo.list_items(game.id)
        choices = self._repo.list_conflict_choices(game.id)
        desired = self._desired_file_map(items, choices)
        deployed = self._repo.list_deployed(game.id)
        backups = self._repo.list_backups(game.id)

        journal_id = uuid4().hex
        self._repo.begin_journal(
            journal_id,
            game.id,
            operation,
            {
                "desired_paths": sorted(desired.keys()),
                "deployed_paths": sorted(deployed.keys()),
            },
        )

        # 1. Back up every target file we haven't backed up yet BEFORE touching install_dir.
        for rel_path in sorted(desired.keys()):
            if rel_path in backups:
                continue
            target = self._safe_game_target(install_dir, rel_path)
            if target.exists():
                info = target.lstat()
                if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
                    raise ModFilesystemError(f"Target file is not a regular file: {rel_path!r}")
                backup_dst = self._backup_file_path(game.id, rel_path)
                orig_sha = _atomic_copy_file(target, backup_dst)
                self._repo.record_backup(
                    game_id=game.id,
                    rel_path=rel_path,
                    existed=True,
                    backup_path=str(backup_dst),
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
            backups = self._repo.list_backups(game.id)

        # 2. Restore/remove files that are no longer in desired (including restore_original).
        restore_candidates = set(deployed.keys()) - set(desired.keys())
        if not desired:
            # Ensure every tracked backup is restored even if a crash happened mid-deploy before
            # mod_deployed_files was updated!
            restore_candidates |= set(backups.keys())

        for rel_path in sorted(restore_candidates):
            target = self._safe_game_target(install_dir, rel_path)
            backup = backups.get(rel_path)
            if backup is not None and backup.existed and backup.backup_path:
                backup_src = Path(backup.backup_path)
                if not backup_src.is_file():
                    raise ModFilesystemError(f"Original backup file is missing for {rel_path!r}.")
                restored_sha = _atomic_copy_file(backup_src, target)
                if backup.orig_sha256 and restored_sha != backup.orig_sha256:
                    raise ModFilesystemError(f"Backup checksum mismatch while restoring {rel_path!r}.")
            elif backup is not None and not backup.existed:
                if target.exists():
                    info = target.lstat()
                    if _is_reparse(info):
                        raise ModFilesystemError("Refusing to remove a symlink inside game folder.")
                    target.unlink()
                    _cleanup_empty_dirs(install_dir, target.parent)
            elif target.exists() and rel_path in deployed:
                target.unlink()
                _cleanup_empty_dirs(install_dir, target.parent)
            self._repo.delete_deployed_file(game.id, rel_path)

        # 3. Deploy every desired file atomically and verify SHA-256.
        for rel_path, (winner_item, expected_sha) in sorted(desired.items()):
            current = deployed.get(rel_path)
            target = self._safe_game_target(install_dir, rel_path)
            if (
                current is not None
                and current.item_id == winner_item.id
                and current.deployed_sha256 == expected_sha
                and target.is_file()
                and _sha256_file(target) == expected_sha
            ):
                continue
            src_file = Path(winner_item.storage_dir) / "files" / PurePosixPath(rel_path)
            if not src_file.is_file():
                raise ModFilesystemError(f"Stored package file is missing: {rel_path!r}")
            actual_sha = _atomic_copy_file(src_file, target)
            if actual_sha != expected_sha:
                raise ModFilesystemError(f"Deployed file checksum mismatch for {rel_path!r}.")
            self._repo.set_deployed_file(
                game_id=game.id,
                rel_path=rel_path,
                item_id=winner_item.id,
                deployed_sha256=actual_sha,
            )

        self._repo.finish_journal(journal_id, "committed")
