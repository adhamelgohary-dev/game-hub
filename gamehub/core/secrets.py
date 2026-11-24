"""Protect local opt-in secrets (e.g. SteamGridDB API key) at rest using Windows DPAPI.

Uses ONLY public Win32 `crypt32.CryptProtectData` / `CryptUnprotectData` tied to the
current Windows user account with `CRYPTPROTECT_UI_FORBIDDEN`. Completely offline.
"""

from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes

_DPAPI_PREFIX = "dpapi:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _dpapi_protect(raw: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    in_blob = _DataBlob(len(raw), buf)
    out_blob = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "GameRewind",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    ):
        raise OSError(f"CryptProtectData failed (winerror={ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(cipher: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    buf = (ctypes.c_ubyte * len(cipher)).from_buffer_copy(cipher)
    in_blob = _DataBlob(len(cipher), buf)
    out_blob = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    ):
        raise OSError(f"CryptUnprotectData failed (winerror={ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def protect_secret(plaintext: str) -> str:
    """Encrypt a non-empty secret string for local SQLite storage using Windows DPAPI."""
    cleaned = plaintext.strip()
    if not cleaned:
        return ""
    if os.name != "nt":
        return cleaned
    encrypted = _dpapi_protect(cleaned.encode("utf-8"))
    return _DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect_secret(stored: str) -> str:
    """Decrypt a DPAPI-protected secret, transparently accepting legacy plaintext values."""
    if not isinstance(stored, str) or not stored:
        return ""
    if not stored.startswith(_DPAPI_PREFIX):
        return stored.strip()
    if os.name != "nt":
        return ""
    encoded = stored.removeprefix(_DPAPI_PREFIX)
    try:
        cipher = base64.b64decode(encoded.encode("ascii"), validate=True)
        if not cipher:
            return ""
        return _dpapi_unprotect(cipher).decode("utf-8").strip()
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
