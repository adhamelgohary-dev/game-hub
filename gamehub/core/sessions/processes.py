"""Match running Windows processes using public OS metadata only."""

import ctypes
import ntpath
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from ctypes import wintypes
from typing import Protocol

import psutil

from .models import ProcessIdentity, ProcessSnapshot, WatchTarget

_SNAP_PROCESSES = 0x00000002
_QUERY_LIMITED_INFORMATION = 0x1000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_ERROR_NO_MORE_FILES = 18
_ERROR_INVALID_PARAMETER = 87
_ERROR_INSUFFICIENT_BUFFER = 122
_NO_PACKAGE = 15700


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
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        ]
        self._image.restype = wintypes.BOOL
        self._family = kernel.GetPackageFamilyName
        self._family.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
        self._family.restype = wintypes.LONG

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
        handle = self._open(_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == _ERROR_INVALID_PARAMETER:
                raise ProcessLookupError("Process exited")
            raise ctypes.WinError(error)
        try:
            image = self._process_image(handle) if executable else None
            family = self._package_family(handle) if package else None
            return image, family
        finally:
            self._close(handle)

    def _process_image(self, handle: int) -> str:
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


def _fresh_creation_time(pid: int) -> float:
    return psutil.Process(pid).create_time()


class ProcessProbe:
    def __init__(
        self,
        metadata: ProcessMetadata | None = None,
        creation_time: Callable[[int], float] = _fresh_creation_time,
    ) -> None:
        self._metadata = metadata if metadata is not None else _WindowsProcessMetadata()
        self._creation_time = creation_time

    def snapshot(self, targets: Sequence[WatchTarget]) -> ProcessSnapshot:
        executables: dict[str, set[str]] = defaultdict(set)
        packages: dict[str, set[str]] = defaultdict(set)
        for target in targets:
            if target.kind == "exe_path":
                executables[ntpath.normcase(target.match_key)].add(target.game_id)
            elif target.kind == "package_id":
                packages[target.match_key.casefold()].add(target.game_id)
        if not executables and not packages:
            return ProcessSnapshot({})

        basenames = {ntpath.basename(path) for path in executables}
        observed: dict[str, set[ProcessIdentity]] = defaultdict(set)
        unknown = set()
        complete = True
        try:
            for pid, name in self._metadata.names():
                check_image = ntpath.normcase(name) in basenames
                if not check_image and not packages:
                    continue
                try:
                    matches = self._matches(pid, check_image, executables, packages)
                    if not matches:
                        continue
                    if len(matches) != 1:
                        unknown.add(pid)
                        continue

                    # A PID can be reused between the inventory and a metadata read.
                    created_at = self._creation_time(pid)
                    confirmed = self._matches(pid, check_image, executables, packages)
                    if confirmed != matches or self._creation_time(pid) != created_at:
                        unknown.add(pid)
                        continue
                    observed[next(iter(matches))].add(ProcessIdentity(pid, created_at))
                except (psutil.NoSuchProcess, ProcessLookupError):
                    continue
                except (psutil.Error, OSError):
                    unknown.add(pid)
        except (psutil.Error, OSError):
            complete = False

        return ProcessSnapshot(
            {game_id: frozenset(identities) for game_id, identities in observed.items()},
            frozenset(unknown),
            complete,
        )

    def _matches(
        self,
        pid: int,
        check_image: bool,
        executables: dict[str, set[str]],
        packages: dict[str, set[str]],
    ) -> set[str]:
        image, family = self._metadata.inspect(pid, executable=check_image, package=bool(packages))
        matches = set()
        if image:
            matches.update(executables.get(ntpath.normcase(image), ()))
        if family:
            matches.update(packages.get(family.casefold(), ()))
        return matches
