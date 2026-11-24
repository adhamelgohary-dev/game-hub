"""SQLite persistence for Translations & Mods (Schema v7)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import time

from gamehub.core.storage.db import Database
from gamehub.modules.mods.manifest import manifest_to_json, parse_manifest_dict
from gamehub.modules.mods.models import ModItem, ModManifest


def _now_ms() -> int:
    return int(time() * 1000)


@dataclass(frozen=True, slots=True)
class ModBackupRecord:
    game_id: str
    rel_path: str
    existed: bool
    backup_path: str | None
    orig_sha256: str | None
    backed_up_at: int


@dataclass(frozen=True, slots=True)
class DeployedFileRecord:
    game_id: str
    rel_path: str
    item_id: str
    deployed_sha256: str
    deployed_at: int


@dataclass(frozen=True, slots=True)
class JournalRecord:
    id: str
    game_id: str
    operation: str
    status: str
    payload_json: str
    created_at: int
    updated_at: int


class ModsRepository:
    """Thread-safe SQLite repository for mod items, backups, deployed state, and journal."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def list_items(self, game_id: str) -> tuple[ModItem, ...]:
        with self._db.read() as conn:
            rows = conn.execute(
                """
                SELECT id, game_id, package_id, kind, name, name_ar, version, author,
                       storage_dir, manifest_json, enabled, installed_at
                FROM mod_items
                WHERE game_id = ?
                ORDER BY installed_at ASC, id ASC
                """,
                (game_id,),
            ).fetchall()
        items: list[ModItem] = []
        for row in rows:
            manifest = parse_manifest_dict(json.loads(row["manifest_json"]))
            items.append(
                ModItem(
                    id=row["id"],
                    game_id=row["game_id"],
                    package_id=row["package_id"],
                    kind=row["kind"],
                    name=row["name"],
                    name_ar=row["name_ar"] or row["name"],
                    version=row["version"],
                    author=row["author"] or "",
                    storage_dir=row["storage_dir"],
                    manifest=manifest,
                    enabled=bool(row["enabled"]),
                    installed_at=int(row["installed_at"]),
                )
            )
        return tuple(items)

    def get_item(self, game_id: str, item_id: str) -> ModItem | None:
        for item in self.list_items(game_id):
            if item.id == item_id:
                return item
        return None

    def get_item_by_package_id(self, game_id: str, package_id: str) -> ModItem | None:
        for item in self.list_items(game_id):
            if item.package_id == package_id:
                return item
        return None

    def upsert_item(
        self,
        *,
        item_id: str,
        game_id: str,
        manifest: ModManifest,
        storage_dir: str,
        enabled: bool,
    ) -> ModItem:
        now = _now_ms()
        m_json = manifest_to_json(manifest)
        with self._db.write() as conn:
            conn.execute(
                """
                INSERT INTO mod_items (
                    id, game_id, package_id, kind, name, name_ar, version, author,
                    storage_dir, manifest_json, enabled, installed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (game_id, package_id) DO UPDATE SET
                    kind = excluded.kind,
                    name = excluded.name,
                    name_ar = excluded.name_ar,
                    version = excluded.version,
                    author = excluded.author,
                    storage_dir = excluded.storage_dir,
                    manifest_json = excluded.manifest_json,
                    enabled = excluded.enabled
                """,
                (
                    item_id,
                    game_id,
                    manifest.id,
                    manifest.kind,
                    manifest.name,
                    manifest.name_ar,
                    manifest.version,
                    manifest.author,
                    storage_dir,
                    m_json,
                    1 if enabled else 0,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id, installed_at FROM mod_items WHERE game_id = ? AND package_id = ?",
                (game_id, manifest.id),
            ).fetchone()
        return ModItem(
            id=row["id"],
            game_id=game_id,
            package_id=manifest.id,
            kind=manifest.kind,
            name=manifest.name,
            name_ar=manifest.name_ar,
            version=manifest.version,
            author=manifest.author,
            storage_dir=storage_dir,
            manifest=manifest,
            enabled=enabled,
            installed_at=int(row["installed_at"]),
        )

    def set_enabled(self, game_id: str, item_id: str, enabled: bool) -> None:
        with self._db.write() as conn:
            conn.execute(
                "UPDATE mod_items SET enabled = ? WHERE game_id = ? AND id = ?",
                (1 if enabled else 0, game_id, item_id),
            )

    def disable_all(self, game_id: str) -> None:
        with self._db.write() as conn:
            conn.execute("UPDATE mod_items SET enabled = 0 WHERE game_id = ?", (game_id,))

    def delete_item(self, game_id: str, item_id: str) -> None:
        with self._db.write() as conn:
            conn.execute("DELETE FROM mod_items WHERE game_id = ? AND id = ?", (game_id, item_id))

    def list_backups(self, game_id: str) -> dict[str, ModBackupRecord]:
        with self._db.read() as conn:
            rows = conn.execute(
                """
                SELECT game_id, rel_path, existed, backup_path, orig_sha256, backed_up_at
                FROM mod_backups
                WHERE game_id = ?
                """,
                (game_id,),
            ).fetchall()
        return {
            row["rel_path"]: ModBackupRecord(
                game_id=row["game_id"],
                rel_path=row["rel_path"],
                existed=bool(row["existed"]),
                backup_path=row["backup_path"],
                orig_sha256=row["orig_sha256"],
                backed_up_at=int(row["backed_up_at"]),
            )
            for row in rows
        }

    def record_backup(
        self,
        *,
        game_id: str,
        rel_path: str,
        existed: bool,
        backup_path: str | None,
        orig_sha256: str | None,
    ) -> None:
        with self._db.write() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO mod_backups (
                    game_id, rel_path, existed, backup_path, orig_sha256, backed_up_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (game_id, rel_path, 1 if existed else 0, backup_path, orig_sha256, _now_ms()),
            )

    def list_deployed(self, game_id: str) -> dict[str, DeployedFileRecord]:
        with self._db.read() as conn:
            rows = conn.execute(
                """
                SELECT game_id, rel_path, item_id, deployed_sha256, deployed_at
                FROM mod_deployed_files
                WHERE game_id = ?
                """,
                (game_id,),
            ).fetchall()
        return {
            row["rel_path"]: DeployedFileRecord(
                game_id=row["game_id"],
                rel_path=row["rel_path"],
                item_id=row["item_id"],
                deployed_sha256=row["deployed_sha256"],
                deployed_at=int(row["deployed_at"]),
            )
            for row in rows
        }

    def set_deployed_file(
        self, *, game_id: str, rel_path: str, item_id: str, deployed_sha256: str
    ) -> None:
        with self._db.write() as conn:
            conn.execute(
                """
                INSERT INTO mod_deployed_files (game_id, rel_path, item_id, deployed_sha256, deployed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (game_id, rel_path) DO UPDATE SET
                    item_id = excluded.item_id,
                    deployed_sha256 = excluded.deployed_sha256,
                    deployed_at = excluded.deployed_at
                """,
                (game_id, rel_path, item_id, deployed_sha256, _now_ms()),
            )

    def delete_deployed_file(self, game_id: str, rel_path: str) -> None:
        with self._db.write() as conn:
            conn.execute(
                "DELETE FROM mod_deployed_files WHERE game_id = ? AND rel_path = ?",
                (game_id, rel_path),
            )

    def list_conflict_choices(self, game_id: str) -> dict[str, str]:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT rel_path, winner_item_id FROM mod_conflict_choices WHERE game_id = ?",
                (game_id,),
            ).fetchall()
        return {row["rel_path"]: row["winner_item_id"] for row in rows}

    def set_conflict_winner(
        self, game_id: str, rel_paths: tuple[str, ...], winner_item_id: str
    ) -> None:
        now = _now_ms()
        with self._db.write() as conn:
            for rel_path in rel_paths:
                conn.execute(
                    """
                    INSERT INTO mod_conflict_choices (game_id, rel_path, winner_item_id, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (game_id, rel_path) DO UPDATE SET
                        winner_item_id = excluded.winner_item_id,
                        updated_at = excluded.updated_at
                    """,
                    (game_id, rel_path, winner_item_id, now),
                )

    def begin_journal(self, journal_id: str, game_id: str, operation: str, payload: dict) -> None:
        now = _now_ms()
        with self._db.write() as conn:
            conn.execute(
                """
                INSERT INTO mod_journal (id, game_id, operation, status, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, 'in_progress', ?, ?, ?)
                """,
                (journal_id, game_id, operation, json.dumps(payload), now, now),
            )

    def finish_journal(self, journal_id: str, status: str) -> None:
        with self._db.write() as conn:
            conn.execute(
                "UPDATE mod_journal SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now_ms(), journal_id),
            )

    def list_incomplete_journals(self) -> tuple[JournalRecord, ...]:
        with self._db.read() as conn:
            rows = conn.execute(
                """
                SELECT id, game_id, operation, status, payload_json, created_at, updated_at
                FROM mod_journal
                WHERE status = 'in_progress'
                ORDER BY created_at ASC
                """
            ).fetchall()
        return tuple(
            JournalRecord(
                id=row["id"],
                game_id=row["game_id"],
                operation=row["operation"],
                status=row["status"],
                payload_json=row["payload_json"],
                created_at=int(row["created_at"]),
                updated_at=int(row["updated_at"]),
            )
            for row in rows
        )
