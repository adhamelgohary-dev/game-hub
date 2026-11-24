"""Reproducible performance, memory, and anti-cheat exit-latency benchmark for GameRewind.

Measures:
  1. Frozen GameRewind.exe startup (cold cover cache + warm, 10 runs each)
  2. In-process Qt UI timings for 20-game & 100-game library draw (cold + warm cover cache),
     Game Page, Settings, Translations & Mods, and 100-game scroll RAM (median of 10 runs)
  3. Frozen GameRewind.exe idle RAM & CPU over 60 seconds + library scroll RAM
  4. Frozen GameRewind.exe exit latency (40 trials each) for Fortnite, Valorant, EA SPORTS FC
     (plus optional under-UI-load stress trials)
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


# ── Win32 helpers (zero psutil, public APIs only) ──────────────────────────
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)

_WM_CLOSE = 0x0010
_WM_MOUSEWHEEL = 0x020A
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_VM_READ = 0x0010


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
    ctypes.POINTER(_FILETIME),
]
_kernel32.GetProcessTimes.restype = wintypes.BOOL
_psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX),
    wintypes.DWORD,
]
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


def _find_visible_window(pid: int, title_prefix: str = "GameRewind") -> int | None:
    found: list[int] = []

    def _cb(hwnd: int, _lparam: int) -> bool:
        wpid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        if not _user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(128)
        _user32.GetWindowTextW(hwnd, buf, 128)
        if not buf.value.startswith(title_prefix):
            return True
        rect = _RECT()
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            if (rect.right - rect.left) > 100 and (rect.bottom - rect.top) > 100:
                found.append(hwnd)
                return False
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return found[0] if found else None


def _get_memory_mb(pid: int) -> tuple[float, float]:
    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_VM_READ, False, pid)
    if not h:
        return (0.0, 0.0)
    try:
        pmc = _PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(pmc)
        if _psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return (
                round(pmc.WorkingSetSize / (1024 * 1024), 2),
                round(pmc.PrivateUsage / (1024 * 1024), 2),
            )
        return (0.0, 0.0)
    finally:
        _kernel32.CloseHandle(h)


def _get_cpu_seconds(pid: int) -> float:
    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return 0.0
    try:
        ct, et, kt, ut = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        if _kernel32.GetProcessTimes(
            h, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut)
        ):
            k = (kt.dwHighDateTime << 32) | kt.dwLowDateTime
            u = (ut.dwHighDateTime << 32) | ut.dwLowDateTime
            return (k + u) / 10_000_000.0
        return 0.0
    finally:
        _kernel32.CloseHandle(h)


def _close_process(proc: subprocess.Popen, hwnd: int | None) -> None:
    if hwnd:
        _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3.0)


def _stats(values: list[float]) -> dict[str, float]:
    s = sorted(values)
    n = len(s)
    p95_idx = min(n - 1, max(0, math.ceil(0.95 * n) - 1))
    return {
        "n": n,
        "min": round(s[0], 2),
        "median": round(statistics.median(s), 2),
        "avg": round(statistics.mean(s), 2),
        "p95": round(s[p95_idx], 2),
        "max": round(s[-1], 2),
    }


def bench_startup(
    exe: Path,
    *,
    runs: int = 10,
    clear_cover_cache_dir: Path | None = None,
) -> dict:
    times_ms: list[float] = []
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)

    for _ in range(runs):
        if clear_cover_cache_dir is not None and clear_cover_cache_dir.exists():
            shutil.rmtree(clear_cover_cache_dir, ignore_errors=True)

        t0 = time.perf_counter()
        proc = subprocess.Popen([str(exe)], env=env)
        hwnd = None
        deadline = t0 + 30.0
        while time.perf_counter() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"GameRewind exited early with code {proc.returncode}")
            hwnd = _find_visible_window(proc.pid)
            if hwnd is not None:
                break
            time.sleep(0.002)
        t_vis = time.perf_counter()
        if hwnd is None:
            _close_process(proc, None)
            raise RuntimeError("GameRewind main window did not appear within 30s")
        times_ms.append((t_vis - t0) * 1000.0)
        time.sleep(0.20)
        _close_process(proc, hwnd)
        time.sleep(0.15)

    res = _stats(times_ms)
    res["run1_ms"] = round(times_ms[0], 2)
    res["raw_ms"] = [round(x, 2) for x in times_ms]
    return res


def bench_idle_and_scroll(exe: Path, idle_sec: int = 60) -> dict:
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)

    proc = subprocess.Popen([str(exe)], env=env)
    hwnd = None
    deadline = time.perf_counter() + 30.0
    while time.perf_counter() < deadline:
        hwnd = _find_visible_window(proc.pid)
        if hwnd is not None:
            break
        time.sleep(0.01)
    if hwnd is None:
        _close_process(proc, None)
        raise RuntimeError("Window failed to appear for idle test")

    # Wait 5s for startup refresh to finish settling
    time.sleep(5.0)
    ws_start, priv_start = _get_memory_mb(proc.pid)
    cpu_start = _get_cpu_seconds(proc.pid)
    t_start = time.perf_counter()
    time.sleep(idle_sec)
    t_end = time.perf_counter()
    cpu_end = _get_cpu_seconds(proc.pid)
    ws_end, priv_end = _get_memory_mb(proc.pid)

    # Scroll library actively on the live frozen window and measure RAM after scrolling
    rect = _RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2
    lparam = ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)
    for delta in [-120] * 30 + [120] * 30:
        wparam = (delta & 0xFFFF) << 16
        _user32.PostMessageW(hwnd, _WM_MOUSEWHEEL, wparam, lparam)
        time.sleep(0.04)
    time.sleep(1.0)
    ws_scroll, priv_scroll = _get_memory_mb(proc.pid)
    _close_process(proc, hwnd)

    wall = t_end - t_start
    cpu_delta = max(0.0, cpu_end - cpu_start)
    cpu_pct_one_core = round((cpu_delta / wall) * 100.0, 3)
    cpu_count = os.cpu_count() or 1
    cpu_pct_total = round(cpu_pct_one_core / cpu_count, 3)

    return {
        "idle_window_sec": round(wall, 2),
        "idle_cpu_seconds": round(cpu_delta, 4),
        "idle_cpu_pct_one_core": cpu_pct_one_core,
        "idle_cpu_pct_system": cpu_pct_total,
        "idle_ram_start_ws_mb": ws_start,
        "idle_ram_start_private_mb": priv_start,
        "idle_ram_60s_ws_mb": ws_end,
        "idle_ram_60s_private_mb": priv_end,
        "after_scroll_ws_mb": ws_scroll,
        "after_scroll_private_mb": priv_scroll,
    }


def bench_exit_latency(
    exe: Path,
    dummy_exe_name: str,
    *,
    trials: int = 40,
    ui_load: bool = False,
) -> dict:
    donor = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ping.exe"
    if not donor.is_file():
        raise FileNotFoundError(f"Donor binary not found: {donor}")

    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    latencies_ms: list[float] = []
    timeouts = 0
    with TemporaryDirectory(prefix="gr-bench-dummy-") as tmp:
        dummy_path = Path(tmp) / dummy_exe_name
        shutil.copy2(donor, dummy_path)

        for trial in range(trials):
            proc = subprocess.Popen([str(exe)], env=env)
            hwnd = None
            deadline = time.perf_counter() + 30.0
            while time.perf_counter() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"GameRewind exited before dummy launch on trial {trial} (rc={proc.returncode})"
                    )
                hwnd = _find_visible_window(proc.pid)
                if hwnd is not None:
                    break
                time.sleep(0.005)
            if hwnd is None:
                _close_process(proc, None)
                raise RuntimeError(f"Window not visible on trial {trial}")

            # Wait for event loop & guard thread to be active
            time.sleep(0.85)
            lparam = 0
            if ui_load:
                rect = _RECT()
                _user32.GetWindowRect(hwnd, ctypes.byref(rect))
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                lparam = ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)
                for _ in range(12):
                    _user32.PostMessageW(hwnd, _WM_MOUSEWHEEL, ((-120) & 0xFFFF) << 16, lparam)

            t0 = time.perf_counter()
            dummy = subprocess.Popen(
                [str(dummy_path), "127.0.0.1", "-n", "6"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            try:
                wait_deadline = t0 + 5.0
                while proc.poll() is None and time.perf_counter() < wait_deadline:
                    if ui_load:
                        _user32.PostMessageW(hwnd, _WM_MOUSEWHEEL, ((-120) & 0xFFFF) << 16, lparam)
                    time.sleep(0.001)
                t_exit = time.perf_counter()
                if proc.poll() is None:
                    timeouts += 1
                    print(
                        f"  [WARN] trial {trial} ({dummy_exe_name}) TIMEOUT >5s "
                        f"(dummy_poll={dummy.poll()})",
                        flush=True,
                    )
                    _close_process(proc, hwnd)
                    latencies_ms.append(5000.0)
                else:
                    latencies_ms.append((t_exit - t0) * 1000.0)
            finally:
                if dummy.poll() is None:
                    dummy.terminate()
                    try:
                        dummy.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        dummy.kill()
                        dummy.wait(timeout=2.0)
            if (trial + 1) % 10 == 0:
                print(
                    f"  {dummy_exe_name} ({'load' if ui_load else 'normal'}): "
                    f"{trial + 1}/{trials} done (last={latencies_ms[-1]:.1f} ms)",
                    flush=True,
                )
            time.sleep(0.10)

    res = _stats(latencies_ms)
    res["dummy_exe"] = dummy_exe_name
    res["ui_load"] = ui_load
    res["timeouts"] = timeouts
    res["raw_ms"] = [round(x, 2) for x in latencies_ms]
    return res


def bench_ui_operations(runs: int = 10) -> dict:
    """Measure exact Qt UI timings (library draw 20/100 cold+warm, game page, settings, mods, scroll RAM)."""
    from PySide6.QtWidgets import QApplication

    from gamehub.app import GameHubWindow
    from gamehub.core.protection.catalog import ProtectedGamesCatalog
    from gamehub.core.settings import SettingsService
    from gamehub.core.storage.controls import ControlsRepository
    from gamehub.core.storage.db import Database
    from gamehub.core.storage.library import LibraryRepository
    from gamehub.core.storage.memory import MemoryRepository
    from gamehub.modules.mods.engine import ModsEngine
    from gamehub.ui.covers import clear_cover_cache, set_cover_cache_dir
    from gamehub.ui.theme import apply_theme

    app = QApplication.instance() or QApplication(["GameRewind-Bench"])
    apply_theme(app, "dark")

    results: dict[str, dict] = {}
    with TemporaryDirectory(prefix="gr-ui-bench-") as tmp_str:
        tmp = Path(tmp_str)
        covers_dir = tmp / "covers"
        covers_dir.mkdir()
        games_dir = tmp / "games"
        games_dir.mkdir()

        def _make_games(n: int) -> tuple[Database, LibraryRepository, Path]:
            root = tmp / f"profile_{n}"
            if root.exists():
                shutil.rmtree(root)
            root.mkdir()
            db = Database(root / "gamehub.db")
            repo = LibraryRepository(db)
            for i in range(n):
                cf = covers_dir / f"c_{i:03d}.jpg"
                if not cf.is_file():
                    Image.new("RGB", (920, 430), ((i * 29) % 255, (i * 53) % 255, (i * 97) % 255)).save(
                        cf, "JPEG", quality=85
                    )
                gd = games_dir / f"g_{i:03d}"
                gd.mkdir(exist_ok=True)
                exe = gd / f"UI_Bench_Game_{i + 1:03d}.exe"
                if not exe.is_file():
                    exe.write_bytes(b"MZ" + b"\x00" * 64)
                gid = repo.add_manual(exe)
                with db.write() as conn:
                    conn.execute(
                        "UPDATE games SET name = ?, cover_path = ?, custom_cover = 1 WHERE id = ?",
                        (f"UI Bench Game {i + 1:03d}", str(cf), gid),
                    )
            return db, repo, root

        def _pump_until_covers_loaded(window: GameHubWindow, timeout: float = 15.0) -> None:
            app.processEvents()
            wait_fn = getattr(window.library, "wait_for_visible_covers", None)
            if callable(wait_fn):
                wait_fn(timeout)
            app.processEvents()

        for count in (20, 100):
            db, repo, root = _make_games(count)
            games = repo.list_games()
            cache_dir = root / "cache" / "covers"

            cold_times: list[float] = []
            for _ in range(runs):
                if cache_dir.exists():
                    shutil.rmtree(cache_dir)
                clear_cover_cache()
                set_cover_cache_dir(cache_dir)
                win = GameHubWindow(app)
                win.show()
                app.processEvents()
                t0 = time.perf_counter()
                win.library.present_games(games)
                _pump_until_covers_loaded(win)
                cold_times.append((time.perf_counter() - t0) * 1000.0)
                win.close()
                app.processEvents()
            results[f"library_draw_{count}_cold"] = _stats(cold_times)

            warm_times: list[float] = []
            set_cover_cache_dir(cache_dir)
            for _ in range(runs):
                clear_cover_cache()
                win = GameHubWindow(app)
                win.show()
                app.processEvents()
                t0 = time.perf_counter()
                win.library.present_games(games)
                _pump_until_covers_loaded(win)
                warm_times.append((time.perf_counter() - t0) * 1000.0)
                win.close()
                app.processEvents()
            results[f"library_draw_{count}_warm_disk"] = _stats(warm_times)

            if count == 100:
                # Scroll 100-game library and record process RAM before/after
                win = GameHubWindow(app)
                win.show()
                win.library.present_games(games)
                _pump_until_covers_loaded(win)
                ws_b, priv_b = _get_memory_mb(os.getpid())
                sb = win.library._scroll.verticalScrollBar()
                step = max(1, sb.maximum() // 25)
                for pos in range(0, sb.maximum() + 1, step):
                    sb.setValue(pos)
                    app.processEvents()
                _pump_until_covers_loaded(win)
                ws_a, priv_a = _get_memory_mb(os.getpid())
                results["scroll_100_ram"] = {
                    "before_ws_mb": ws_b,
                    "before_private_mb": priv_b,
                    "after_ws_mb": ws_a,
                    "after_private_mb": priv_a,
                }
                win.close()
                app.processEvents()

        # Page navigation timings (20-game profile)
        db, repo, root = _make_games(20)
        games = repo.list_games()
        controls = ControlsRepository(db, root)
        memory = MemoryRepository(db, root)
        settings_svc = SettingsService(db)
        catalog = ProtectedGamesCatalog.load(strict_load=True)
        mods_engine = ModsEngine(db, root, repo, catalog, is_any_game_running=lambda: False)
        set_cover_cache_dir(root / "cache" / "covers")
        win = GameHubWindow(app)
        win.show()
        win.library.present_games(games)
        _pump_until_covers_loaded(win)

        game_page_ms: list[float] = []
        settings_ms: list[float] = []
        mods_ms: list[float] = []

        for i in range(runs):
            win.show_library()
            app.processEvents()
            gid = games[i % len(games)].id

            t0 = time.perf_counter()
            g = repo.get_game(gid)
            citems = controls.list_controls(gid)
            page = memory.timeline(gid)
            win.game_page.show_game(g, citems, page, auto_strict=False)
            state = mods_engine.get_state(gid)
            win.game_page.mods_panel.present_state(state)
            win.show_game_page()
            app.processEvents()
            game_page_ms.append((time.perf_counter() - t0) * 1000.0)

            t0 = time.perf_counter()
            snap = settings_svc.read()
            win.settings_view.load_settings(snap, root)
            win.settings_view.set_protected_games([])
            win.settings_view.set_scan_folders(repo.list_scan_folders())
            win.show_settings()
            app.processEvents()
            settings_ms.append((time.perf_counter() - t0) * 1000.0)

            t0 = time.perf_counter()
            all_games = repo.list_games()
            rows = [(gm, mods_engine.is_game_protected(gm)[0]) for gm in all_games]
            win.mods_view.set_games(rows)
            win.show_mods()
            app.processEvents()
            mods_ms.append((time.perf_counter() - t0) * 1000.0)

        win.close()
        app.processEvents()
        results["open_game_page"] = _stats(game_page_ms)
        results["open_settings"] = _stats(settings_ms)
        results["open_mods"] = _stats(mods_ms)

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=REPO_ROOT / "dist" / "GameRewind" / "GameRewind.exe")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--idle-sec", type=int, default=60)
    parser.add_argument("--include-ui-load-exit", action="store_true")
    args = parser.parse_args()

    exe = args.exe.resolve()
    if not exe.is_file():
        raise FileNotFoundError(f"Frozen exe not found: {exe}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "exe": str(exe),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    dist_dir = exe.parent
    total_bytes = sum(p.stat().st_size for p in dist_dir.rglob("*") if p.is_file())
    report["installed_folder_bytes"] = total_bytes
    report["installed_folder_mib"] = round(total_bytes / (1024 * 1024), 2)

    def _save() -> None:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("[1/4] Benchmarking UI operations (20/100 library draw, game page, settings, mods)...", flush=True)
    report["ui_operations"] = bench_ui_operations(runs=args.runs)
    _save()

    real_cover_cache = Path(os.environ.get("LOCALAPPDATA", "")) / "GameRewind" / "cache" / "covers"
    print(f"[2/4] Benchmarking frozen startup ({args.runs} runs cold cover cache + {args.runs} runs warm)...", flush=True)
    report["startup_frozen_cold_cache"] = bench_startup(
        exe, runs=args.runs, clear_cover_cache_dir=real_cover_cache if real_cover_cache.parent.exists() else None
    )
    _save()
    report["startup_frozen_warm"] = bench_startup(exe, runs=args.runs)
    _save()

    print(f"[3/4] Benchmarking frozen idle RAM & CPU ({args.idle_sec}s) + scroll RAM...", flush=True)
    report["idle_and_scroll"] = bench_idle_and_scroll(exe, idle_sec=args.idle_sec)
    _save()

    print(f"[4/4] Benchmarking frozen exit latency ({args.trials} trials each: Fortnite, Valorant, EA SPORTS FC)...", flush=True)
    report["exit_latency"] = {
        "fortnite": bench_exit_latency(exe, "FortniteLauncher.exe", trials=args.trials),
        "valorant": bench_exit_latency(exe, "VALORANT.exe", trials=args.trials),
        "ea_fc": bench_exit_latency(exe, "FC26.exe", trials=args.trials),
    }
    _save()

    if args.include_ui_load_exit:
        print(f"[5/5] Benchmarking frozen exit latency UNDER UI LOAD ({args.trials} trials each)...", flush=True)
        report["exit_latency_under_load"] = {
            "fortnite": bench_exit_latency(
                exe, "FortniteLauncher.exe", trials=args.trials, ui_load=True
            ),
            "valorant": bench_exit_latency(
                exe, "VALORANT.exe", trials=args.trials, ui_load=True
            ),
            "ea_fc": bench_exit_latency(
                exe, "FC26.exe", trials=args.trials, ui_load=True
            ),
        }
        _save()

    print(f"Benchmark written to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
