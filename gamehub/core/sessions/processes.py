"""Match running Windows processes using public Win32 metadata only."""

import ctypes
import ntpath
import os
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from ctypes import wintypes
from typing import Protocol

from .models import ProcessIdentity, ProcessSnapshot, WatchTarget

_SNAP_PROCESSES = 0x00000002
_QUERY_LIMITED_INFORMATION = 0x1000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_NO_MORE_FILES = 18
_ERROR_INVALID_PARAMETER = 87
_ERROR_INSUFFICIENT_BUFFER = 122
_NO_PACKAGE = 15700
_WINDOWS_TO_UNIX_EPOCH_SEC = 11644473600.0

# OS/system, security, anti-cheat, and launcher processes that ProcessProbe NEVER opens a handle to.
DEFAULT_NEVER_OPEN_EXES: frozenset[str] = frozenset(
    {
        "system",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "svchost.exe",
        "explorer.exe",
        "dwm.exe",
        "conhost.exe",
        "taskhostw.exe",
        "sihost.exe",
        "ctfmon.exe",
        "fontdrvhost.exe",
        "searchhost.exe",
        "startmenuexperiencehost.exe",
        "shellexperiencehost.exe",
        "runtimebroker.exe",
        "textinputhost.exe",
        "applicationframehost.exe",
        "audiodg.exe",
        "msmpeng.exe",
        "nissrv.exe",
        "securityhealthservice.exe",
        "avp.exe",
        "avpui.exe",
        "vgtray.exe",
        "vgc.exe",
        "vgm.exe",
        "eaanticheat.gameservice.exe",
        "eaanticheat.gameservicelauncher.exe",
        "eabackgroundservice.exe",
        "beservice_x64.exe",
        "faceitclient.exe",
        "faceitservice.exe",
        "epicgameslauncher.exe",
        "epicwebhelper.exe",
        "eadesktop.exe",
        "ealocalhostsvc.exe",
        "battle.net.exe",
        "agent.exe",
        "upc.exe",
        "ubisoftconnect.exe",
        "steam.exe",
        "steamservice.exe",
        "steamwebhelper.exe",
        "gamelaunchhelper.exe",
        "gta5.exe",
        "gta5_enhanced.exe",
        "gta5_be.exe",
        "gta5_enhanced_be.exe",
        "sguard64.exe",
        "sguardsvc64.exe",
        "gamemon.des",
        "gamemon64.des",
        "robloxplayerbeta.exe",
    }
)


class _ProcessEntry(ctypes.Structure):
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


class _FileTime(ctypes.Structure):
    _fields_ = (
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    )


def _filetime_to_unix_seconds(ft: _FileTime) -> float:
    ticks = (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)
    return (ticks / 10_000_000.0) - _WINDOWS_TO_UNIX_EPOCH_SEC


class ProcessMetadata(Protocol):
    def names(self) -> Iterator[tuple[int, str]]: ...

    def inspect(
        self, pid: int, *, executable: bool, package: bool
    ) -> tuple[str | None, str | None]: ...


