"""Regression tests for all Round 1 Red-Team security findings (R1-R7)."""

from __future__ import annotations

import hashlib
import json
import struct
import zipfile
from pathlib import Path

import pytest

from gamehub.core.library.models import DetectedGame, DiscoveryBatch, GameSource
from gamehub.core.library.steamgriddb import fetch_steamgriddb_cover
from gamehub.core.protection.catalog import CatalogLoadError, ProtectedGamesCatalog
from gamehub.core.protection.guard import ProtectionGuard, unbiased_monotonic
from gamehub.core.protection.lifecycle import LifecycleCoordinator
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.location import StoreLocation
from gamehub.core.storage.pending_notes import PendingNoteRepository
from gamehub.modules.mods.engine import ModsEngine
from gamehub.modules.mods.manifest import validate_zip_manifest
from gamehub.modules.mods.models import ManifestValidationError, ProtectedGameModError
from gamehub.modules.mods.sample_pack import build_sample_translation_zip


class _EmptyScanner:
    def list_processes(self) -> tuple[tuple[int, str], ...]:
        return ()


class _EmptyServiceProbe:
    def verify_available(self) -> bool:
        return True

    def running_services(self, _names) -> frozenset[str]:
        return frozenset()


def test_override_catalog_cannot_weaken_or_strip_bundled_protected_games(tmp_path: Path) -> None:
    override = tmp_path / "protected_games_override.json"
    override.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "games": [
                    {
                        "id": "fortnite",
                        "name": "Fortnite",
                        "default_mode": "full",
                        "launcher_stage_exes": [],
                        "game_exes": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog = ProtectedGamesCatalog.load(override_path=override, strict_load=True)
    fn = catalog.match_exe_name("FortniteLauncher.exe")
    assert fn is not None and fn.id == "fortnite"
    assert fn.default_mode == "strict"
    assert "fortniteclient-win64-shipping.exe" in fn.game_exes

    # Different-ID hijack override attempting to downgrade Valorant/Fortnite to 'full' MUST fail!
    hijack = tmp_path / "hijack_override.json"
    hijack.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "games": [
                    {
                        "id": "hijack_bypass",
                        "name": "Bypass",
                        "default_mode": "full",
                        "epic_app_names": ["Fortnite"],
                        "riot_product_ids": ["valorant"],
                        "game_exes": [
                            "fortniteclient-win64-shipping.exe",
                            "valorant-win64-shipping.exe",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    hcat = ProtectedGamesCatalog.load(override_path=hijack, strict_load=True)
    assert hcat.effective_mode("auto", GameSource.EPIC, "Fortnite", ()) == "strict"
    assert hcat.effective_mode("auto", GameSource.RIOT, "valorant.live", ()) == "strict"
    assert hcat.match_exe_name("valorant-win64-shipping.exe").default_mode == "strict"


def test_catalog_rejects_bool_schema_version_and_deep_recursion(tmp_path: Path) -> None:
    bool_schema = tmp_path / "bool.json"
    bool_schema.write_text('{"schema_version": true, "games": []}', encoding="utf-8")
    with pytest.raises(CatalogLoadError):
        ProtectedGamesCatalog.load(bundled_path=bool_schema, strict_load=True)

    deep = tmp_path / "deep.json"
    deep.write_text("[" * 5000 + "]" * 5000, encoding="utf-8")
    with pytest.raises(CatalogLoadError):
        ProtectedGamesCatalog.load(bundled_path=deep, strict_load=True)


def test_unbiased_monotonic_and_lifecycle_fail_closed_on_storage_error(tmp_path: Path) -> None:
    t1 = unbiased_monotonic()
    t2 = unbiased_monotonic()
    assert t2 >= t1

    class _BrokenLibrary:
        def get_game(self, _gid: str):
            raise StorageError("db locked")

    db = Database(tmp_path / "gamehub.db")
    lc = LifecycleCoordinator(
        ProtectedGamesCatalog.load(strict_load=True),
        _BrokenLibrary(),  # type: ignore[arg-type]
        PendingNoteRepository(db),
    )
    assert lc.is_strict_game("any-game") is True


def test_custom_strict_game_triggers_protection_guard() -> None:
    catalog = ProtectedGamesCatalog.load(strict_load=True)

    class _Scanner:
        def list_processes(self):
            return ((777, "CustomAntiCheatGame.exe"),)

    guard = ProtectionGuard(
        catalog,
        process_scanner=_Scanner(),
        service_probe=_EmptyServiceProbe(),
        extra_strict_exes=(("CustomAntiCheatGame.exe", "Custom Strict Title"),),
    )
    trig = guard.check_once()
    assert trig is not None
    assert trig.display_name == "Custom Strict Title"


def test_mods_rejects_pe_binary_src_bomb_case_collision_and_protected_sibling(tmp_path: Path) -> None:
    # 1. Renamed PE executable inside .zip (.dat with MZ + PE\0\0 header) must be rejected
    pe_bytes = bytearray(128)
    pe_bytes[0:2] = b"MZ"
    struct.pack_into("<I", pe_bytes, 60, 64)
    pe_bytes[64:68] = b"PE\x00\x00"
    pe_sha = hashlib.sha256(bytes(pe_bytes)).hexdigest()
    pe_zip = tmp_path / "pe_disguised.zip"
    with zipfile.ZipFile(pe_zip, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "pe-test",
                    "name": "PE Test",
                    "kind": "mod",
                    "version": "1.0",
                    "files_root": "files",
                    "files": [{"src": "data.dat", "dest": "data.dat", "sha256": pe_sha}],
                }
            ),
        )
        zf.writestr("files/data.dat", bytes(pe_bytes))
    with pytest.raises(ManifestValidationError):
        validate_zip_manifest(pe_zip)

    # 1b. Renamed PE with e_lfanew >= 4096 (high offset) must ALSO be rejected!
    pe_high = bytearray(4200)
    pe_high[0:2] = b"MZ"
    struct.pack_into("<I", pe_high, 60, 4096)
    pe_high[4096:4100] = b"PE\x00\x00"
    pe_high_sha = hashlib.sha256(bytes(pe_high)).hexdigest()
    pe_high_zip = tmp_path / "pe_high_offset.zip"
    with zipfile.ZipFile(pe_high_zip, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "pe-high",
                    "name": "PE High",
                    "kind": "mod",
                    "version": "1.0",
                    "files_root": "files",
                    "files": [{"src": "data.dat", "dest": "data.dat", "sha256": pe_high_sha}],
                }
            ),
        )
        zf.writestr("files/data.dat", bytes(pe_high))
    with pytest.raises(ManifestValidationError):
        validate_zip_manifest(pe_high_zip)

    # 2. src-reuse amplification bomb (2 MB member referenced 300 times = 600 MB > 512 MB cap)
    chunk = b"A" * (2 * 1024 * 1024)
    chunk_sha = hashlib.sha256(chunk).hexdigest()
    bomb_zip = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "bomb",
                    "name": "Bomb",
                    "kind": "mod",
                    "version": "1.0",
                    "files_root": "files",
                    "files": [
                        {"src": "blob.bin", "dest": f"out/f{i}.bin", "sha256": chunk_sha}
                        for i in range(300)
                    ],
                }
            ),
        )
        zf.writestr("files/blob.bin", chunk)
    with pytest.raises(ManifestValidationError):
        validate_zip_manifest(bomb_zip)

    # 3. Case-insensitive collision across two mods (fonts.cfg vs Fonts.cfg) detected as conflict
    #    and original backup survives StoreLocation.move()!
    data_root = tmp_path / "data"
    db = Database(data_root / "gamehub.db")
    library = LibraryRepository(db)
    game_dir = tmp_path / "StoryGame"
    (game_dir / "localization").mkdir(parents=True)
    (game_dir / "Story.exe").write_bytes(b"fake")
    (game_dir / "localization" / "fonts.cfg").write_bytes(b"ORIGINAL_FONT\n")
    (game_dir / "localization" / "strings.txt").write_bytes(b"ORIGINAL_TEXT\n")
    gid = library.add_manual(game_dir / "Story.exe")

    catalog = ProtectedGamesCatalog.load(strict_load=True)
    engine = ModsEngine(
        db,
        data_root,
        library,
        catalog,
        process_scanner=_EmptyScanner(),
        service_probe=_EmptyServiceProbe(),
    )

    tr_zip = build_sample_translation_zip(tmp_path / "tr.zip")
    engine.import_zip(gid, tr_zip, enable=True)

    upper_mod_bytes = b"UPPER_CASE_MOD_FONT\n"
    upper_sha = hashlib.sha256(upper_mod_bytes).hexdigest()
    upper_zip = tmp_path / "upper_mod.zip"
    with zipfile.ZipFile(upper_zip, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "upper-mod",
                    "name": "Upper Mod",
                    "kind": "mod",
                    "version": "1.0",
                    "files_root": "files",
                    "files": [
                        {
                            "src": "localization/Fonts.cfg",
                            "dest": "localization/Fonts.cfg",
                            "sha256": upper_sha,
                        }
                    ],
                }
            ),
        )
        zf.writestr("files/localization/Fonts.cfg", upper_mod_bytes)

    engine.import_zip(gid, upper_zip, enable=True)
    state = engine.get_state(gid)
    assert len(state.conflicts) == 1

    # Move store to a new location and verify Restore Original STILL works via relative paths!
    moved_root = tmp_path / "moved_data"
    ok, err = StoreLocation(data_root, data_root, db).move(moved_root)
    assert ok and err is None

    moved_db = Database(moved_root / "gamehub.db")
    moved_engine = ModsEngine(
        moved_db,
        moved_root,
        LibraryRepository(moved_db),
        catalog,
        process_scanner=_EmptyScanner(),
        service_probe=_EmptyServiceProbe(),
    )
    moved_engine.restore_original(gid)
    assert (game_dir / "localization" / "fonts.cfg").read_bytes() == b"ORIGINAL_FONT\n"
    assert (game_dir / "localization" / "strings.txt").read_bytes() == b"ORIGINAL_TEXT\n"

    # 4. Sibling helper exe inside a protected game's folder is locked!
    fn_dir = tmp_path / "FortniteRoot"
    (fn_dir / "Binaries" / "Win64").mkdir(parents=True)
    (fn_dir / "Binaries" / "Win64" / "FortniteClient-Win64-Shipping.exe").write_bytes(b"x")
    helper = fn_dir / "HelperTool.exe"
    helper.write_bytes(b"y")
    sibling_id = library.add_manual(helper)
    assert engine.get_state(sibling_id).protected is True
    with pytest.raises(ProtectedGameModError):
        engine.import_zip(sibling_id, tr_zip)

    # 5. Ubisoft R6 Siege (zero exe targets) & Riot 2XKO (lion) are locked by source_id!
    r6_dir = tmp_path / "R6Siege"
    r6_dir.mkdir()
    library.reconcile(
        GameSource.UBISOFT,
        DiscoveryBatch(
            (DetectedGame(GameSource.UBISOFT, "635", "Rainbow Six Siege", install_dir=r6_dir),)
        ),
    )
    r6_game = next(g for g in library.list_games() if g.source == GameSource.UBISOFT)
    assert engine.get_state(r6_game.id).protected is True


