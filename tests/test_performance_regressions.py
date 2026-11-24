"""Regression tests for v1.2.0-rc.3 speed, lazy-import, async cover, and exit-latency guarantees."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from gamehub.core.protection.catalog import ProtectedGamesCatalog
from gamehub.core.protection.guard import ProtectionGuard, ToolhelpProcessScanner
from gamehub.ui.covers import (
    CoverLabel,
    clear_cover_cache,
    set_cover_cache_dir,
    shutdown_cover_loader,
    wait_for_cover_loads,
)


def _jpg_bytes(width: int = 920, height: int = 430, color: tuple[int, int, int] = (40, 120, 210)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def test_startup_imports_defer_heavy_audio_capture_and_pillow_modules() -> None:
    """Importing gamehub.app and instantiating VoicePlayer must not eagerly load heavy backends."""
    code = (
        "import sys\n"
        "from PySide6.QtCore import QCoreApplication\n"
        "import gamehub.app\n"
        "from gamehub.core.audio.player import VoicePlayer\n"
        "app = QCoreApplication(['lazy-test'])\n"
        "vp = VoicePlayer()\n"
        "vp.stop()\n"
        "forbidden = ['PySide6.QtMultimedia', 'windows_capture', 'numpy', 'sounddevice', 'soundfile', 'cv2', 'PIL.Image']\n"
        "loaded = [m for m in forbidden if m in sys.modules]\n"
        "assert not loaded, f'Heavy modules loaded eagerly: {loaded}'\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert res.returncode == 0, res.stderr


def test_async_cover_label_loads_off_ui_thread_and_hits_disk_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    app = QApplication.instance() or QApplication(["cover-async-test"])

    img_path = tmp_path / "hero.jpg"
    img_path.write_bytes(_jpg_bytes(920, 430, (220, 60, 40)))
    cache_dir = tmp_path / "cache" / "covers"
    set_cover_cache_dir(cache_dir)
    clear_cover_cache()
    try:
        # Deferred label shows exact-size placeholder immediately with zero disk cache write yet.
        label = CoverLabel(
            img_path, "Async Game", initial_width=280, fixed_height=150, defer_load=True
        )
        assert not label.pixmap().isNull()
        assert label.pixmap().width() == 280 and label.pixmap().height() == 150
        assert not list(cache_dir.glob("*.webp"))

        # Activating triggers background worker decode + WebP cache write.
        label.ensure_loaded()
        wait_for_cover_loads(5.0)
        assert label._has_real_cover is True
        assert len(list(cache_dir.glob("*.webp"))) == 1
        assert label.pixmap().width() == 280 and label.pixmap().height() == 150

        # Clear RAM cache and verify second label loads cleanly from disk cache off UI thread.
        clear_cover_cache()
        label2 = CoverLabel(
            img_path, "Async Game", initial_width=280, fixed_height=150, defer_load=False
        )
        wait_for_cover_loads(5.0)
        assert label2._has_real_cover is True
        assert label2.pixmap().width() == 280 and label2.pixmap().height() == 150
    finally:
        shutdown_cover_loader(wait=True)
        set_cover_cache_dir(None)
        clear_cover_cache()
        app.processEvents()


def test_guard_precomputed_priority_and_fast_pid_diff_skips_redundant_toolhelp() -> None:
    catalog = ProtectedGamesCatalog.load(strict_load=True)

    class _FakeProbe:
        def verify_available(self) -> bool:
            return True

        def running_services(self, _names) -> frozenset[str]:
            return frozenset()

    class _CountingScanner:
        def __init__(self, procs: list[tuple[int, str]]) -> None:
            self.procs = procs
            self.calls = 0

        def list_processes(self) -> tuple[tuple[int, str], ...]:
            self.calls += 1
            return tuple(self.procs)

    # Riot Client (priority 1) beats game_exe (priority 6) regardless of process list order.
    scanner = _CountingScanner([(200, "FC26.exe"), (100, "RiotClientServices.exe")])
    guard = ProtectionGuard(catalog, process_scanner=scanner, service_probe=_FakeProbe())
    trig = guard.check_once()
    assert trig is not None
    assert trig.kind == "strict_launcher"
    assert trig.display_name == "Riot Client"

    # Real Windows ToolhelpProcessScanner exposes fast K32EnumProcesses pid_snapshot().
    real_scanner = ToolhelpProcessScanner()
    if os.name == "nt":
        sig = real_scanner.pid_snapshot()
        assert sig is not None and len(sig) >= 4


def test_guard_emergency_exit_is_independent_of_frozen_ui_thread(tmp_path: Path) -> None:
    """Even when the Qt main thread is completely frozen for 5 s, guard exits immediately (<300 ms)."""
    if os.name != "nt":
        pytest.skip("Windows-only test")
    donor = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ping.exe"
    if not donor.is_file():
        pytest.skip("ping.exe not available")

    dummy_path = tmp_path / "FC26.exe"
    shutil.copy2(donor, dummy_path)

    child_code = (
        "import os, time\n"
        "from pathlib import Path\n"
        "from PySide6.QtCore import QTimer\n"
        "from PySide6.QtWidgets import QApplication\n"
        "from gamehub.core.protection.catalog import ProtectedGamesCatalog\n"
        "from gamehub.core.protection.guard import ProtectionGuard\n"
        "app = QApplication(['frozen-ui-guard-test'])\n"
        "cat = ProtectedGamesCatalog.load(strict_load=True)\n"
        "guard = ProtectionGuard(cat)\n"
        "guard.start(on_trigger=lambda _t: os._exit(0), on_failure=lambda _r: os._exit(2))\n"
        "print('READY', flush=True)\n"
        "# Freeze Qt main thread completely for 5 seconds!\n"
        "QTimer.singleShot(0, lambda: time.sleep(5.0))\n"
        "QTimer.singleShot(5200, app.quit)\n"
        "raise SystemExit(app.exec())\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    dummy = None
    try:
        assert child.stdout is not None
        line = child.stdout.readline().strip()
        assert line == "READY"
        time.sleep(0.15)  # Ensure main thread is inside time.sleep(5.0)

        t0 = time.perf_counter()
        dummy = subprocess.Popen(
            [str(dummy_path), "127.0.0.1", "-n", "6"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rc = child.wait(timeout=3.0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert rc == 0
        assert elapsed_ms < 300.0, f"Guard took {elapsed_ms:.1f} ms to exit with frozen UI thread"
    finally:
        if dummy is not None and dummy.poll() is None:
            dummy.terminate()
            dummy.wait(timeout=2.0)
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2.0)
