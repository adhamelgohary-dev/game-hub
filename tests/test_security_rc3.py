"""Security regression tests for v1.2.0-rc.3 Red-Team audit findings (C1, C2, C3, C4)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

from gamehub.core.library.epic import EpicDetector, EpicRegistryEntry
from gamehub.core.library.models import GameSource
from gamehub.core.library.steamgriddb import (
    _validate_https_host,
    fetch_steamgriddb_cover,
)
from gamehub.core.protection.catalog import ProtectedGamesCatalog
from gamehub.core.secrets import protect_secret, unprotect_secret
from gamehub.core.settings import SettingsService
from gamehub.core.storage.db import Database


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 32), (10, 80, 180)).save(buf, format="PNG")
    return buf.getvalue()


def test_ea_sports_fc_detected_across_epic_steam_ea_and_xbox() -> None:
    catalog = ProtectedGamesCatalog.load(strict_load=True)

    # Epic Games Store: known AppName, opaque hex AppName + title, and nested exe
    assert catalog.match_game(GameSource.EPIC, "ea_sports_fc_26") is not None
    assert (
        catalog.match_game(
            GameSource.EPIC, "deadbeef1234567890abcdef12345678", (), game_name="EA SPORTS FC™ 26"
        )
        is not None
    )
    assert catalog.match_game(GameSource.EPIC, "opaque-id", (), game_name="FC 26") is not None

    # Steam: FC 24, FC 25, FC 25 Showcase, FC 26
    for app_id in ("2195250", "2669320", "3103970", "3405690"):
        matched = catalog.match_game(GameSource.STEAM, app_id)
        assert matched is not None and matched.id == "ea_fc"

    # EA app: slugged names ("fc-26", "ea-sports-fc-27") AND opaque offerId + title
    for ea_id in ("fc-24", "fc-25", "fc-26", "fc-27", "ea-sports-fc-26", "ea-sports-fc-27"):
        matched = catalog.match_game(GameSource.EA, ea_id)
        assert matched is not None and matched.id == "ea_fc"
    assert (
        catalog.match_game(
            GameSource.EA, "Origin.OFR.50.0009999", (), game_name="EA SPORTS FC 26"
        )
        is not None
    )

    # Xbox / Game Pass prefixes
    for pkg in ("ElectronicArtsMobile.EASPORTSFC26:abc", "ElectronicArts.EASPORTSFC26:def"):
        matched = catalog.match_game(GameSource.XBOX, pkg)
        assert matched is not None and matched.id == "ea_fc"

    # All FC launcher & game exes trigger strict mode
    for exe in ("EAAntiCheat.GameServiceLauncher.exe", "FC24.exe", "FC25.exe", "FC26.exe", "FC27.exe"):
        assert catalog.match_exe_name(exe) is not None


def test_2026_anti_cheat_catalog_entries_and_multi_launcher_coverage() -> None:
    catalog = ProtectedGamesCatalog.load(strict_load=True)

    # GTA V / GTA V Enhanced (BattlEye) on Steam & Epic
    assert catalog.match_game(GameSource.STEAM, "3240220") is not None
    assert (
        catalog.match_game(
            GameSource.STEAM, "999999", (), game_name="Grand Theft Auto V Enhanced"
        )
        is not None
    )
    assert catalog.match_exe_name("GTA5_Enhanced.exe") is not None
    assert catalog.match_exe_name("GTA5_Enhanced_BE.exe") is not None

    # Marvel Rivals, Wuthering Waves, Roblox, Dota 2, Battlefield 6, Call of Duty Battle.net
    assert catalog.match_game(GameSource.STEAM, "2767030") is not None
    assert catalog.match_exe_name("Marvel-Win64-Shipping.exe") is not None
    assert catalog.match_game(GameSource.STEAM, "3513350") is not None
    assert catalog.match_exe_name("RobloxPlayerBeta.exe") is not None
    assert catalog.match_game(GameSource.STEAM, "570") is not None
    assert catalog.match_game(GameSource.BATTLENET, "odin") is not None
    assert catalog.match_game(GameSource.EPIC, "opaque", (), game_name="Apex Legends") is not None
    assert catalog.match_game(GameSource.EPIC, "opaque", (), game_name="Destiny 2") is not None

    # Single-player titles must NOT falsely match title aliases
    for benign in ("Hollow Knight", "Hollow Knight: Silksong", "Portal", "Terraria", "Balatro"):
        assert catalog.match_game(GameSource.STEAM, "100", (), game_name=benign) is None


def test_epic_detector_discovers_nested_game_executables(tmp_path: Path) -> None:
    game_dir = tmp_path / "Fortnite"
    nested_exe = game_dir / "FortniteGame" / "Binaries" / "Win64" / "FortniteClient-Win64-Shipping.exe"
    nested_exe.parent.mkdir(parents=True)
    nested_exe.write_bytes(b"MZ" + b"\x00" * 128)

    entry = EpicRegistryEntry(
        key_name="EpicGames-Fortnite",
        display_name="Fortnite",
        install_location=str(game_dir),
        epic_app_id="fn:item:Fortnite",
    )
    batch = EpicDetector(
        tmp_path / "no-manifests",
        registry_provider=lambda: (entry,),
        launcher_installed_path=tmp_path / "no-dat.json",
    ).discover()
    assert len(batch.games) == 1
    assert any(
        t.match_key.endswith("fortniteclient-win64-shipping.exe") for t in batch.games[0].targets
    )


def test_steamgriddb_key_encrypted_at_rest_with_dpapi_and_strict_network_validation(
    tmp_path: Path,
) -> None:
    db = Database(tmp_path / "gamehub.db")
    svc = SettingsService(db)
    secret = "sgdb-super-secret-token-12345"
    res = svc.update({"covers.steamgriddb_enabled": False, "covers.steamgriddb_api_key": secret})
    assert res.ok is True
    assert svc.read().steamgriddb_api_key == secret
    assert svc.read().steamgriddb_enabled is False

    # Confirm SQLite does NOT contain plaintext API key on Windows (DPAPI encrypted!)
    if os.name == "nt":
        conn = sqlite3.connect(tmp_path / "gamehub.db")
        try:
            raw_val = conn.execute(
                "SELECT value FROM settings WHERE key = 'covers.steamgriddb_api_key'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert secret not in raw_val
        assert json.loads(raw_val).startswith("dpapi:")
        assert unprotect_secret(protect_secret(secret)) == secret

    # URL validation rejects HTTP, userinfo, non-443 ports, and unknown hosts
    for bad_url in (
        "http://www.steamgriddb.com/api/v2/test",
        "https://user:pass@www.steamgriddb.com/api/v2/test",
        "https://www.steamgriddb.com:8443/api/v2/test",
        "https://evil.example.com/grid.png",
        "https://cdn2.steamgriddb.com.evil.com/grid.png",
    ):
        try:
            _validate_https_host(bad_url, frozenset({"www.steamgriddb.com", "cdn2.steamgriddb.com"}))
        except ValueError:
            pass
        else:
            raise AssertionError(f"Should have rejected URL: {bad_url}")

    # CRLF header injection in api_key is rejected even if called directly
    calls: list[str] = []
    assert (
        fetch_steamgriddb_cover(
            "Hades",
            enabled=True,
            api_key="abc\r\nX-Injected: 1",
            http_get=lambda u, h, m: (calls.append(u), b"")[1],
        )
        is None
    )
    assert calls == []

    # Non-image HTML payload returned from CDN is rejected before returning bytes
    def fake_html_cdn(url: str, _headers: dict[str, str], _max: int) -> bytes:
        if "/search/autocomplete/" in url:
            return json.dumps({"success": True, "data": [{"id": 42}]}).encode()
        if "/grids/game/42" in url:
            return json.dumps(
                {"success": True, "data": [{"url": "https://cdn2.steamgriddb.com/evil.png"}]}
            ).encode()
        return b"<html><body>not an image</body></html>"

    assert fetch_steamgriddb_cover("Hades", enabled=True, api_key="validkey", http_get=fake_html_cdn) is None

    # Valid PNG magic passes
    def fake_png_cdn(url: str, _headers: dict[str, str], _max: int) -> bytes:
        if "/search/autocomplete/" in url:
            return json.dumps({"success": True, "data": [{"id": 42}]}).encode()
        if "/grids/game/42" in url:
            return json.dumps(
                {"success": True, "data": [{"url": "https://cdn2.steamgriddb.com/ok.png"}]}
            ).encode()
        return _png_bytes()

    got = fetch_steamgriddb_cover("Hades", enabled=True, api_key="validkey", http_get=fake_png_cdn)
    assert got is not None and got.startswith(b"\x89PNG\r\n\x1a\n")


def test_single_instance_recovers_cleanly_after_hard_os_exit(tmp_path: Path) -> None:
    """Direct guard-thread os._exit(0) leaves gamehub.lock on disk; next launch must claim cleanly."""
    code1 = (
        "import os\n"
        "from pathlib import Path\n"
        "from PySide6.QtCore import QCoreApplication\n"
        "from gamehub.single_instance import SingleInstance\n"
        "app = QCoreApplication(['si1'])\n"
        f"si = SingleInstance(Path({str(tmp_path)!r}), lambda: None)\n"
        "assert si.claim_or_activate() is True\n"
        "os._exit(0)\n"
    )
    r1 = subprocess.run(
        [sys.executable, "-c", code1], check=False, capture_output=True, text=True, timeout=15
    )
    assert r1.returncode == 0, r1.stderr

    code2 = (
        "from pathlib import Path\n"
        "from PySide6.QtCore import QCoreApplication\n"
        "from gamehub.single_instance import SingleInstance\n"
        "app = QCoreApplication(['si2'])\n"
        f"si = SingleInstance(Path({str(tmp_path)!r}), lambda: None)\n"
        "assert si.claim_or_activate() is True\n"
        "si.close()\n"
    )
    r2 = subprocess.run(
        [sys.executable, "-c", code2], check=False, capture_output=True, text=True, timeout=15
    )
    assert r2.returncode == 0, r2.stderr
