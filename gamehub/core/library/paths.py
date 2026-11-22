"""Validate local library paths before inspecting launcher-controlled locations."""

import os
import re
import stat
from pathlib import Path, PureWindowsPath

if os.name == "nt":
    import ctypes

_FIXED_DRIVE = 3
_DRIVE_ROOT = re.compile(r"[A-Za-z]:\\")
_INVALID_COMPONENT = re.compile(r'[\x00-\x1f<>:"|?*]')
_DEVICE_COMPONENT = re.compile(
    r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])", re.IGNORECASE
)


def _is_safe_component(part: str) -> bool:
    return (
        bool(part)
        and not part.endswith((".", " "))
        and not _INVALID_COMPONENT.search(part)
        and not _DEVICE_COMPONENT.fullmatch(part.partition(".")[0].rstrip(" "))
    )


def local_path(value: Path | str) -> Path | None:
    """Return a safe absolute local path, allowing a missing final path.

    Unexpected filesystem errors propagate so discovery can mark a partial scan.
    """
    path = Path(value)
    if not path.is_absolute():
        return None
    if os.name == "nt" and (
        not _DRIVE_ROOT.fullmatch(path.anchor)
        or ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(path.anchor)) != _FIXED_DRIVE
    ):
        return None
    if not all(_is_safe_component(part) for part in path.parts[1:]):
        return None

    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except (FileNotFoundError, NotADirectoryError):
            break
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            return None
    return path


def contained_file(root: Path, raw: object) -> Path | None:
    """Read only regular files reached by a plain relative Windows path."""
    if not isinstance(raw, str):
        return None
    relative = PureWindowsPath(raw)
    parts = re.split(r"[/\\]", raw)
    if relative.anchor or not all(_is_safe_component(part) for part in parts):
        return None

    path = local_path(root.joinpath(*parts))
    if path is None:
        return None
    try:
        return path if stat.S_ISREG(path.lstat().st_mode) else None
    except (FileNotFoundError, NotADirectoryError):
        return None
