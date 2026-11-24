"""Layer 2, 3, 4, 5 & 7 Zero-Presence Anti-Cheat Test Lab (dummy processes, all 4 orders, fail-closed, SCM)."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gamehub.app import _run
from gamehub.core.library.launcher import WindowsLauncher, validate_launch_target
from gamehub.core.library.models import GameSource, LaunchTarget
from gamehub.core.protection.catalog import CatalogLoadError, ProtectedGamesCatalog
from gamehub.core.protection.guard import (
    ProtectionCheckError,
    ProtectionGuard,
    ProtectionTrigger,
    WindowsServiceProbe,
    _benign_windows_donor_exe,
    run_dummy_process_protection_test,
)
from gamehub.core.storage.db import (
    CONTROLS_SCHEMA,
    INITIAL_SCHEMA,
    NOTE_SCHEMA,
    PROTECTION_SCHEMA,
    SCHEMA_VERSION,
    SCREENSHOT_SCHEMA,
    Database,
)
from gamehub.single_instance import SingleInstance


class _FakeScanner:
    def __init__(self, procs: list[tuple[int, str]] | None = None, *, fail: bool = False) -> None:
        self.procs = list(procs or [])
        self.fail = fail

    def list_processes(self) -> tuple[tuple[int, str], ...]:
        if self.fail:
            raise ProtectionCheckError("snapshot_failed")
        return tuple(self.procs)


class _FakeServiceProbe:
    def __init__(
        self,
        running: set[str] | None = None,
        *,
        available: bool = True,
        fail: bool = False,
    ) -> None:
        self.running = set(running or set())
        self.available = available
        self.fail = fail

    def verify_available(self) -> bool:
        return self.available

    def running_services(self, service_names) -> frozenset[str]:
        if self.fail:
            raise ProtectionCheckError("scm_query_failed")
        return frozenset(name for name in service_names if name in self.running)


def test_catalog_schema_v2_stages_and_strict_load_fail_closed(tmp_path: Path) -> None:
    catalog = ProtectedGamesCatalog.load(strict_load=True)
    fn = catalog.match_game(GameSource.EPIC, "Fortnite")
    assert fn is not None
    assert "fortnitebootstrapper.exe" in fn.launcher_stage_exes
    assert "fortnitelauncher.exe" in fn.launcher_stage_exes
    assert "fortniteclient-win64-shipping_eac_eos.exe" in fn.anti_cheat_exes
    assert "fortniteclient-win64-shipping.exe" in fn.game_exes

    val = catalog.match_game(GameSource.RIOT, "valorant.live")
    assert val is not None
    assert "valorant.exe" in val.launcher_stage_exes
    assert "valorant-win64-shipping.exe" in val.game_exes

    fc = catalog.match_exe_name("FC27.exe")
    assert fc is not None and fc.id == "ea_fc"
    assert "eaanticheat.gameservicelauncher.exe" in fc.launcher_stage_exes

    # Missing or corrupt bundled catalog MUST raise in strict_load mode (fail-closed)
    missing = tmp_path / "missing.json"
    with pytest.raises(CatalogLoadError):
        ProtectedGamesCatalog.load(bundled_path=missing, strict_load=True)

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogLoadError):
        ProtectedGamesCatalog.load(bundled_path=corrupt, strict_load=True)


def test_layer2_all_four_orders_and_service_detection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["zero-presence test"])

    # Case 1: App opened while Riot Client / FortniteLauncher / running anti-cheat service is ALREADY active
    for procs, svcs, expected_name in (
        ([(100, "RiotClientServices.exe")], set(), "Riot Client"),
        ([(101, "FortniteLauncher.exe")], set(), "Fortnite"),
        ([(102, "FortniteBootstrapper.exe")], set(), "Fortnite"),
        ([(103, "EasyAntiCheat_EOS.exe")], set(), "easyanticheat_eos.exe"),
        ([], {"EasyAntiCheat_EOS"}, "EasyAntiCheat_EOS"),
        ([], {"vgc"}, "vgc"),
        ([], {"BEService"}, "BEService"),
    ):
        dialogs: list[tuple[str, str]] = []
        root = tmp_path / f"case1_{expected_name.replace(' ', '_')}"
        code = _run(
            app,
            root,
            smoke_test=False,
            process_scanner=_FakeScanner(procs),
            service_probe=_FakeServiceProbe(svcs),
            show_guard_dialog=lambda kind, text, box=dialogs: box.append((kind, text)),
        )
        assert code == 0
        assert len(dialogs) == 1 and dialogs[0][0] == "refused"
        assert "protected game" in dialogs[0][1].lower()
        # Wrote nothing to disk!
        assert not (root / "gamehub.db").exists()

    # Case 4: App opened AGAIN while a protected game is running, even when SingleInstance is held!
    holder_root = tmp_path / "case4_holder"
    holder_root.mkdir()
    activated = []
    holder = SingleInstance(holder_root, lambda: activated.append("activated"))
    assert holder.claim_or_activate() is True
    try:
        dialogs4: list[tuple[str, str]] = []
        code4 = _run(
            app,
            holder_root,
            smoke_test=False,
            process_scanner=_FakeScanner([(555, "VALORANT.exe")]),
            service_probe=_FakeServiceProbe(),
            show_guard_dialog=lambda kind, text: dialogs4.append((kind, text)),
        )
        assert code4 == 0
        assert len(dialogs4) == 1 and dialogs4[0][0] == "refused"
        # SingleInstance must NOT bypass the check or activate!
        assert activated == []
    finally:
        holder.close()

    # Case 2 & Case 3: Epic Launcher ALREADY open -> Game Hub starts cleanly (story games allowed!),
    # then FortniteLauncher.exe appears -> Game Hub exits immediately!
    scanner3 = _FakeScanner([(200, "EpicGamesLauncher.exe"), (201, "DeathStranding.exe")])
    dialogs3: list[tuple[str, str]] = []

    def _inject_fortnite() -> None:
        scanner3.procs.append((202, "FortniteLauncher.exe"))

    QTimer.singleShot(150, _inject_fortnite)
    t0 = monotonic()
    code3 = _run(
        app,
        tmp_path / "case3_epic_then_fortnite",
        smoke_test=False,
        process_scanner=scanner3,
        service_probe=_FakeServiceProbe(),
        guard_interval_sec=0.05,
        show_guard_dialog=lambda kind, text: dialogs3.append((kind, text)),
    )
    elapsed_ms = (monotonic() - t0) * 1000
    assert code3 == 0
    assert dialogs3 == []  # Clean silent immediate exit, no blocking dialog!
    assert elapsed_ms < 2000


def test_layer2_fail_closed_cases(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(["fail-closed test"])

    # 1. Corrupt catalog -> fail-closed exit code 2
    bad_cat = tmp_path / "bad_catalog.json"
    bad_cat.write_text("CORRUPT", encoding="utf-8")
    dialogs: list[tuple[str, str]] = []
    code = _run(
        app,
        tmp_path / "fc1",
        smoke_test=False,
        catalog_path=bad_cat,
        process_scanner=_FakeScanner(),
        service_probe=_FakeServiceProbe(),
        show_guard_dialog=lambda kind, text: dialogs.append((kind, text)),
    )
    assert code == 2
    assert len(dialogs) == 1 and dialogs[0][0] == "fail_closed"

    # 2. SCM unavailable on startup -> fail-closed exit code 2
    dialogs2: list[tuple[str, str]] = []
    code2 = _run(
        app,
        tmp_path / "fc2",
        smoke_test=False,
        process_scanner=_FakeScanner(),
        service_probe=_FakeServiceProbe(available=False),
        show_guard_dialog=lambda kind, text: dialogs2.append((kind, text)),
    )
    assert code2 == 2
    assert len(dialogs2) == 1 and dialogs2[0][0] == "fail_closed"

    # 3. Runtime detector exception -> fail-closed callback fires
    scanner = _FakeScanner()
    svc = _FakeServiceProbe()
    catalog = ProtectedGamesCatalog.load(strict_load=True)
    guard = ProtectionGuard(
        catalog, process_scanner=scanner, service_probe=svc, interval_sec=0.05
    )
    failed_event = Event()
    reasons: list[str] = []
    guard.start(
        on_trigger=lambda _t: None,
        on_failure=lambda r: (reasons.append(r), failed_event.set()),
    )
    svc.fail = True
    assert failed_event.wait(timeout=2.0) is True
    assert reasons and guard.is_healthy() is False
    guard.close()

    # 4. Stale heartbeat detected by watchdog health check
    now = [100.0]
    guard2 = ProtectionGuard(
        catalog,
        process_scanner=_FakeScanner(),
        service_probe=_FakeServiceProbe(),
        interval_sec=0.05,
        clock=lambda: now[0],
    )
    guard2.start(on_trigger=lambda _t: None, on_failure=lambda _r: None)
    assert guard2.is_healthy(max_stale_sec=2.5) is True
    # Simulate hung thread: freeze last heartbeat behind clock
    with guard2._heartbeat_lock:
        guard2._last_heartbeat = 90.0
    now[0] = 100.0
    assert guard2.is_healthy(max_stale_sec=2.5) is False
    guard2.close()


def test_layer4_launcher_rules_and_per_game_override() -> None:
    catalog = ProtectedGamesCatalog.load(strict_load=True)

    # Epic launcher allowed by default (story games work!)
    guard = ProtectionGuard(
        catalog,
        process_scanner=_FakeScanner([(10, "EpicGamesLauncher.exe"), (11, "Hue.exe")]),
        service_probe=_FakeServiceProbe(),
    )
    assert guard.check_once() is None

    # Optional Epic strict toggle ON -> triggers on EpicGamesLauncher.exe
    guard.update_policy(enabled_optional_launchers={"epic"})
    trig = guard.check_once()
    assert trig is not None and trig.kind == "strict_launcher" and trig.display_name == "Epic Games Launcher"

    # Riot Client is ALWAYS strict even when optional launchers are empty
    riot_guard = ProtectionGuard(
        catalog,
        process_scanner=_FakeScanner([(12, "RiotClientServices.exe")]),
        service_probe=_FakeServiceProbe(),
        enabled_optional_launchers=(),
        disabled_entry_ids=("valorant", "league_of_legends"),
    )
    rtrig = riot_guard.check_once()
    assert rtrig is not None and rtrig.kind == "strict_launcher" and rtrig.display_name == "Riot Client"

    # Per-game override OFF ('full') allows that specific game's exe, while anti-cheat exe still protects
    fn_guard = ProtectionGuard(
        catalog,
        process_scanner=_FakeScanner([(13, "FortniteClient-Win64-Shipping.exe")]),
        service_probe=_FakeServiceProbe(),
        disabled_entry_ids=("fortnite",),
    )
    assert fn_guard.check_once() is None


@pytest.mark.parametrize(
    "dummy_exe,expected_stage",
    [
        ("FortniteBootstrapper.exe", "launcher_stage"),
        ("FortniteLauncher.exe", "launcher_stage"),
        ("VALORANT.exe", "launcher_stage"),
        ("EasyAntiCheat_EOS.exe", "anti_cheat"),
        ("RiotClientServices.exe", "launcher"),
        ("EAAntiCheat.GameServiceLauncher.exe", "launcher_stage"),
    ],
)
def test_layer7_real_dummy_process_lab(tmp_path: Path, dummy_exe: str, expected_stage: str) -> None:
    """Real Windows dummy-process test lab: verify Toolhelp32 detection and < 1s latency."""
    from gamehub.core.protection.guard import ToolhelpProcessScanner

    donor = _benign_windows_donor_exe()
    assert donor is not None

    catalog = ProtectedGamesCatalog.load(strict_load=True)
    dummy_path = tmp_path / dummy_exe
    shutil.copy2(donor, dummy_path)

    # Verify read-only Windows SCM probe works cleanly on this machine
    assert WindowsServiceProbe().verify_available() is True

    real_scanner = ToolhelpProcessScanner()
    target_pid: list[int | None] = [None]

    class _PidScopedRealScanner:
        def list_processes(self) -> tuple[tuple[int, str], ...]:
            pid = target_pid[0]
            if pid is None:
                return ()
            return tuple(item for item in real_scanner.list_processes() if item[0] == pid)

    guard = ProtectionGuard(catalog, process_scanner=_PidScopedRealScanner(), interval_sec=0.10)
    triggered = Event()
    hits: list[ProtectionTrigger] = []
    guard.start(on_trigger=lambda t: (hits.append(t), triggered.set()), on_failure=lambda _e: None)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [str(dummy_path), "127.0.0.1", "-n", "6"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creation_flags,
        shell=False,
    )
    target_pid[0] = proc.pid
    t0 = monotonic()
    try:
        assert triggered.wait(timeout=2.5) is True
        latency_ms = (monotonic() - t0) * 1000
        assert hits and hits[0].stage == expected_stage
        assert latency_ms < 1000.0, f"Detection latency too high: {latency_ms:.1f} ms"
    finally:
        guard.close()
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3.0)


def test_layer7_dummy_self_test_helper_does_not_trip_live_guard() -> None:
    """Clicking 'Test protection' measures real latency without closing the live main guard."""
    catalog = ProtectedGamesCatalog.load(strict_load=True)
    live_guard = ProtectionGuard(
        catalog,
        process_scanner=_FakeScanner(),
        service_probe=_FakeServiceProbe(),
        interval_sec=0.05,
    )
    live_hits: list[ProtectionTrigger] = []
    live_guard.start(on_trigger=live_hits.append, on_failure=lambda _e: None)
    try:
        result = run_dummy_process_protection_test(
            catalog,
            dummy_exe_name="FortniteLauncher.exe",
            live_guard=live_guard,
            interval_sec=0.08,
        )
        assert result.ok is True, f"Self-test failed: {result.error}"
        assert 1 <= result.elapsed_ms < 1500
        assert result.trigger_name == "Fortnite"
        assert live_hits == []
        assert live_guard.is_healthy() is True
    finally:
        live_guard.close()


def test_layer5_official_launcher_uri_validation_and_detached_riot(tmp_path: Path) -> None:
    riot_exe = tmp_path / "RiotClientServices.exe"
    riot_exe.write_bytes(b"MZ")
    riot_target = LaunchTarget("riot_client", f"{riot_exe}|valorant|live")
    validated = validate_launch_target(riot_target)
    assert isinstance(validated, tuple)
    assert validated[0] == riot_exe
    assert validated[1] == ("--launch-product=valorant", "--launch-patchline=live")

    detached_calls: list[tuple[Path, tuple[str, ...]]] = []
    launcher = WindowsLauncher(
        open_uri=lambda _u: None,
        spawn_detached=lambda p, a: (detached_calls.append((p, a)) or None),
    )
    res = launcher.launch("g-val", riot_target, "att-1")
    assert res.accepted is True
    assert detached_calls == [(riot_exe, ("--launch-product=valorant", "--launch-patchline=live"))]

    for kind, uri in (
        ("steam_uri", "steam://rungameid/730"),
        ("epic_uri", "com.epicgames.launcher://apps/fn%3A4fe75%3AFortnite?action=launch&silent=true"),
        ("ubisoft_uri", "uplay://launch/65043/0"),
        ("gog_uri", "goggalaxy://openGameView/1207658924"),
        ("ea_uri", "link2ea://launchgame/12345"),
        ("battlenet_uri", "battlenet://Pro"),
        ("xbox_uri", r"shell:AppsFolder\Microsoft.SeaofThieves_8wekyb3d8bbwe!App"),
    ):
        assert validate_launch_target(LaunchTarget(kind, uri)) is not None


def test_schema_v5_migrates_to_v6_with_backup_and_preserves_fks(tmp_path: Path) -> None:
    db_path = tmp_path / "gamehub.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for step, statements in enumerate(
            (INITIAL_SCHEMA, SCREENSHOT_SCHEMA, NOTE_SCHEMA, CONTROLS_SCHEMA, PROTECTION_SCHEMA),
            start=1,
        ):
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {step}")
        conn.execute(
            "INSERT INTO games (id, source, source_id, name, added_at, protection_mode) "
            "VALUES ('g1', 'steam', '730', 'CS2', 1000, 'strict')"
        )
        conn.execute(
            "INSERT INTO pending_notes (id, game_id, launched_at) VALUES ('p1', 'g1', 2000)"
        )
        conn.commit()
    finally:
        conn.close()

    db = Database(db_path)
    assert (tmp_path / "gamehub.db-v5.bak").is_file()
    with db.read() as rconn:
        assert rconn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert rconn.execute("PRAGMA foreign_key_check").fetchone() is None
        row = rconn.execute("SELECT name, protection_mode, custom_cover FROM games WHERE id='g1'").fetchone()
        assert (row["name"], row["protection_mode"], row["custom_cover"]) == ("CS2", "strict", 0)
        assert rconn.execute("SELECT COUNT(*) FROM pending_notes WHERE game_id='g1'").fetchone()[0] == 1
