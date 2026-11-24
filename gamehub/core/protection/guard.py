"""Zero-Presence fail-closed protection guard (Layers 2, 3, 4 & 7).

Uses ONLY passive CreateToolhelp32Snapshot process basenames and read-only
Windows Service Control Manager (SCM) status queries. Never opens process handles,
never reads memory, never injects, and fails closed on any catalog, SCM,
snapshot, or watchdog error.
"""

from __future__ import annotations

import ctypes
import logging
import ntpath
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from time import monotonic
from typing import Protocol

from gamehub.core.protection.catalog import ProtectedGamesCatalog

LOGGER = logging.getLogger(__name__)

DEFAULT_GUARD_INTERVAL_SEC = 0.30
DEFAULT_WATCHDOG_STALE_SEC = 2.5

# Win32 Service Control Manager read-only constants
_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SC_STATUS_PROCESS_INFO = 0
_SERVICE_START_PENDING = 0x00000002
_SERVICE_RUNNING = 0x00000004
_ERROR_SERVICE_DOES_NOT_EXIST = 1060

# Toolhelp32 constants (basename-only, zero process handles)
_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_NO_MORE_FILES = 18

LAUNCHER_DISPLAY_NAMES: dict[str, str] = {
    "riot": "Riot Client",
    "epic": "Epic Games Launcher",
    "ea": "EA app",
    "battlenet": "Battle.net",
    "ubisoft": "Ubisoft Connect",
    "steam": "Steam",
}


class ProtectionCheckError(RuntimeError):
    """Raised when protection cannot verify the system state safely (triggers fail-closed exit)."""


@dataclass(frozen=True, slots=True)
class ProtectionTrigger:
    kind: str  # "strict_launcher" | "launcher_stage" | "anti_cheat_exe" | "game_exe" | "anti_cheat_service"
    identifier: str
    display_name: str
    stage: str
    entry_id: str | None = None


class ProcessScanner(Protocol):
    """Return running `(pid, lowercase_basename)` pairs without opening any process handles."""

    def list_processes(self) -> tuple[tuple[int, str], ...]: ...


class ServiceProbe(Protocol):
    """Read-only Service Control Manager probe for on-demand anti-cheat services."""

    def verify_available(self) -> bool: ...

    def running_services(self, service_names: Sequence[str]) -> frozenset[str]: ...


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    )


class _ServiceStatusProcess(ctypes.Structure):
    _fields_ = (
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwServiceFlags", wintypes.DWORD),
    )


class ToolhelpProcessScanner:
    """Passive Toolhelp32 process basename enumeration — zero process handles."""

    def __init__(self) -> None:
        if os.name != "nt":
            self._kernel = None
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel = kernel
        self._snapshot = kernel.CreateToolhelp32Snapshot
        self._snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._snapshot.restype = wintypes.HANDLE
        self._first = kernel.Process32FirstW
        self._next = kernel.Process32NextW
        for fn in (self._first, self._next):
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
            fn.restype = wintypes.BOOL
        self._close = kernel.CloseHandle
        self._close.argtypes = [wintypes.HANDLE]
        self._close.restype = wintypes.BOOL

    def list_processes(self) -> tuple[tuple[int, str], ...]:
        if self._kernel is None:
            return ()
        snap = self._snapshot(_TH32CS_SNAPPROCESS, 0)
        if snap == _INVALID_HANDLE_VALUE:
            raise ProtectionCheckError(
                f"CreateToolhelp32Snapshot failed (winerror={ctypes.get_last_error()})"
            )
        results: list[tuple[int, str]] = []
        try:
            entry = _ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = self._first(snap, ctypes.byref(entry))
            while ok:
                if entry.th32ProcessID > 0 and entry.szExeFile:
                    results.append((int(entry.th32ProcessID), ntpath.normcase(entry.szExeFile)))
                ok = self._next(snap, ctypes.byref(entry))
            err = ctypes.get_last_error()
            if err != _ERROR_NO_MORE_FILES:
                raise ProtectionCheckError(f"Process32NextW failed (winerror={err})")
        finally:
            self._close(snap)
        return tuple(results)


