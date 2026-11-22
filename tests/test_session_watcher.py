from unittest.mock import Mock

from gamehub.core.library.models import LibraryChanged
from gamehub.core.sessions.models import ProcessSnapshot, WatchTarget
from gamehub.core.sessions.watcher import SessionWatcher
from gamehub.core.storage.db import StorageError


def test_failed_target_removal_is_retried_and_idle_polls_reuse_targets() -> None:
    target = WatchTarget("game", "exe_path", r"C:\Games\Example.exe")
    store = Mock()
    store.watch_targets.side_effect = [(target,), (), ()]
    probe = Mock()
    tracker = Mock()
    tracker.target_removed.side_effect = [StorageError("Retry"), None]
    watcher = SessionWatcher(store, probe, tracker, interval=0)
    samples = []

    def sample(targets):
        samples.append(targets)
        if len(samples) == 1:
            watcher.library_changed(LibraryChanged(("game",)))
        if len(samples) == 4:
            watcher._stop.set()
        return ProcessSnapshot({})

    probe.snapshot.side_effect = sample
    watcher._run()

    assert samples == [(target,), (), (), ()]
    assert store.watch_targets.call_count == 3
    assert tracker.target_removed.call_count == 2
    tracker.mark_unreliable.assert_called_once()
    tracker.shutdown.assert_called_once()
