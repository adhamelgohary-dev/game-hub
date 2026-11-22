from pathlib import Path

import pytest

from gamehub.core.sessions.models import (
    ClockReading,
    GameStarted,
    GameStopped,
    ProcessIdentity,
    ProcessSnapshot,
)
from gamehub.core.sessions.tracker import SessionTracker
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.sessions import SessionRepository


@pytest.fixture
def tracked_game(tmp_path: Path):
    database = Database(tmp_path / "gamehub.db")
    path = tmp_path / "Example Adventure.exe"
    path.touch()
    game_id = LibraryRepository(database).add_manual(path)
    events = []
    tracker = SessionTracker(SessionRepository(database), events.append)
    return game_id, tracker, events


def _sample(tracker, game_id, seconds, processes=(), *, unknown=(), complete=True):
    games = {game_id: frozenset(processes)} if processes else {}
    tracker.observe(
        ProcessSnapshot(games, frozenset(unknown), complete),
        ClockReading(1_000_000 + seconds * 1000, seconds),
    )


def test_session_requires_confirmed_exit_and_uses_last_checkpoint(tracked_game) -> None:
    game_id, tracker, events = tracked_game
    main = ProcessIdentity(41, 1.0)
    helper = ProcessIdentity(42, 2.0)
    _sample(tracker, game_id, 0, [main])
    _sample(tracker, game_id, 5, [main, helper])
    _sample(tracker, game_id, 8, [helper])
    assert tracker.active_for(main) is None
    assert tracker.active_for(helper) is not None
    _sample(tracker, game_id, 10)
    assert len(events) == 1
    assert tracker.active_for(helper) is None
    _sample(tracker, game_id, 13)
    assert isinstance(events[0], GameStarted)
    assert events[1] == GameStopped(
        game_id, events[0].session_id, 1_008_000, 8, "completed", "process_exit"
    )


def test_session_does_not_add_unverified_time_and_interrupts_on_unknown(tracked_game) -> None:
    game_id, tracker, events = tracked_game
    process = ProcessIdentity(41, 1.0)
    _sample(tracker, game_id, 0, [process])
    _sample(tracker, game_id, 4, [process])
    _sample(tracker, game_id, 7, unknown=[41])
    assert tracker.active_for(process) is None
    _sample(tracker, game_id, 10, [process])
    _sample(tracker, game_id, 13, [process])
    for seconds in (15, 18, 21):
        _sample(tracker, game_id, seconds, complete=False)
    assert isinstance(events[1], GameStopped)
    assert events[1].reason == "observation_lost"
    assert events[1].status == "interrupted"
    assert events[1].duration_sec == 7
    assert events[1].ended_at == 1_013_000


def test_session_pid_reuse_separates_sessions_and_quit_interrupts(tracked_game) -> None:
    game_id, tracker, events = tracked_game
    _sample(tracker, game_id, 0, [ProcessIdentity(41, 1.0)])
    _sample(tracker, game_id, 2, [ProcessIdentity(41, 3.0)])
    assert [type(event) for event in events] == [GameStarted, GameStopped, GameStarted]
    assert events[0].session_id != events[2].session_id
    assert events[1].reason == "process_exit"
    tracker.shutdown()
    assert events[3].reason == "app_quit"
    assert events[3].session_id == events[2].session_id


def test_session_uses_monotonic_time_when_utc_goes_backwards(tracked_game) -> None:
    game_id, tracker, events = tracked_game
    snapshot = ProcessSnapshot({game_id: frozenset([ProcessIdentity(41, 1.0)])})
    tracker.observe(snapshot, ClockReading(10_000, 0))
    tracker.observe(snapshot, ClockReading(8_000, 4))
    tracker.shutdown()
    assert events[-1].duration_sec == 4
    assert events[-1].ended_at == 10_000


def test_skipped_storage_poll_pauses_duration_and_process_eligibility(tracked_game) -> None:
    game_id, tracker, events = tracked_game
    process = ProcessIdentity(41, 1.0)
    _sample(tracker, game_id, 0, [process])
    _sample(tracker, game_id, 2, [process])
    tracker.mark_unreliable()
    assert tracker.active_for(process) is None
    _sample(tracker, game_id, 8, [process])
    assert tracker.active_for(process) is not None
    _sample(tracker, game_id, 10, [process])
    tracker.shutdown()
    assert events[-1].duration_sec == 4
