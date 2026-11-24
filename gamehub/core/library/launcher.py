"""Validate launch targets, hand them off to Windows, and correlate starts."""

import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import uuid4

from gamehub.core.library.models import LaunchFinished, LaunchRequested, LaunchTarget
from gamehub.core.library.paths import local_path

ATTEMPT_TTL_SEC = 90.0
_SW_SHOWNORMAL = 1
_COINIT_APARTMENTTHREADED = 0x2
_COINIT_DISABLE_OLE1DDE = 0x4
_S_OK = 0
_S_FALSE = 1
_FROZEN_ENV_KEYS = (
    "_MEIPASS",
    "_MEIPASS2",
    "LD_LIBRARY_PATH",
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
)
_STEAM_URI = re.compile(r"steam://rungameid/[0-9]{1,10}\Z")
_EPIC_PART = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_EPIC_URI = re.compile(
    rf"com\.epicgames\.launcher://apps/(?:{_EPIC_PART}(?:%3A{_EPIC_PART}){{2}}|{_EPIC_PART})"
    r"\?action=launch&silent=true\Z"
)
_UBISOFT_URI = re.compile(r"uplay://launch/[0-9]{1,10}/0\Z")
_GOG_URI = re.compile(r"goggalaxy://openGameView/[0-9]{1,16}\Z")
_EA_URI = re.compile(
    r"(?:origin2://game/launch\?offerIds=[A-Za-z0-9._:,-]{1,128}|link2ea://launchgame/[A-Za-z0-9._-]{1,128})\Z"
)
_BATTLENET_URI = re.compile(r"battlenet://[A-Za-z0-9._-]{1,64}\Z")
_XBOX_URI = re.compile(r"shell:AppsFolder\\[A-Za-z0-9._!-]{1,256}\Z")
_RIOT_TOKEN = re.compile(r"[a-z0-9_-]{1,64}\Z")


@dataclass(frozen=True, slots=True)
class LaunchReceipt:
    attempt_id: str
    game_id: str
    target: LaunchTarget


@dataclass(frozen=True, slots=True)
class LaunchResult:
    accepted: bool
    receipt: LaunchReceipt | None = None
    diagnostic: str | None = None