class WindowsServiceProbe:
    """Read-only Windows SCM query (`SC_MANAGER_CONNECT` + `SERVICE_QUERY_STATUS`)."""

    def __init__(self) -> None:
        if os.name != "nt":
            self._advapi = None
            return
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._advapi = advapi
        self._open_scm = advapi.OpenSCManagerW
        self._open_scm.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        self._open_scm.restype = wintypes.HANDLE
        self._open_svc = advapi.OpenServiceW
        self._open_svc.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
        self._open_svc.restype = wintypes.HANDLE
        self._query_ex = advapi.QueryServiceStatusEx
        self._query_ex.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._query_ex.restype = wintypes.BOOL
        self._close_svc = advapi.CloseServiceHandle
        self._close_svc.argtypes = [wintypes.HANDLE]
        self._close_svc.restype = wintypes.BOOL

    def verify_available(self) -> bool:
        if self._advapi is None:
            return True
        scm = self._open_scm(None, None, _SC_MANAGER_CONNECT)
        if not scm:
            return False
        self._close_svc(scm)
        return True

    def running_services(self, service_names: Sequence[str]) -> frozenset[str]:
        if self._advapi is None or not service_names:
            return frozenset()
        scm = self._open_scm(None, None, _SC_MANAGER_CONNECT)
        if not scm:
            raise ProtectionCheckError(
                f"OpenSCManagerW failed (winerror={ctypes.get_last_error()})"
            )
        running: set[str] = set()
        try:
            for name in service_names:
                svc = self._open_svc(scm, name, _SERVICE_QUERY_STATUS)
                if not svc:
                    err = ctypes.get_last_error()
                    if err == _ERROR_SERVICE_DOES_NOT_EXIST:
                        continue
                    # ACCESS_DENIED or transient SCM error on a known service -> fail-closed
                    raise ProtectionCheckError(
                        f"OpenServiceW({name}) failed (winerror={err})"
                    )
                try:
                    status = _ServiceStatusProcess()
                    needed = wintypes.DWORD(0)
                    ok = self._query_ex(
                        svc,
                        _SC_STATUS_PROCESS_INFO,
                        ctypes.byref(status),
                        ctypes.sizeof(status),
                        ctypes.byref(needed),
                    )
                    if not ok:
                        raise ProtectionCheckError(
                            f"QueryServiceStatusEx({name}) failed (winerror={ctypes.get_last_error()})"
                        )
                    if status.dwCurrentState in {_SERVICE_RUNNING, _SERVICE_START_PENDING}:
                        running.add(name)
                finally:
                    self._close_svc(svc)
        finally:
            self._close_svc(scm)
        return frozenset(running)


