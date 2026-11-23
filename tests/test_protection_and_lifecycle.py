"""Tests for protected-games catalog, Schema v5, passive scanning, Strict mode & lifecycle."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication

from gamehub.core.hotkeys.windows import LAST_TIME_ID, RECORD_NOTE_ID, GlobalHotkeys
from gamehub.core.library.models import DetectedGame, DiscoveryBatch, GameSource
from gamehub.core.notifications.windows import WindowsNotifier
from gamehub.core.protection.catalog import (
    ProtectedGameDetected,
    ProtectedGameExited,
    ProtectedGamesCatalog,
)
from gamehub.core.protection.lifecycle import LifecycleCoordinator
from gamehub.core.sessions.models import (
    GameStarted,
    GameStopped,
    ProcessSnapshot,
    WatchTarget,
)
from gamehub.core.sessions.processes import ProcessProbe
from gamehub.core.sessions.watcher import SessionWatcher
from gamehub.core.settings import SettingsService
from gamehub.core.storage.db import (
    CONTROLS_SCHEMA,
    INITIAL_SCHEMA,
    NOTE_SCHEMA,
    SCHEMA_VERSION,
    SCREENSHOT_SCHEMA,
    Database,
)
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.pending_notes import PendingNoteRepository


def test_bundled_protected_games_catalog_and_override(tmp_path: Path) -> None:
    catalog = ProtectedGamesCatalog.load()
    assert len(catalog.entries) >= 25
    assert catalog.match_exe_name("VALORANT-Win64-Shipping.exe") is not None
    assert catalog.match_game(GameSource.STEAM, "1172470").name == "Apex Legends"
    assert catalog.match_game(GameSource.STEAM, "730").name == "Counter-Strike 2"
    assert catalog.match_game(GameSource.STEAM, "1422450").name == "Deadlock"
    assert catalog.match_game(GameSource.EPIC, "Fortnite").name == "Fortnite"
    assert catalog.effective_mode("auto", GameSource.STEAM, "1172470") == "strict"
    assert catalog.effective_mode("full", GameSource.STEAM, "1172470") == "full"
    assert catalog.effective_mode("auto", GameSource.STEAM, "999999") == "full"
    assert catalog.effective_mode("strict", GameSource.STEAM, "999999") == "strict"

    # EAC FromSoftware / co-op titles default to Strict; Dark Souls III (no EAC) stays Full.
    assert catalog.effective_mode("auto", GameSource.STEAM, "1245620") == "strict"
    assert catalog.effective_mode("auto", GameSource.MANUAL, "m-er", ("eldenring.exe",)) == "strict"
    assert (
        catalog.effective_mode("auto", GameSource.MANUAL, "m-eac", ("start_protected_game.exe",))
        == "strict"
    )
    assert catalog.effective_mode("auto", GameSource.STEAM, "2622380") == "strict"
    assert catalog.effective_mode("auto", GameSource.MANUAL, "m-nr", ("nightreign.exe",)) == "strict"
    assert catalog.effective_mode("auto", GameSource.STEAM, "1888160") == "strict"
    assert (
        catalog.effective_mode("auto", GameSource.MANUAL, "m-ac6", ("armoredcore6.exe",))
        == "strict"
    )
    assert catalog.effective_mode("auto", GameSource.STEAM, "1501750") == "strict"
    assert catalog.effective_mode("auto", GameSource.STEAM, "2183900") == "strict"
    assert (
        catalog.effective_mode("auto", GameSource.STEAM, "374320", ("darksoulsiii.exe",))
        == "full"
    )

    override = tmp_path / "protected_games_override.json"
    override.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-11-23",
                "games": [
                    {
                        "id": "custom_competitive",
                        "name": "Custom Competitive",
                        "anti_cheat": "CustomAC",
                        "privilege": "kernel",
                        "starts_at": "launch",
                        "default_mode": "strict",
                        "steam_app_ids": ["777777"],
                        "exe_names": ["customcomp.exe"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    merged = ProtectedGamesCatalog.load(override_path=override)
    assert merged.match_exe_name("CustomComp.exe") is not None
    assert merged.match_game(GameSource.STEAM, "777777") is not None

    # Corrupt override falls back cleanly to bundled catalog.
    override.write_text("{broken json", encoding="utf-8")
    fallback = ProtectedGamesCatalog.load(override_path=override)
    assert fallback.match_exe_name("valorant-win64-shipping.exe") is not None


def test_schema_v4_migrates_to_v5_with_backup_and_pending_notes(tmp_path: Path) -> None:
    db_path = tmp_path / "gamehub.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for step, statements in enumerate(
            (INITIAL_SCHEMA, SCREENSHOT_SCHEMA, NOTE_SCHEMA, CONTROLS_SCHEMA), start=1
        ):
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {step}")
        conn.execute(
            "INSERT INTO games (id, source, source_id, name, added_at) "
            "VALUES ('g1', 'steam', '1172470', 'Apex Legends', 1000)"
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('app.start_with_windows', 'true')"
        )
        conn.commit()
    finally:
        conn.close()

    db = Database(db_path)
    assert (tmp_path / "gamehub.db-v4.bak").is_file()
    with db.read() as read_conn:
        assert read_conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        legacy = read_conn.execute(
            "SELECT 1 FROM settings WHERE key = 'app.start_with_windows'"
        ).fetchone()
        assert legacy is None

    lib = LibraryRepository(db)
    game = lib.get_game("g1")
    assert game is not None
    assert game.protection_mode == "auto"
    assert game.exit_after_launch is False

    lib.set_protection("g1", "strict", exit_after_launch=True)
    updated = lib.get_game("g1")
    assert updated is not None
    assert updated.protection_mode == "strict"
    assert updated.exit_after_launch is True

    pending_repo = PendingNoteRepository(db)
    pid = pending_repo.add("g1", 5000)
    pending = pending_repo.list_pending()
    assert len(pending) == 1
    assert pending[0].id == pid
    session_id = pending_repo.create_deferred_session("g1", 5000, 9000)
    assert session_id
    pending_repo.consume(pid)
    assert pending_repo.list_pending() == ()


def test_process_probe_never_opens_handles_for_protected_or_strict_games() -> None:
    inspect_calls: list[int] = []
    creation_calls: list[int] = []

    class FakeMetadata:
        def names(self):
            yield 101, "VALORANT-Win64-Shipping.exe"
            yield 202, "SinglePlayer.exe"

        def inspect(self, pid: int, *, executable: bool, package: bool):
            inspect_calls.append(pid)
            if pid == 202 and executable:
                return r"C:\Games\SinglePlayer.exe", None
            return None, None

    def fake_creation(pid: int) -> float:
        creation_calls.append(pid)
        return 1234.5

    probe = ProcessProbe(metadata=FakeMetadata(), creation_time=fake_creation)
    snapshot = probe.snapshot(
        targets=(WatchTarget("sp-game", "exe_path", r"c:\games\singleplayer.exe"),),
        passive_basenames={"valorant-win64-shipping.exe": frozenset({"val-game"})},
        protected_exes=frozenset({"valorant-win64-shipping.exe"}),
    )

    assert "val-game" in snapshot.games
    assert "sp-game" in snapshot.games
    assert "valorant-win64-shipping.exe" in snapshot.protected_exes
    # Hard anti-cheat rule: PID 101 (protected/strict) must NEVER be passed to inspect/OpenProcess!
    assert 101 not in inspect_calls
    assert 101 not in creation_calls
    assert 202 in inspect_calls


def test_hotkeys_suspend_and_resume_cleanly() -> None:
    app = QCoreApplication.instance() or QCoreApplication(["hotkey suspend test"])
    hotkeys = GlobalHotkeys(app)
    registered: dict[int, tuple[int, int]] = {}
    hotkeys._register = lambda _h, ident, mods, key: (registered.__setitem__(ident, (mods, key)) or 1)
    hotkeys._unregister = lambda _h, ident: (registered.pop(ident, None) and 1) or 1
    try:
        handler = Mock()
        assert hotkeys.bind_shortcut(RECORD_NOTE_ID, "Ctrl+Alt+N", handler)
        assert hotkeys.bind_shortcut(LAST_TIME_ID, "Ctrl+Alt+L", handler)
        assert set(registered) == {RECORD_NOTE_ID, LAST_TIME_ID}

        hotkeys.suspend()
        assert hotkeys.is_suspended is True
        assert registered == {}

        # Updating hotkeys while suspended stores them without registering live Win32 hotkeys.
        ok, failed = hotkeys.rebind_batch({LAST_TIME_ID: ("Ctrl+Alt+K", handler)})
        assert (ok, failed) == (True, None)
        assert registered == {}

        hotkeys.resume()
        assert hotkeys.is_suspended is False
        assert registered[RECORD_NOTE_ID][1] == ord("N")
        assert registered[LAST_TIME_ID][1] == ord("K")
    finally:
        hotkeys.close()


def test_lifecycle_play_through_strict_mode_and_forgetful_guard(tmp_path: Path) -> None:
    db = Database(tmp_path / "gamehub.db")
    lib = LibraryRepository(db)
    pending = PendingNoteRepository(db)
    lib.reconcile(
        GameSource.STEAM,
        DiscoveryBatch(
            games=(
                DetectedGame(GameSource.STEAM, "1172470", "Apex Legends"),
                DetectedGame(GameSource.STEAM, "999001", "Story RPG"),
            )
        ),
    )
    games = {g.name: g for g in lib.list_games()}
    apex = games["Apex Legends"]
    rpg = games["Story RPG"]

    catalog = ProtectedGamesCatalog.load()
    actions: list[str] = []
    prompt_enabled = [True]

    coord = LifecycleCoordinator(
        catalog,
        lib,
        pending,
        external_behavior="exit_app",
        suspend_hotkeys=lambda: actions.append("suspend_hotkeys"),
        resume_hotkeys=lambda: actions.append("resume_hotkeys"),
        pause_capture=lambda: actions.append("pause_capture"),
        resume_capture=lambda: actions.append("resume_capture"),
        minimize_window=lambda: actions.append("minimize"),
        restore_window=lambda: actions.append("restore"),
        exit_app=lambda: actions.append("exit_app"),
        show_status=lambda name: actions.append(f"status:{name}"),
        notify_passive=lambda name: actions.append(f"notify:{name}"),
        prompts_enabled=lambda: prompt_enabled[0],
        clock_ms=lambda: 50_000,
    )

    assert coord.is_strict_game(apex.id) is True
    assert coord.is_strict_game(rpg.id) is False

    # 1. Play-through Full mode with exit_after_play=True -> minimize -> exit after note prompt.
    assert coord.on_play_launched(rpg.id, exit_after_play=True) is False
    assert actions == ["minimize"]
    actions.clear()
    coord.on_game_stopped(GameStopped(rpg.id, "s1", 60_000, 10, "completed", "process_exit"))
    assert "exit_app" not in actions  # Waits for note prompt first.
    coord.on_note_prompt_finished(rpg.id)
    assert actions == ["exit_app"]

    # 2. Play-through Strict mode with exit_after_launch=True -> saves pending_note and exits!
    actions.clear()
    lib.set_protection(apex.id, "strict", exit_after_launch=True)
    assert coord.on_play_launched(apex.id, exit_after_play=False) is True
    assert actions == ["exit_app"]
    assert len(pending.list_pending()) == 1

    # 3. Play-through Strict mode (stay minimized) -> suspends hotkeys/capture, restores on stop!
    actions.clear()
    lib.set_protection(apex.id, "strict", exit_after_launch=False)
    assert coord.on_play_launched(apex.id, exit_after_play=False) is False
    assert actions == ["suspend_hotkeys", "pause_capture", "minimize"]
    assert coord.is_strict_active() is True
    # Protected detection for our own Play-launched game must NOT trigger forgetful-case exit.
    actions.clear()
    coord.on_protected_detected(
        ProtectedGameDetected("apex_legends", "Apex Legends", "EAC", "r5apex.exe", apex.id)
    )
    assert actions == []
    coord.on_game_stopped(GameStopped(apex.id, "s2", 70_000, 20, "completed", "process_exit"))
    assert "resume_hotkeys" in actions and "resume_capture" in actions

    # 3b. External start of a registered strict game engages Strict mode immediately.
    actions.clear()
    coord.on_game_started(GameStarted(apex.id, "s3", 75_000, None))
    assert actions == ["suspend_hotkeys", "pause_capture"]
    assert coord.is_strict_active() is True
    coord.on_game_stopped(GameStopped(apex.id, "s3", 80_000, 5, "completed", "process_exit"))
    assert coord.is_strict_active() is False

    # 4. Forgetful case (external Valorant launched while Game Hub is open):
    # (a) Default exit_app
    actions.clear()
    val = ProtectedGameDetected("valorant", "Valorant", "Vanguard", "valorant.exe", None)
    coord.on_protected_detected(val)
    assert actions == ["exit_app"]

    # (b) strict_mode
    actions.clear()
    coord.set_external_behavior("strict_mode")
    coord.on_protected_detected(val)
    assert actions == ["suspend_hotkeys", "pause_capture", "minimize", "status:Valorant"]
    assert coord.is_strict_active() is True
    coord.clear_external_protected("valorant")
    assert coord.is_strict_active() is False

    # (c) ask_me -> precautionary Strict mode + passive Windows notification (never a window over game)
    actions.clear()
    coord.set_external_behavior("ask_me")
    coord.on_protected_detected(val)
    assert actions == ["suspend_hotkeys", "pause_capture", "minimize", "notify:Valorant"]


def test_settings_persists_theme_and_external_behavior(tmp_path: Path) -> None:
    db = Database(tmp_path / "gamehub.db")
    service = SettingsService(db)
    assert service.read().theme == "dark"
    assert service.read().external_protected_behavior == "exit_app"

    bad = service.update({"ui.theme": "neon", "protection.external_behavior": "hack"})
    assert bad.ok is False
    assert bad.errors == {
        "ui.theme": "invalid_theme",
        "protection.external_behavior": "invalid_external_behavior",
    }

    good = service.update({"ui.theme": "light", "protection.external_behavior": "ask_me"})
    assert good.ok is True
    reloaded = SettingsService(Database(tmp_path / "gamehub.db")).read()
    assert reloaded.theme == "light"
    assert reloaded.external_protected_behavior == "ask_me"


def test_windows_notifier_handles_sender_and_errors_cleanly() -> None:
    delivered: list[tuple[str, str]] = []
    notifier = WindowsNotifier(sender=lambda t, b: (delivered.append((t, b)) or True))
    assert notifier.notify_protected_game("Valorant", title="Alert", body="Strict mode") is True
    assert delivered == [("Alert", "Strict mode")]

    failing = WindowsNotifier(sender=lambda _t, _b: (_ for _ in ()).throw(OSError("no toast")))
    assert failing.notify_protected_game("Valorant", title="Alert", body="Strict mode") is False


def test_watcher_emits_protected_detected_and_exited_events() -> None:
    catalog = ProtectedGamesCatalog.load()
    published = []
    watcher = SessionWatcher(
        Mock(), Mock(), Mock(), catalog=catalog, publish_protected=published.append
    )
    watcher._emit_protected_detections(
        ProcessSnapshot({}, protected_exes=frozenset({"valorant-win64-shipping.exe"})),
        {},
    )
    watcher._emit_protected_detections(ProcessSnapshot({}), {})
    assert len(published) == 2
    assert isinstance(published[0], ProtectedGameDetected)
    assert published[0].entry_id == "valorant"
    assert isinstance(published[1], ProtectedGameExited)
    assert published[1].entry_id == "valorant"


def test_library_and_game_page_show_strict_for_elden_ring_and_full_for_dark_souls_3(
    tmp_path: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QApplication, QLabel

    from gamehub.app import GameHubWindow
    from gamehub.core.storage.memory import TimelinePage

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["strict badge test"])
    db = Database(tmp_path / "gamehub.db")
    lib = LibraryRepository(db)
    pending = PendingNoteRepository(db)
    lib.reconcile(
        GameSource.STEAM,
        DiscoveryBatch(
            games=(
                DetectedGame(GameSource.STEAM, "1245620", "Elden Ring"),
                DetectedGame(GameSource.STEAM, "1888160", "ARMORED CORE VI FIRES OF RUBICON"),
                DetectedGame(GameSource.STEAM, "374320", "DARK SOULS III"),
            )
        ),
    )
    catalog = ProtectedGamesCatalog.load()
    lifecycle = LifecycleCoordinator(catalog, lib, pending)
    window = GameHubWindow(app)
    try:
        window.library.set_strict_resolver(lambda g: lifecycle.is_strict_game(g.id))
        games = lib.list_games()
        window.library.present_games(games)
        by_name = {g.name: g for g in games}
        card_badges = {}
        for card in window.library.cards():
            badge = card.findChild(QLabel, "badgeStrict") or card.findChild(QLabel, "badgeFull")
            assert badge is not None
            card_badges[card.game_id] = (badge.objectName(), badge.text())

        assert card_badges[by_name["Elden Ring"].id] == ("badgeStrict", "Strict")
        assert card_badges[by_name["ARMORED CORE VI FIRES OF RUBICON"].id] == (
            "badgeStrict",
            "Strict",
        )
        assert card_badges[by_name["DARK SOULS III"].id] == ("badgeFull", "Full")

        er = by_name["Elden Ring"]
        window.game_page.show_game(
            er,
            (),
            TimelinePage(()),
            auto_strict=catalog.effective_mode("auto", er.source, er.source_id) == "strict",
        )
        assert window.game_page._mode_badge.objectName() == "badgeStrict"
        assert window.game_page._mode_badge.text() == "Strict"
        assert window.game_page._protection_combo.currentText() == "Auto (Strict)"
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
