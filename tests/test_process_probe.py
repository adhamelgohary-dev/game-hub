import os
from collections.abc import Iterator

import pytest

from gamehub.core.sessions.models import ProcessIdentity, WatchTarget
from gamehub.core.sessions.processes import ProcessProbe, _WindowsProcessMetadata

GAME = WatchTarget("game", "exe_path", r"C:\Games\Sample\Game.exe")
PACKAGE = WatchTarget("pkg_only", "package_id", "Sample.Game_abcdef0123456")


class ProcessRows:
    def __init__(self, entries: dict[int, tuple[str, str | None, str | None]]) -> None:
        self.entries = entries
        self.inspected: list[tuple[int, bool, bool]] = []
        self.denied = set()
        self.exited = set()
        self.incomplete = False

    def names(self) -> Iterator[tuple[int, str]]:
        for pid, (name, _, _) in self.entries.items():
            yield pid, name
        if self.incomplete:
            raise OSError("Synthetic process inventory failure")

    def inspect(self, pid: int, *, executable: bool, package: bool) -> tuple[str | None, str | None]:
        self.inspected.append((pid, executable, package))
        if pid in self.denied:
            raise PermissionError("Synthetic process access denial")
        if pid in self.exited:
            raise ProcessLookupError("Synthetic process exit")
        _, path, family = self.entries[pid]
        return path if executable else None, family if package else None


def test_probe_uses_basename_to_shortlist_and_requires_exact_image_path() -> None:
    metadata = ProcessRows({
        10: ("unrelated.exe", r"C:\Programs\Unrelated.exe", None),
        11: ("GAME.EXE", r"c:\GAMES\sample\GAME.EXE", None),
        12: ("Game.exe", r"C:\Other\Game.exe", None),
        13: ("Game.exe", r"C:\Games\Sample\Game.exe", None),
    })
    probe = ProcessProbe(metadata, lambda pid: float(pid))

    sample = probe.snapshot([GAME])

    assert sample.games == {"game": frozenset({ProcessIdentity(11, 11.0), ProcessIdentity(13, 13.0)})}
    assert {pid for pid, _, _ in metadata.inspected} == {11, 12, 13}
    assert all(executable and not package for _, executable, package in metadata.inspected)
    assert not sample.unknown_pids


def test_probe_matches_exact_family_and_discards_conflicting_identity() -> None:
    metadata = ProcessRows({
        10: ("XboxApp.exe", None, "SAMPLE.GAME_ABCDEF0123456"),
        11: ("Game.exe", GAME.match_key, "Other.Game_abcdef0123456"),
        12: ("Similar.exe", None, "Sample.Game2_abcdef0123456"),
        13: ("vgtray.exe", None, None),
        14: ("EpicGamesLauncher.exe", None, None),
        15: ("explorer.exe", None, None),
    })
    other_package = WatchTarget("other", "package_id", "OTHER.GAME_abcdef0123456")

    sample = ProcessProbe(metadata, lambda pid: float(pid)).snapshot([GAME, PACKAGE, other_package])

    assert sample.games == {"pkg_only": frozenset({ProcessIdentity(10, 10.0)})}
    assert sample.unknown_pids == frozenset({11})
    assert (10, False, True) in metadata.inspected
    inspected_pids = {pid for pid, _, _ in metadata.inspected}
    assert inspected_pids.isdisjoint({13, 14, 15})


def test_probe_distinguishes_access_denial_from_exit() -> None:
    metadata = ProcessRows({11: ("Game.exe", GAME.match_key, None), 12: ("Game.exe", GAME.match_key, None)})
    metadata.denied.add(11)
    metadata.exited.add(12)

    sample = ProcessProbe(metadata, lambda pid: float(pid)).snapshot([GAME])

    assert sample.complete
    assert not sample.games
    assert sample.unknown_pids == frozenset({11})


def test_probe_discards_pid_reused_between_identity_checks() -> None:
    metadata = ProcessRows({11: ("Game.exe", GAME.match_key, None)})
    creation_times = iter([12.0, 99.0])

    sample = ProcessProbe(metadata, lambda _pid: next(creation_times)).snapshot([GAME])

    assert not sample.games
    assert sample.unknown_pids == frozenset({11})


def test_probe_preserves_observations_from_partially_read_inventory() -> None:
    metadata = ProcessRows({11: ("Game.exe", GAME.match_key, None)})
    metadata.incomplete = True

    sample = ProcessProbe(metadata, lambda pid: float(pid)).snapshot([GAME])

    assert not sample.complete
    assert sample.games == {"game": frozenset({ProcessIdentity(11, 11.0)})}


@pytest.mark.skipif(os.name != "nt", reason="Windows process metadata probe")
def test_native_probe_observes_current_process_image() -> None:
    pid = os.getpid()
    backend = _WindowsProcessMetadata()
    image, _ = backend.inspect(pid, executable=True, package=False)
    assert image is not None

    sample = ProcessProbe(backend).snapshot([WatchTarget("sample", "exe_path", image)])

    assert sample.complete
    assert ProcessIdentity(pid, backend.creation_time(pid)) in sample.games["sample"]
