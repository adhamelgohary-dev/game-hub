"""Data models and exception hierarchy for Translations & Mods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ModKind = Literal["translation", "mod"]


class ModError(RuntimeError):
    """Base error for Translations & Mods operations."""


class ProtectedGameModError(ModError):
    """Raised when attempting any mod/translation action on a protected/online game."""


class GameRunningModError(ModError):
    """Raised when attempting any mod/translation filesystem change while a game is running."""


class ManifestValidationError(ModError):
    """Raised when a .zip archive or manifest.json violates declarative safety rules."""


class ModFilesystemError(ModError):
    """Raised when a backup, deploy, or restore encounters unsafe or failed disk I/O."""


@dataclass(frozen=True, slots=True)
class ModManifestFile:
    src: str
    dest: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ModManifest:
    schema_version: int
    id: str
    name: str
    name_ar: str
    kind: ModKind
    version: str
    author: str
    description: str
    description_ar: str
    files_root: str
    files: tuple[ModManifestFile, ...]


@dataclass(frozen=True, slots=True)
class ModItem:
    id: str
    game_id: str
    package_id: str
    kind: ModKind
    name: str
    name_ar: str
    version: str
    author: str
    storage_dir: str
    manifest: ModManifest
    enabled: bool
    installed_at: int


@dataclass(frozen=True, slots=True)
class ModConflict:
    item_a: ModItem
    item_b: ModItem
    rel_paths: tuple[str, ...]
    winner_item_id: str


@dataclass(frozen=True, slots=True)
class GameModsState:
    game_id: str
    game_name: str
    protected: bool
    protected_reason: str
    install_dir_available: bool
    backed_up_count: int
    has_mod_changes: bool
    items: tuple[ModItem, ...]
    conflicts: tuple[ModConflict, ...]