class _WindowsProcessMetadata:
    def __init__(self) -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._snapshot = kernel.CreateToolhelp32Snapshot
        self._snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._snapshot.restype = wintypes.HANDLE
        self._first = kernel.Process32FirstW
        self._next = kernel.Process32NextW
        for step in (self._first, self._next):
            step.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
            step.restype = wintypes.BOOL
        self._open = kernel.OpenProcess
        self._open.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._open.restype = wintypes.HANDLE
        self._close = kernel.CloseHandle
        self._close.argtypes = [wintypes.HANDLE]
        self._close.restype = wintypes.BOOL
        self._image = kernel.QueryFullProcessImageNameW
        self._image.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._image.restype = wintypes.BOOL
        self._family = kernel.GetPackageFamilyName
        self._family.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
        self._family.restype = wintypes.LONG
        self._times = kernel.GetProcessTimes
        self._times.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
            ctypes.POINTER(_FileTime),
        ]
        self._times.restype = wintypes.BOOL

    def names(self) -> Iterator[tuple[int, str]]:
        snapshot = self._snapshot(_SNAP_PROCESSES, 0)
        if snapshot == _INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            success = self._first(snapshot, ctypes.byref(entry))
            while success:
                if entry.th32ProcessID > 0:
                    yield entry.th32ProcessID, entry.szExeFile
                success = self._next(snapshot, ctypes.byref(entry))
            error = ctypes.get_last_error()
            if error != _ERROR_NO_MORE_FILES:
                raise ctypes.WinError(error)
        finally:
            self._close(snapshot)

    def inspect(
        self, pid: int, *, executable: bool, package: bool
    ) -> tuple[str | None, str | None]:
        image, family, _created = self.inspect_with_time(
            pid, executable=executable, package=package
        )
        return image, family

    def inspect_with_time(
        self, pid: int, *, executable: bool, package: bool
    ) -> tuple[str | None, str | None, float]:
        handle = self._open(_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == _ERROR_INVALID_PARAMETER:
                raise ProcessLookupError("Process exited")
            raise ctypes.WinError(error)
        try:
            image = self._process_image(handle) if executable else None
            family = self._package_family(handle) if package else None
            created_at = self._process_creation_time(handle)
            return image, family, created_at
        finally:
            self._close(handle)

    def creation_time(self, pid: int) -> float:
        handle = self._open(_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == _ERROR_INVALID_PARAMETER:
                raise ProcessLookupError("Process exited")
            raise ctypes.WinError(error)
        try:
            return self._process_creation_time(handle)
        finally:
            self._close(handle)

    def _process_creation_time(self, handle: int) -> float:
        created, exited, kernel_t, user_t = _FileTime(), _FileTime(), _FileTime(), _FileTime()
        if not self._times(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel_t),
            ctypes.byref(user_t),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return _filetime_to_unix_seconds(created)

    def _process_image(self, handle: int) -> str:
        error = 0
        for capacity in (512, 32768):
            buffer = ctypes.create_unicode_buffer(capacity)
            size = wintypes.DWORD(capacity)
            if self._image(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            error = ctypes.get_last_error()
            if error != _ERROR_INSUFFICIENT_BUFFER:
                break
        raise ctypes.WinError(error)

    def _package_family(self, handle: int) -> str | None:
        buffer = ctypes.create_unicode_buffer(256)
        size = wintypes.UINT(len(buffer))
        result = self._family(handle, ctypes.byref(size), buffer)
        if result == 0:
            return buffer.value
        if result == _NO_PACKAGE:
            return None
        raise ctypes.WinError(result)


_SHARED_META: _WindowsProcessMetadata | None = None


def query_process_creation_time(pid: int) -> float:
    """Query process creation timestamp via GetProcessTimes on PROCESS_QUERY_LIMITED_INFORMATION.

    Callers MUST restrict calls to verified non-protected Full-mode game PIDs only.
    """
    global _SHARED_META
    if os.name != "nt":
        raise OSError("Windows process timing is unavailable on this platform.")
    if _SHARED_META is None:
        _SHARED_META = _WindowsProcessMetadata()
    return _SHARED_META.creation_time(pid)


class ProcessProbe:
    def __init__(
        self,
        metadata: ProcessMetadata | None = None,
        creation_time: Callable[[int], float] | None = None,
    ) -> None:
        self._metadata = metadata if metadata is not None else _WindowsProcessMetadata()
        self._creation_time = creation_time

    def snapshot(
        self,
        targets: Sequence[WatchTarget],
        *,
        passive_basenames: Mapping[str, frozenset[str]] | None = None,
        protected_exes: frozenset[str] = frozenset(),
        never_open_exes: frozenset[str] = frozenset(),
        ignored_pids: frozenset[int] = frozenset(),
    ) -> ProcessSnapshot:
        executables: dict[str, set[str]] = defaultdict(set)
        games_with_exe: set[str] = set()
        packages: dict[str, set[str]] = defaultdict(set)
        for target in targets:
            if target.kind == "exe_path":
                executables[ntpath.normcase(target.match_key)].add(target.game_id)
                games_with_exe.add(target.game_id)
        for target in targets:
            if target.kind == "package_id" and target.game_id not in games_with_exe:
                # Only fall back to package_id inspection if the game has no exe_path target.
                packages[target.match_key.casefold()].add(target.game_id)

        passive = {
            ntpath.normcase(name): game_ids for name, game_ids in (passive_basenames or {}).items()
        }
        protected = frozenset(ntpath.normcase(name) for name in protected_exes)
        never_open = DEFAULT_NEVER_OPEN_EXES | frozenset(
            ntpath.normcase(name) for name in never_open_exes
        )
        if not executables and not packages and not passive and not protected:
            return ProcessSnapshot({})

        basenames = {ntpath.basename(path) for path in executables}
        observed: dict[str, set[ProcessIdentity]] = defaultdict(set)
        seen_protected: set[str] = set()
        unknown: set[int] = set()
        complete = True
        try:
            for pid, name in self._metadata.names():
                if pid in ignored_pids:
                    continue
                norm_name = ntpath.normcase(name)
                is_protected = norm_name in protected
                if is_protected:
                    seen_protected.add(norm_name)

                # Strict-mode / protected games are observed passively by Toolhelp basename only:
                # never call OpenProcess on protected game processes.
                passive_games = passive.get(norm_name)
                if passive_games:
                    for game_id in passive_games:
                        observed[game_id].add(ProcessIdentity(pid, 0.0))
                    continue
                if is_protected or norm_name in never_open:
                    continue

                check_image = norm_name in basenames
                check_package = bool(packages)
                if not check_image and not check_package:
                    continue
                try:
                    if (
                        self._creation_time is None
                        and isinstance(self._metadata, _WindowsProcessMetadata)
                    ):
                        # Single atomic handle query: image + optional package + GetProcessTimes!
                        image, family, created_at = self._metadata.inspect_with_time(
                            pid, executable=check_image, package=check_package
                        )
                        matches = self._match_results(image, family, executables, packages)
                        if not matches:
                            continue
                        if len(matches) != 1:
                            unknown.add(pid)
                            continue
                        observed[next(iter(matches))].add(ProcessIdentity(pid, created_at))
                    else:
                        matches = self._matches(pid, check_image, check_package, executables, packages)
                        if not matches:
                            continue
                        if len(matches) != 1:
                            unknown.add(pid)
                            continue
                        get_time = (
                            self._creation_time
                            if self._creation_time is not None
                            else query_process_creation_time
                        )
                        created_at = get_time(pid)
                        confirmed = self._matches(
                            pid, check_image, check_package, executables, packages
                        )
                        if confirmed != matches or get_time(pid) != created_at:
                            unknown.add(pid)
                            continue
                        observed[next(iter(matches))].add(ProcessIdentity(pid, created_at))
                except ProcessLookupError:
                    continue
                except OSError:
                    unknown.add(pid)
        except OSError:
            complete = False

        return ProcessSnapshot(
            {game_id: frozenset(identities) for game_id, identities in observed.items()},
            frozenset(unknown),
            complete,
            frozenset(seen_protected),
        )

    @staticmethod
    def _match_results(
        image: str | None,
        family: str | None,
        executables: dict[str, set[str]],
        packages: dict[str, set[str]],
    ) -> set[str]:
        matches: set[str] = set()
        if image:
            matches.update(executables.get(ntpath.normcase(image), ()))
        if family:
            matches.update(packages.get(family.casefold(), ()))
        return matches

    def _matches(
        self,
        pid: int,
        check_image: bool,
        check_package: bool,
        executables: dict[str, set[str]],
        packages: dict[str, set[str]],
    ) -> set[str]:
        image, family = self._metadata.inspect(
            pid, executable=check_image, package=check_package
        )
        return self._match_results(image, family, executables, packages)
