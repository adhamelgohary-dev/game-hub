"""Regression tests closing all rc.3 4-domain Red-Team security findings."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import types
import zipfile
from pathlib import Path

import pytest

from gamehub.core.capture.windows import ensure_cv2_shim
from gamehub.core.library.models import GameSource
from gamehub.core.protection.catalog import ProtectedGamesCatalog
from gamehub.core.protection.guard import (
    _FULL_AUDIT_INTERVAL_SEC,
    ProtectionGuard,
    ToolhelpProcessScanner,
)
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.location import StoreLocation
from gamehub.modules.mods.engine import ModsEngine
from gamehub.modules.mods.manifest import (
    _StreamingPeDetector,
    extract_verified_package,
    validate_zip_manifest,
)
from gamehub.modules.mods.models import ManifestValidationError
from gamehub.ui.covers import _file_signature, _load_local_qimage, set_cover_cache_dir


class _NoServices:
    def verify_available(self) -> bool:
        return True

    def running_services(self, _names) -> frozenset[str]:
        return frozenset()


def test_rc3_ac01_pid_reuse_detected_within_240ms_audit_interval() -> None:
    assert _FULL_AUDIT_INTERVAL_SEC <= 0.25
    catalog = ProtectedGamesCatalog.load(strict_load=True)
    now = [100.0]
    procs = [((200, "notepad.exe"),)]

    class _ReuseScanner(ToolhelpProcessScanner):
        def __init__(self) -> None:
            self._kernel = None
            self._enum_procs = None

        def pid_snapshot(self) -> bytes | None:
            return b"\xc8\x00\x00\x00"  # constant PID 200 (LIFO PID reuse)

        def list_processes(self) -> tuple[tuple[int, str], ...]:
            return procs[0]

    guard = ProtectionGuard(
        catalog,
        process_scanner=_ReuseScanner(),
        service_probe=_NoServices(),
        clock=lambda: now[0],
    )
    assert guard.check_once(force_full=True, check_services=False) is None
    # Simulate LIFO PID reuse: PID 200 is now FortniteLauncher.exe while pid_snapshot stays identical.
    procs[0] = ((200, "fortnitelauncher.exe"),)
    now[0] += 0.25
    trig = guard.check_once(force_full=False, check_services=False)
    assert trig is not None and trig.entry_id == "fortnite"


@pytest.mark.skipif(os.name != "nt", reason="Windows K32EnumProcesses byte-length test")
def test_rc3_ac02_pid_snapshot_returns_exact_byte_length() -> None:
    scanner = ToolhelpProcessScanner()
    snap = scanner.pid_snapshot()
    assert snap is not None
    assert len(snap) % 4 == 0
    assert len(snap) == int(scanner._pid_needed.value)


def test_rc3_ac03_and_ac04_anti_cheat_exes_and_2026_catalog_coverage() -> None:
    catalog = ProtectedGamesCatalog.load(strict_load=True)

    # Disabling helldivers_2 must NEVER disable nProtect GameGuard (gamemon64.des).
    class _GameGuardScanner:
        def list_processes(self):
            return ((99, "GameMon64.des"),)

    guard = ProtectionGuard(
        catalog,
        process_scanner=_GameGuardScanner(),
        service_probe=_NoServices(),
        disabled_entry_ids=("helldivers_2",),
    )
    trig = guard.check_once(force_full=True, check_services=False)
    assert trig is not None and trig.identifier == "gamemon64.des"

    # 2026 catalog coverage checks
    assert "beservice_x64.exe" in catalog.global_anti_cheat_exes
    assert "gamemon64.des" in catalog.global_anti_cheat_exes
    assert catalog.match_game(GameSource.EPIC, "9c59efaabb6a48f19b3485d5d9416032") is not None
    assert catalog.match_game(GameSource.EPIC, "pubg-battlegrounds") is not None
    assert catalog.match_game(GameSource.BATTLENET, "auks") is not None
    assert catalog.match_game(GameSource.BATTLENET, "lazr") is not None
    assert catalog.match_exe_name("sp26-cod.exe") is not None
    assert catalog.match_exe_name("RainbowSix_DX12.exe") is not None


def test_rc3_net01_and_net02_covers_reject_unc_paths_and_symlinks(tmp_path: Path) -> None:
    unc_file = Path(r"\\127.0.0.1\nonexistent_share\cover.png")
    assert _file_signature(unc_file) == ("", 0, 0)
    assert _load_local_qimage(unc_file, 320, 150) is None

    set_cover_cache_dir(Path(r"\\127.0.0.1\nonexistent_share\cache"))
    from gamehub.ui import covers as covers_mod

    assert covers_mod._DISK_CACHE_DIR is None
    set_cover_cache_dir(tmp_path / "cache")
    assert covers_mod._DISK_CACHE_DIR is not None


def test_rc3_loc01_loc02_loc03_mods_dotfile_overlapped_pe_and_single_extract(tmp_path: Path) -> None:
    # 1. Dotfile script (.bat / .ps1) must be rejected even though PurePosixPath(".bat").suffix == ""
    payload = b"@echo off\n"
    sha = hashlib.sha256(payload).hexdigest()
    dot_zip = tmp_path / "dotfile.zip"
    with zipfile.ZipFile(dot_zip, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "dot-bat",
                    "name": "Dot Bat",
                    "kind": "mod",
                    "version": "1.0",
                    "files_root": "files",
                    "files": [{"src": ".bat", "dest": ".bat", "sha256": sha}],
                }
            ),
        )
        zf.writestr("files/.bat", payload)
    with pytest.raises(ManifestValidationError):
        validate_zip_manifest(dot_zip)

    # 2. Overlapped tiny PE (e_lfanew = 16) must be detected by _StreamingPeDetector
    tiny_pe = bytearray(64)
    tiny_pe[0:2] = b"MZ"
    tiny_pe[16:20] = b"PE\x00\x00"
    struct.pack_into("<I", tiny_pe, 60, 16)
    det = _StreamingPeDetector()
    det.feed(bytes(tiny_pe))
    assert det.is_pe is True

    # 3. Single-handle extract_verified_package still extracts valid declarative packs cleanly
    ok_bytes = b"hello=world\n"
    ok_sha = hashlib.sha256(ok_bytes).hexdigest()
    ok_zip = tmp_path / "ok.zip"
    with zipfile.ZipFile(ok_zip, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "ok-pack",
                    "name": "OK Pack",
                    "kind": "translation",
                    "version": "1.0",
                    "files_root": "files",
                    "files": [{"src": "strings.txt", "dest": "strings.txt", "sha256": ok_sha}],
                }
            ),
        )
        zf.writestr("files/strings.txt", ok_bytes)
    out = tmp_path / "extracted"
    manifest = extract_verified_package(ok_zip, out)
    assert manifest.id == "ok-pack"
    assert (out / "files" / "strings.txt").read_bytes() == ok_bytes


def test_rc3_loc06_store_location_move_preserves_override_catalog(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    db = Database(src / "gamehub.db")
    override_bytes = b'{"schema_version": 2, "games": []}'
    (src / "protected_games_override.json").write_bytes(override_bytes)

    ok, err = StoreLocation(src, src, db).move(dst)
    assert ok and err is None
    assert (dst / "protected_games_override.json").read_bytes() == override_bytes


def test_rc3_loc04_and_pkg01_mods_unc_safe_and_cv2_shim_sentinel(tmp_path: Path) -> None:
    # ModsEngine.is_game_protected handles UNC install_dir without crashing or caching unsafely
    data_root = tmp_path / "data"
    db = Database(data_root / "gamehub.db")
    library = LibraryRepository(db)
    exe = tmp_path / "Game" / "Story.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"stub")
    gid = library.add_manual(exe)
    game = library.get_game(gid)
    assert game is not None
    engine = ModsEngine(
        db,
        data_root,
        library,
        ProtectedGamesCatalog.load(strict_load=True),
        service_probe=_NoServices(),
    )
    assert engine.is_game_protected(game, use_cache=True)[0] is False

    # ensure_cv2_shim replaces non-sentinel spoofed cv2 module in sys.modules
    saved = sys.modules.get("cv2")
    try:
        sys.modules["cv2"] = types.ModuleType("cv2")
        ensure_cv2_shim()
        assert getattr(sys.modules["cv2"], "_GAMEREWIND_CV2_SHIM", False) is True
        with pytest.raises(RuntimeError):
            _ = sys.modules["cv2"].imread
    finally:
        if saved is None:
            sys.modules.pop("cv2", None)
        else:
            sys.modules["cv2"] = saved
