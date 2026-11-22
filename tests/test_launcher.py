import os
import subprocess
from pathlib import Path

import pytest

from gamehub.core.library.launcher import (
    ATTEMPT_TTL_SEC,
    LaunchCoordinator,
    WindowsLauncher,
    validate_launch_target,
)
from gamehub.core.library.models import LaunchFinished, LaunchRequested, LaunchTarget
from gamehub.core.sessions.models import (
    ClockReading,
    GameStarted,
    ProcessIdentity,
    ProcessSnapshot,
)
from gamehub.core.sessions.tracker import SessionTracker
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.sessions import SessionRepository


@pytest.mark.parametrize(
    "target",
    [
        LaunchTarget("steam_uri", "steam://rungameid/420"),
        LaunchTarget(
            "epic_uri",
            "com.epicgames.launcher://apps/ns1%3Acat2%3AAppName?action=launch&silent=true",
        ),
        LaunchTarget(
            "epic_uri",
            "com.epicgames.launcher://apps/AppName?action=launch&silent=true",
        ),
    ],
)
def test_launcher_dispatches_validated_uris(target: LaunchTarget) -> None:
    opened: list[str] = []
    launcher = WindowsLauncher(open_uri=lambda uri: opened.append(uri) or None)
    result = launcher.launch("game-1", target, "attempt-1")
    assert result.accepted is True
    assert result.receipt is not None
    assert result.receipt.attempt_id == "attempt-1"
    assert opened == [target.value]


def test_launcher_dispatches_validated_executable(tmp_path: Path) -> None:
    exe = tmp_path / "Adventure.exe"
    exe.touch()
    spawned: list[Path] = []
    launcher = WindowsLauncher(spawn_exe=lambda path: spawned.append(path) or None)
    result = launcher.launch("game-1", LaunchTarget("exe", str(exe)), "attempt-1")
    assert result.accepted is True
    assert spawned == [exe]


@pytest.mark.parametrize(
    "target",
    [
        LaunchTarget("steam_uri", "steam://rungameid/"),
        LaunchTarget("steam_uri", "steam://rungameid/12345678901"),
        LaunchTarget("steam_uri", "steam://rungameid/420?arg=1"),
        LaunchTarget("steam_uri", "steam://rungameid/420#frag"),
        LaunchTarget("steam_uri", "steam://rungameid/420 --inject"),
        LaunchTarget("steam_uri", "http://example.com/game"),
        LaunchTarget("steam_uri", "file:///C:/Windows/System32/cmd.exe"),
        LaunchTarget("epic_uri", "com.epicgames.launcher://apps/App?action=launch&silent=false"),
        LaunchTarget("epic_uri", "com.epicgames.launcher://apps/App?action=launch&silent=true&x=1"),
        LaunchTarget("epic_uri", "com.epicgames.launcher://apps/../App?action=launch&silent=true"),
        LaunchTarget("epic_uri", "ms-msdt:/id"),
        LaunchTarget("exe", r"\\server\share\game.exe"),
        LaunchTarget("exe", r"C:\Windows\System32\..\cmd.exe"),
        LaunchTarget("exe", r"C:\CON.exe"),
        LaunchTarget("exe", r"C:\Games\launch.bat"),
        LaunchTarget("exe", r"C:\Games\game.exe:hidden.exe"),
        LaunchTarget("unknown", "steam://rungameid/420"),
    ],
)
def test_launcher_rejects_malformed_or_unsafe_targets(target: LaunchTarget) -> None:
    opened: list[str] = []
    spawned: list[Path] = []
    launcher = WindowsLauncher(
        open_uri=lambda uri: opened.append(uri) or None,
        spawn_exe=lambda path: spawned.append(path) or None,
    )
    assert validate_launch_target(target) is None
    result = launcher.launch("game-1", target, "attempt-1")
    assert result.accepted is False
    assert result.diagnostic == "launch_invalid_target"
    assert opened == []
    assert spawned == []


def test_launcher_rejects_missing_and_junctioned_executables(tmp_path: Path) -> None:
    missing = tmp_path / "Missing.exe"
    assert validate_launch_target(LaunchTarget("exe", str(missing))) is None

    if os.name == "nt":
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        exe = real_dir / "Game.exe"
        exe.touch()
        junction = tmp_path / "link"
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(real_dir)],
            capture_output=True,
            check=False,
        )
        assert created.returncode == 0
        assert validate_launch_target(LaunchTarget("exe", str(junction / "Game.exe"))) is None


def test_coordinator_correlates_single_start_and_expires_after_ttl() -> None:
    now = [100.0]
    events = []
    launcher = WindowsLauncher(open_uri=lambda _uri: None)
    coordinator = LaunchCoordinator(launcher, events.append, clock=lambda: now[0])

    result = coordinator.launch("game-1", LaunchTarget("steam_uri", "steam://rungameid/420"))
    assert result.accepted is True and result.receipt is not None
    assert isinstance(events[0], LaunchRequested)
    assert isinstance(events[1], LaunchFinished) and events[1].accepted is True

    # First claim consumes the attempt; second claim gets None.
    assert coordinator.claim("game-1") == result.receipt.attempt_id
    assert coordinator.claim("game-1") is None

    # A second launch expires after 90 seconds.
    second = coordinator.launch("game-1", LaunchTarget("steam_uri", "steam://rungameid/420"))
    assert second.accepted is True
    now[0] += ATTEMPT_TTL_SEC + 0.1
    assert coordinator.claim("game-1") is None


def test_failed_dispatch_clears_pending_attempt() -> None:
    events = []
    launcher = WindowsLauncher(open_uri=lambda _uri: "launch_handler_missing")
    coordinator = LaunchCoordinator(launcher, events.append)

    result = coordinator.launch("game-1", LaunchTarget("steam_uri", "steam://rungameid/420"))
    assert result.accepted is False
    assert result.diagnostic == "launch_handler_missing"
    assert coordinator.claim("game-1") is None
    assert isinstance(events[-1], LaunchFinished)
    assert events[-1].accepted is False
    assert events[-1].diagnostic == "launch_handler_missing"


def test_session_tracker_attaches_claimed_launch_attempt_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    exe = tmp_path / "Runner.exe"
    exe.touch()
    game_id = library.add_manual(exe)

    coordinator = LaunchCoordinator(WindowsLauncher(spawn_exe=lambda _p: None))
    launch = coordinator.launch(game_id, LaunchTarget("exe", str(exe)))
    assert launch.accepted is True and launch.receipt is not None

    published = []
    tracker = SessionTracker(sessions, published.append, coordinator.claim)
    proc1 = frozenset({ProcessIdentity(100, 1.0)})
    tracker.observe(ProcessSnapshot({game_id: proc1}), ClockReading(1000, 10.0))
    tracker.observe(ProcessSnapshot({}), ClockReading(4000, 13.0))
    tracker.observe(ProcessSnapshot({}), ClockReading(7000, 16.0))

    # A subsequent external start has no launch_attempt_id.
    proc2 = frozenset({ProcessIdentity(200, 20.0)})
    tracker.observe(ProcessSnapshot({game_id: proc2}), ClockReading(20_000, 30.0))

    starts = [event for event in published if isinstance(event, GameStarted)]
    assert len(starts) == 2
    assert starts[0].launch_attempt_id == launch.receipt.attempt_id
    assert starts[1].launch_attempt_id is None
