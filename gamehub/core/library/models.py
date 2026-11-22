"""Values passed between discovery, storage, and the library view."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class GameSource(StrEnum):
    STEAM = "steam"
    EPIC = "epic"
    XBOX = "xbox"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class GameTarget:
    kind: str
    match_key: str
    origin: str = "discovery"


@dataclass(frozen=True, slots=True)
class LaunchTarget:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class DetectedGame:
    source: GameSource
    source_id: str
    name: str
    install_dir: Path | None = None
    cover_path: Path | None = None
    launch_target: LaunchTarget | None = None
    targets: tuple[GameTarget, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryBatch:
    games: tuple[DetectedGame, ...] = ()
    state: str = "complete"
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GameSummary:
    id: str
    name: str
    source: GameSource
    install_dir: Path | None
    cover_path: Path | None
    last_played: int | None
    total_playtime: int
    installed: bool
    launch_target: LaunchTarget | None
    tracking: bool


class GameDetector(Protocol):
    @property
    def source(self) -> GameSource: ...

    def discover(self) -> DiscoveryBatch: ...
