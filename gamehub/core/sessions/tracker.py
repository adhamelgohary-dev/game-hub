"""Reconcile observed processes with open play sessions."""

from collections.abc import Callable
from dataclasses import dataclass

from gamehub.core.sessions.models import (
    ClockReading,
    GameStarted,
    GameStopped,
    ProcessIdentity,
    ProcessSnapshot,
    SessionIdentity,
)
from gamehub.core.storage.sessions import SessionRepository

EXIT_SAMPLES = 2
UNKNOWN_SAMPLES = 3


@dataclass(slots=True)
class ActiveSession:
    game_id: str
    session_id: str
    processes: frozenset[ProcessIdentity]
    confirmed_at: ClockReading
    duration: float = 0.0
    missing: int = 0
    unknown: int = 0


class SessionTracker:
    def __init__(
        self,
        store: SessionRepository,
        publish: Callable[[GameStarted | GameStopped], None],
        claim_launch_attempt: Callable[[str], str | None] | None = None,
    ) -> None:
        self._store = store
        self._publish = publish
        self._claim_launch_attempt = claim_launch_attempt
        self._active: dict[str, ActiveSession] = {}
        self._eligible: dict[ProcessIdentity, SessionIdentity] = {}

    def observe(self, snapshot: ProcessSnapshot, time: ClockReading) -> None:
        for game_id, active in tuple(self._active.items()):
            processes = snapshot.games.get(game_id)
            uncertain = not snapshot.complete or any(
                process.pid in snapshot.unknown_pids for process in active.processes
            )
            if processes:
                if not uncertain and _pid_reused(active.processes, processes):
                    self._finish(active, "completed", "process_exit")
                else:
                    self._checkpoint(active, processes, time)
            elif uncertain:
                active.unknown += 1
                active.missing = 0
                if active.unknown >= UNKNOWN_SAMPLES:
                    self._finish(active, "interrupted", "observation_lost")
            else:
                active.missing += 1
                active.unknown = 0
                if active.missing >= EXIT_SAMPLES:
                    self._finish(active, "completed", "process_exit")

        for game_id, processes in snapshot.games.items():
            if processes and game_id not in self._active:
                session_id = self._store.open(game_id, time.utc_ms)
                self._active[game_id] = ActiveSession(game_id, session_id, processes, time)
                attempt = self._claim_launch_attempt(game_id) if self._claim_launch_attempt is not None else None
                self._publish(GameStarted(game_id, session_id, time.utc_ms, attempt))

        self._eligible = {
            process: SessionIdentity(active.game_id, active.session_id)
            for active in self._active.values()
            if not active.missing and not active.unknown
            for process in active.processes
        }

    def mark_unreliable(self) -> None:
        """Pause time and eligibility after a poll could not reach storage."""
        self._eligible = {}
        for active in self._active.values():
            active.unknown += 1
            active.missing = 0

    def target_removed(self, game_id: str) -> None:
        active = self._active.get(game_id)
        if active is not None:
            self._finish(active, "interrupted", "observation_lost")

    def _checkpoint(
        self, active: ActiveSession, processes: frozenset[ProcessIdentity], time: ClockReading
    ) -> None:
        duration = active.duration
        if not active.missing and not active.unknown:
            duration += max(0.0, time.monotonic - active.confirmed_at.monotonic)
        seen_at = max(time.utc_ms, active.confirmed_at.utc_ms)
        self._store.checkpoint(active.session_id, seen_at, int(duration))
        active.confirmed_at = ClockReading(seen_at, time.monotonic)
        active.duration = duration
        active.processes = processes
        active.missing = 0
        active.unknown = 0

    def active_for(self, process: ProcessIdentity) -> SessionIdentity | None:
        """Match an exact identity only while its current observation is reliable."""
        return self._eligible.get(process)

    def active_pids(self) -> frozenset[int]:
        """Return PIDs of currently eligible tracked Full-mode game processes (nonzero created_at)."""
        return frozenset(proc.pid for proc in self._eligible if proc.created_at > 0.0)

    def identity_for_pid(self, pid: int) -> ProcessIdentity | None:
        """Return the tracked ProcessIdentity for an eligible PID without touching the OS."""
        for proc in self._eligible:
            if proc.pid == pid and proc.created_at > 0.0:
                return proc
        return None

    def shutdown(self) -> None:
        self._eligible = {}
        for active in tuple(self._active.values()):
            self._finish(active, "interrupted", "app_quit")

    def _finish(self, active: ActiveSession, status: str, reason: str) -> None:
        ended_at = active.confirmed_at.utc_ms
        duration = int(active.duration)
        self._store.finish(active.session_id, ended_at, duration, status)
        del self._active[active.game_id]
        self._publish(
            GameStopped(active.game_id, active.session_id, ended_at, duration, status, reason)
        )


def _pid_reused(
    previous: frozenset[ProcessIdentity], current: frozenset[ProcessIdentity]
) -> bool:
    return previous.isdisjoint(current) and not (
        {process.pid for process in previous}.isdisjoint(process.pid for process in current)
    )