def test_steamgriddb_rejects_disallowed_cdn_hosts() -> None:
    calls: list[str] = []

    def fake_get(url: str, _headers: dict[str, str], _max_bytes: int) -> bytes:
        calls.append(url)
        if "/search/autocomplete/" in url:
            return json.dumps({"success": True, "data": [{"id": 99}]}).encode()
        if "/grids/game/99" in url:
            return json.dumps(
                {"success": True, "data": [{"url": "https://evil.example.com/cover.png"}]}
            ).encode()
        return b"should-never-fetch"

    result = fetch_steamgriddb_cover(
        "Hollow Knight", enabled=True, api_key="secret-key", http_get=fake_get
    )
    assert result is None
    assert all("evil.example.com" not in u for u in calls)


def test_ea_ids_match_protected_catalog_and_mods_lock(tmp_path: Path) -> None:
    catalog = ProtectedGamesCatalog.load(strict_load=True)
    for ea_id, expected_id in (
        ("ea-sports-fc-25", "ea_fc"),
        ("battlefield-2042", "battlefield"),
        ("apex-legends", "apex_legends"),
    ):
        matched = catalog.match_game(GameSource.EA, ea_id)
        assert matched is not None and matched.id == expected_id

    data_root = tmp_path / "data"
    db = Database(data_root / "gamehub.db")
    library = LibraryRepository(db)
    ea_dir = tmp_path / "EAFC25"
    ea_dir.mkdir()
    library.reconcile(
        GameSource.EA,
        DiscoveryBatch((DetectedGame(GameSource.EA, "ea-sports-fc-25", "EA SPORTS FC 25", install_dir=ea_dir),)),
    )
    ea_game = next(g for g in library.list_games() if g.source == GameSource.EA)
    engine = ModsEngine(
        db,
        data_root,
        library,
        catalog,
        process_scanner=_EmptyScanner(),
        service_probe=_EmptyServiceProbe(),
    )
    assert engine.get_state(ea_game.id).protected is True