def validate_launch_target(
    target: LaunchTarget,
) -> LaunchTarget | Path | tuple[Path, tuple[str, ...]] | None:
    """Confirm a launch target matches a fixed URI template or a safe local executable."""
    if not isinstance(target, LaunchTarget) or not isinstance(target.value, str):
        return None
    if target.kind == "steam_uri":
        return target if _STEAM_URI.fullmatch(target.value) else None
    if target.kind == "epic_uri":
        return target if _EPIC_URI.fullmatch(target.value) else None
    if target.kind == "ubisoft_uri":
        return target if _UBISOFT_URI.fullmatch(target.value) else None
    if target.kind == "gog_uri":
        return target if _GOG_URI.fullmatch(target.value) else None
    if target.kind == "ea_uri":
        return target if _EA_URI.fullmatch(target.value) else None
    if target.kind == "battlenet_uri":
        return target if _BATTLENET_URI.fullmatch(target.value) else None
    if target.kind == "xbox_uri":
        return target if _XBOX_URI.fullmatch(target.value) else None
    if target.kind == "riot_client":
        parts = target.value.split("|")
        if len(parts) != 3:
            return None
        raw_exe, product, patchline = parts
        if not _RIOT_TOKEN.fullmatch(product) or not _RIOT_TOKEN.fullmatch(patchline):
            return None
        try:
            path = local_path(raw_exe)
            if path is None or path.name.casefold() != "riotclientservices.exe":
                return None
            info = path.lstat()
        except OSError:
            return None
        if stat.S_ISREG(info.st_mode) and not (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            return (
                path,
                (f"--launch-product={product}", f"--launch-patchline={patchline}"),
            )
        return None
    if target.kind == "exe":
        try:
            path = local_path(target.value)
            if path is None or path.suffix.lower() != ".exe":
                return None
            info = path.lstat()
        except OSError:
            return None
        if stat.S_ISREG(info.st_mode) and not (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            return path
    return None


def _shell_open_uri(uri: str) -> str | None:
    if os.name != "nt":
        return "launch_failed"

    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    co_init = ole32.CoInitializeEx
    co_init.argtypes = (wintypes.LPVOID, wintypes.DWORD)
    co_init.restype = ctypes.c_long
    co_uninit = ole32.CoUninitialize
    co_uninit.argtypes = ()
    co_uninit.restype = None

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    execute = shell32.ShellExecuteW
    execute.argtypes = (
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    )
    execute.restype = ctypes.c_void_p

    com_status = co_init(None, _COINIT_APARTMENTTHREADED | _COINIT_DISABLE_OLE1DDE)
    initialized = com_status in {_S_OK, _S_FALSE}
    try:
        code = int(execute(None, "open", uri, None, None, _SW_SHOWNORMAL) or 0)
    finally:
        if initialized:
            co_uninit()
    if code > 32:
        return None
    if code in {2, 3, 31}:
        return "launch_handler_missing"
    return "launch_failed"


def _spawn_env() -> dict[str, str] | None:
    if not getattr(sys, "frozen", False):
        return None
    env = dict(os.environ)
    for key in _FROZEN_ENV_KEYS:
        env.pop(key, None)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and "PATH" in env:
        internal = os.path.normcase(os.path.normpath(meipass))
        parts = [
            item
            for item in env["PATH"].split(os.pathsep)
            if os.path.normcase(os.path.normpath(item)) != internal
        ]
        env["PATH"] = os.pathsep.join(parts)
    return env


def _spawn_executable(
    path: Path, args: tuple[str, ...] = (), *, detached: bool = False
) -> str | None:
    flags = 0
    if detached and os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        subprocess.Popen(
            [str(path), *args],
            cwd=str(path.parent),
            env=_spawn_env(),
            shell=False,
            close_fds=True,
            creationflags=flags,
        )
    except OSError:
        return "launch_failed"
    return None


class WindowsLauncher:
    """Dispatch validated official launcher URIs or local executables through Windows."""

    def __init__(
        self,
        open_uri: Callable[[str], str | None] = _shell_open_uri,
        spawn_exe: Callable[[Path], str | None] = _spawn_executable,
        spawn_detached: Callable[[Path, tuple[str, ...]], str | None] | None = None,
    ) -> None:
        self._open_uri = open_uri
        self._spawn_exe = spawn_exe
        self._spawn_detached = (
            spawn_detached
            if spawn_detached is not None
            else (lambda p, args: _spawn_executable(p, args, detached=True))
        )

    def launch(self, game_id: str, target: LaunchTarget, attempt_id: str) -> LaunchResult:
        validated = validate_launch_target(target)
        if validated is None:
            return LaunchResult(accepted=False, diagnostic="launch_invalid_target")

        if isinstance(validated, Path):
            diagnostic = self._spawn_exe(validated)
        elif isinstance(validated, tuple):
            path, args = validated
            diagnostic = self._spawn_detached(path, args)
        else:
            diagnostic = self._open_uri(validated.value)
        if diagnostic is not None:
            return LaunchResult(accepted=False, diagnostic=diagnostic)
        return LaunchResult(accepted=True, receipt=LaunchReceipt(attempt_id, game_id, target))


class LaunchCoordinator:
    """Coordinate explicit launches and match them with the next observed game start."""

    def __init__(
        self,
        launcher: WindowsLauncher,
        publish: Callable[[LaunchRequested | LaunchFinished], None] | None = None,
        *,
        clock: Callable[[], float] = monotonic,
        ttl_sec: float = ATTEMPT_TTL_SEC,
    ) -> None:
        self._launcher = launcher
        self._publish = publish
        self._clock = clock
        self._ttl_sec = ttl_sec
        self._lock = Lock()
        self._pending: dict[str, tuple[str, float]] = {}

    def launch(self, game_id: str, target: LaunchTarget | None) -> LaunchResult:
        if target is None:
            return LaunchResult(accepted=False, diagnostic="launch_unavailable")

        attempt_id = str(uuid4())
        expires_at = self._clock() + self._ttl_sec
        with self._lock:
            self._prune(self._clock())
            self._pending[game_id] = (attempt_id, expires_at)
        if self._publish is not None:
            self._publish(LaunchRequested(attempt_id, game_id))

        result = self._launcher.launch(game_id, target, attempt_id)
        if not result.accepted:
            with self._lock:
                current = self._pending.get(game_id)
                if current is not None and current[0] == attempt_id:
                    del self._pending[game_id]
        if self._publish is not None:
            self._publish(LaunchFinished(attempt_id, game_id, result.accepted, result.diagnostic))
        return result

    def claim(self, game_id: str) -> str | None:
        """Consume an unexpired explicit launch attempt for the observed game start."""
        now = self._clock()
        with self._lock:
            self._prune(now)
            entry = self._pending.pop(game_id, None)
            return entry[0] if entry is not None else None

    def _prune(self, now: float) -> None:
        expired = [game_id for game_id, (_, expires) in self._pending.items() if now > expires]
        for game_id in expired:
            del self._pending[game_id]