class ProtectionGuard:
    """Fast, fail-closed, order-independent Zero-Presence protection monitor."""

    def __init__(
        self,
        catalog: ProtectedGamesCatalog,
        *,
        process_scanner: ProcessScanner | None = None,
        service_probe: ServiceProbe | None = None,
        enabled_optional_launchers: Iterable[str] = (),
        disabled_entry_ids: Iterable[str] = (),
        interval_sec: float = DEFAULT_GUARD_INTERVAL_SEC,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._catalog = catalog
        self._scanner = process_scanner if process_scanner is not None else ToolhelpProcessScanner()
        self._service_probe = service_probe if service_probe is not None else WindowsServiceProbe()
        self._interval = max(0.05, float(interval_sec))
        self._clock = clock

        self._config_lock = Lock()
        self._scan_lock = Lock()
        self._enabled_optional_launchers: frozenset[str] = frozenset(
            k.strip().lower() for k in enabled_optional_launchers if k.strip()
        )
        self._disabled_entry_ids: frozenset[str] = frozenset(
            e.strip() for e in disabled_entry_ids if e.strip()
        )
        self._ignored_pids: set[int] = set()

        self._stop = Event()
        self._thread: Thread | None = None
        self._heartbeat_lock = Lock()
        self._last_heartbeat: float = 0.0
        self._failed_reason: str | None = None
        self._triggered: ProtectionTrigger | None = None

    def update_policy(
        self,
        *,
        enabled_optional_launchers: Iterable[str] | None = None,
        disabled_entry_ids: Iterable[str] | None = None,
    ) -> None:
        with self._config_lock:
            if enabled_optional_launchers is not None:
                self._enabled_optional_launchers = frozenset(
                    k.strip().lower() for k in enabled_optional_launchers if k.strip()
                )
            if disabled_entry_ids is not None:
                self._disabled_entry_ids = frozenset(
                    e.strip() for e in disabled_entry_ids if e.strip()
                )

    def ignore_pid(self, pid: int) -> None:
        """Temporarily exempt only a self-test dummy child PID owned by the Test Protection button."""
        with self._config_lock:
            self._ignored_pids.add(int(pid))

    def unignore_pid(self, pid: int) -> None:
        with self._config_lock:
            self._ignored_pids.discard(int(pid))

    def self_check(self) -> ProtectionTrigger | None:
        """Run mandatory startup self-test before showing any window.

        Raises ProtectionCheckError if catalog or SCM probe is broken (fail-closed).
        Returns a ProtectionTrigger if a protected game, anti-cheat, or Riot Client is already active.
        """
        if not self._catalog.entries:
            raise ProtectionCheckError("protected_catalog_empty")
        if not self._service_probe.verify_available():
            raise ProtectionCheckError("service_probe_unavailable")
        return self.check_once()

    def check_once(self) -> ProtectionTrigger | None:
        """Evaluate running processes and on-demand anti-cheat services synchronously."""
        with self._scan_lock:
            return self._check_once_locked()

    def _check_once_locked(self) -> ProtectionTrigger | None:
        with self._config_lock:
            enabled_optional = self._enabled_optional_launchers
            disabled_entries = self._disabled_entry_ids
            ignored_pids = frozenset(self._ignored_pids)

        raw_procs = self._scanner.list_processes()
        basenames: set[str] = set()
        for pid, name in raw_procs:
            if pid in ignored_pids:
                continue
            basenames.add(ntpath.normcase(ntpath.basename(name)))

        # 1. Always-strict launchers (Riot Client — NEVER disableable)
        for launcher_key, exes in self._catalog.always_strict_launchers.items():
            for exe in exes:
                if exe in basenames:
                    return ProtectionTrigger(
                        kind="strict_launcher",
                        identifier=exe,
                        display_name=LAUNCHER_DISPLAY_NAMES.get(launcher_key, launcher_key),
                        stage="launcher",
                    )

        # 2. Optional strict launchers toggled ON by user
        for launcher_key in enabled_optional:
            for exe in self._catalog.optional_strict_launchers.get(launcher_key, ()):
                if exe in basenames:
                    return ProtectionTrigger(
                        kind="strict_launcher",
                        identifier=exe,
                        display_name=LAUNCHER_DISPLAY_NAMES.get(launcher_key, launcher_key),
                        stage="launcher",
                    )

        # 3. Earliest launcher-stage processes of protected games
        for entry in self._catalog.entries:
            if entry.id in disabled_entries:
                continue
            for exe in entry.launcher_stage_exes:
                if exe in basenames:
                    return ProtectionTrigger(
                        kind="launcher_stage",
                        identifier=exe,
                        display_name=entry.name,
                        stage="launcher_stage",
                        entry_id=entry.id,
                    )

        # 4. Global & per-game anti-cheat processes
        for exe in sorted(self._catalog.global_anti_cheat_exes):
            if exe in basenames:
                matched = self._catalog.match_exe_name(exe)
                return ProtectionTrigger(
                    kind="anti_cheat_exe",
                    identifier=exe,
                    display_name=matched.name if matched is not None else exe,
                    stage="anti_cheat",
                    entry_id=matched.id if matched is not None else None,
                )

        for entry in self._catalog.entries:
            if entry.id in disabled_entries:
                continue
            for exe in entry.anti_cheat_exes:
                if exe in basenames:
                    return ProtectionTrigger(
                        kind="anti_cheat_exe",
                        identifier=exe,
                        display_name=entry.name,
                        stage="anti_cheat",
                        entry_id=entry.id,
                    )

        # 5. Game executables of protected games
        for entry in self._catalog.entries:
            if entry.id in disabled_entries:
                continue
            for exe in entry.game_exes:
                if exe in basenames:
                    return ProtectionTrigger(
                        kind="game_exe",
                        identifier=exe,
                        display_name=entry.name,
                        stage="game",
                        entry_id=entry.id,
                    )

        # 6. Read-only SCM status of on-demand anti-cheat services
        running_svcs = self._service_probe.running_services(self._catalog.anti_cheat_services)
        if running_svcs:
            first_svc = min(running_svcs)
            return ProtectionTrigger(
                kind="anti_cheat_service",
                identifier=first_svc,
                display_name=first_svc,
                stage="anti_cheat_service",
            )

        return None

    def start(
        self,
        on_trigger: Callable[[ProtectionTrigger], None],
        on_failure: Callable[[str], None],
    ) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        with self._heartbeat_lock:
            self._last_heartbeat = self._clock()
            self._failed_reason = None
            self._triggered = None

        def _loop() -> None:
            try:
                while not self._stop.is_set():
                    started = self._clock()
                    trigger = self.check_once()
                    with self._heartbeat_lock:
                        self._last_heartbeat = self._clock()
                    if trigger is not None:
                        with self._heartbeat_lock:
                            self._triggered = trigger
                        LOGGER.info(
                            "protection_guard_triggered kind=%s stage=%s name=%s",
                            trigger.kind,
                            trigger.stage,
                            trigger.display_name,
                        )
                        on_trigger(trigger)
                        return
                    delay = max(0.0, self._interval - (self._clock() - started))
                    self._stop.wait(delay)
            except Exception as exc:  # noqa: BLE001 — fail-closed on ANY detector failure
                reason = f"{type(exc).__name__}: {exc}"
                with self._heartbeat_lock:
                    self._failed_reason = reason
                LOGGER.error("protection_guard_failed_closed")
                on_failure(reason)

        self._thread = Thread(target=_loop, name="protection-guard", daemon=True)
        self._thread.start()

    def is_healthy(self, max_stale_sec: float = DEFAULT_WATCHDOG_STALE_SEC) -> bool:
        """Called every second by the main-thread watchdog; False triggers fail-closed exit."""
        if self._stop.is_set():
            return True
        with self._heartbeat_lock:
            if self._triggered is not None:
                return True
            if self._failed_reason is not None:
                return False
            last = self._last_heartbeat
        if self._thread is None or not self._thread.is_alive():
            return False
        return (self._clock() - last) <= max_stale_sec

    @property
    def last_trigger(self) -> ProtectionTrigger | None:
        with self._heartbeat_lock:
            return self._triggered

    @property
    def failed_reason(self) -> str | None:
        with self._heartbeat_lock:
            return self._failed_reason

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)