def test_startup_guard_prefs_loads_custom_strict_games_and_nonblocking_close(tmp_path: Path) -> None:
    from threading import Event
    from time import monotonic

    from gamehub.app import _read_startup_guard_prefs

    data_root = tmp_path / "data"
    data_root.mkdir()
    db = Database(data_root / "gamehub.db")
    library = LibraryRepository(db)
    exe = tmp_path / "CustomGame" / "MyStrictGame.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"stub")
    gid = library.add_manual(exe)
    library.set_protection(gid, "strict")

    lang, launchers, custom_strict = _read_startup_guard_prefs(data_root)
    assert lang == "en"
    assert launchers == frozenset()
    assert ("mystrictgame.exe", "MyStrictGame") in custom_strict

    # Guard.close(wait=False) must return immediately even when the scanner is blocked.
    unblock = Event()
    entered = Event()

    class _BlockedScanner:
        def list_processes(self):
            entered.set()
            unblock.wait(timeout=5.0)
            return ((1, "explorer.exe"),)

    guard = ProtectionGuard(
        ProtectedGamesCatalog.load(strict_load=True),
        process_scanner=_BlockedScanner(),
        service_probe=_EmptyServiceProbe(),
        interval_sec=0.05,
    )
    guard.start(on_trigger=lambda _t: None, on_failure=lambda _r: None)
    assert entered.wait(timeout=2.0)
    t0 = monotonic()
    guard.close(wait=False)
    elapsed = monotonic() - t0
    unblock.set()
    assert elapsed < 0.25
