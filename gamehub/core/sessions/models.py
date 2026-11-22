"""Shared values for process sampling, session state, and events."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WatchTarget:
    game_id: str
    kind: str
    match_key: str


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    created_at: float


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    games: Mapping[str, frozenset[ProcessIdentity]]
    unknown_pids: frozenset[int] = frozenset()
    complete: bool = True


@dataclass(frozen=True, slots=True)
class ClockReading:
    utc_ms: int
    monotonic: float


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    game_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class GameStarted:
    game_id: str
    session_id: str
    started_at: int
    launch_attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class GameStopped:
    game_id: str
    session_id: str
    ended_at: int
    duration_sec: int
    status: str
    reason: str