def _benign_windows_donor_exe() -> Path | None:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    for name in ("ping.exe", "choice.exe", "whoami.exe"):
        candidate = system_root / "System32" / name
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    ok: bool
    elapsed_ms: int
    trigger_name: str
    error: str | None = None


def run_dummy_process_protection_test(
    catalog: ProtectedGamesCatalog,
    *,
    dummy_exe_name: str = "FortniteLauncher.exe",
    live_guard: ProtectionGuard | None = None,
    interval_sec: float = 0.15,
    timeout_sec: float = 3.0,
) -> SelfTestResult:
    """Spawn a harmless renamed Windows binary and verify real Toolhelp32 guard detection + latency."""
    donor = _benign_windows_donor_exe()
    if donor is None:
        return SelfTestResult(False, 0, dummy_exe_name, "donor_executable_missing")

    triggered_event = Event()
    detected: list[ProtectionTrigger] = []
    errors: list[str] = []
    target_pid: list[int | None] = [None]
    real_scanner = ToolhelpProcessScanner()

    class _ScopedRealScanner:
        def list_processes(self) -> tuple[tuple[int, str], ...]:
            pid = target_pid[0]
            if pid is None:
                return ()
            return tuple(item for item in real_scanner.list_processes() if item[0] == pid)

    test_guard = ProtectionGuard(
        catalog,
        process_scanner=_ScopedRealScanner(),
        interval_sec=interval_sec,
    )
    proc: subprocess.Popen | None = None
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with TemporaryDirectory(prefix="gamehub-prot-test-") as tmp:
            dummy_path = Path(tmp) / dummy_exe_name
            shutil.copy2(donor, dummy_path)

            test_guard.start(
                on_trigger=lambda trig: (detected.append(trig), triggered_event.set()),
                on_failure=lambda err: (errors.append(err), triggered_event.set()),
            )
            t0 = monotonic()
            # ping 127.0.0.1 -n 6 stays alive ~5 seconds cleanly without network I/O
            args = (
                [str(dummy_path), "127.0.0.1", "-n", "6"]
                if donor.name.lower() == "ping.exe"
                else [str(dummy_path)]
            )
            if live_guard is not None:
                with live_guard._scan_lock:
                    proc = subprocess.Popen(
                        args,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        creationflags=creation_flags,
                        shell=False,
                    )
                    live_guard.ignore_pid(proc.pid)
                    target_pid[0] = proc.pid
            else:
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=creation_flags,
                    shell=False,
                )
                target_pid[0] = proc.pid

            triggered_event.wait(timeout=timeout_sec)
            elapsed_ms = max(1, round((monotonic() - t0) * 1000))
            test_guard.close()

            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)

            if live_guard is not None:
                live_guard.unignore_pid(proc.pid)

            if errors:
                return SelfTestResult(False, elapsed_ms, dummy_exe_name, errors[0])
            if not detected:
                return SelfTestResult(False, elapsed_ms, dummy_exe_name, "timeout")
            return SelfTestResult(True, elapsed_ms, detected[0].display_name)
    except OSError as exc:
        if proc is not None and proc.poll() is None:
            proc.kill()
        if proc is not None and live_guard is not None:
            live_guard.unignore_pid(proc.pid)
        test_guard.close()
        return SelfTestResult(False, 0, dummy_exe_name, str(exc))
