"""Tests for M16: landscape-first Steam covers, WebP disk cache, CoverStore, Change cover, and opt-in SteamGridDB."""

from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path

import pytest
import vdf
from PIL import Image
from PySide6.QtWidgets import QApplication

from gamehub.core.library.models import DetectedGame, DiscoveryBatch, GameSource
from gamehub.core.library.steam import SteamDetector
from gamehub.core.library.steamgriddb import fetch_steamgriddb_cover
from gamehub.core.storage.covers import CoverStore
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.ui.covers import (
    CoverLabel,
    clear_cover_cache,
    load_cover_pixmap,
    set_cover_cache_dir,
)


def _png_bytes(width: int = 460, height: int = 215, color: tuple[int, int, int] = (40, 120, 210)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def test_steam_prefers_landscape_cover_over_vertical_capsule(tmp_path: Path) -> None:
    steam_root = tmp_path / "Steam"
    game_dir = steam_root / "steamapps" / "common" / "WideGame"
    game_dir.mkdir(parents=True)
    (game_dir / "WideGame.exe").write_bytes(b"MZ")
    (steam_root / "steamapps" / "appmanifest_555001.acf").write_text(
        vdf.dumps({"AppState": {"appid": "555001", "name": "Wide Game", "installdir": "WideGame"}}),
        encoding="utf-8",
    )
    (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
        vdf.dumps({"libraryfolders": {"0": {"path": str(steam_root)}}}),
        encoding="utf-8",
    )
    cache = steam_root / "appcache" / "librarycache"
    cache.mkdir(parents=True)
    # Put vertical capsule in flat layout, and wide header inside hashed subfolder!
    (cache / "555001_library_600x900.jpg").write_bytes(b"\xff\xd8\xff")
    hashed_header = cache / "555001" / "abc123hash" / "library_header.jpg"
    hashed_header.parent.mkdir(parents=True)
    hashed_header.write_bytes(b"\xff\xd8\xff")

    batch = SteamDetector(steam_root).discover()
    assert batch.state == "complete"
    assert batch.games[0].cover_path == hashed_header.resolve()


def test_cover_disk_cache_and_zero_stretch_cover_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    app = QApplication.instance() or QApplication(["Game Hub test"])

    img_path = tmp_path / "source.png"
    img_path.write_bytes(_png_bytes(600, 900))
    cache_dir = tmp_path / "cache" / "covers"
    set_cover_cache_dir(cache_dir)
    clear_cover_cache()
    try:
        pm1 = load_cover_pixmap(img_path, "Vertical Art Game", 280, 150, radius=9)
        assert not pm1.isNull()
        assert pm1.width() == 280 and pm1.height() == 150
        cached_files = list(cache_dir.glob("*.webp"))
        assert len(cached_files) == 1

        # Clear RAM cache and verify reload hits disk WebP cache
        clear_cover_cache()
        pm2 = load_cover_pixmap(img_path, "Vertical Art Game", 280, 150, radius=9)
        assert not pm2.isNull()
        assert pm2.width() == 280 and pm2.height() == 150

        # CoverLabel never stretches via setScaledContents(True) and re-crops on resize
        label = CoverLabel(img_path, "Vertical Art Game", initial_width=280, fixed_height=150)
        label.show()
        assert not label.hasScaledContents()
        assert label.pixmap().width() == 280
        label.resize(340, 150)
        app.processEvents()
        assert label.pixmap().width() == 340
        assert label.pixmap().height() == 150
        label.close()

        # Typographic placeholder renders cleanly with full name when no cover exists
        ph = load_cover_pixmap(None, "Hollow Knight: Silksong", 280, 150, radius=9)
        assert not ph.isNull()
        assert ph.width() == 280 and ph.height() == 150
    finally:
        set_cover_cache_dir(None)
        clear_cover_cache()
        app.processEvents()


def test_cover_store_import_preserves_custom_cover_across_refresh_and_reset(tmp_path: Path) -> None:
    db = Database(tmp_path / "gamehub.db")
    repo = LibraryRepository(db)
    store = CoverStore(db, tmp_path)

    orig_cover = tmp_path / "steam_orig.png"
    orig_cover.write_bytes(_png_bytes(460, 215, (10, 20, 30)))
    custom_src = tmp_path / "my_custom.png"
    custom_src.write_bytes(_png_bytes(920, 430, (200, 80, 40)))

    game = DetectedGame(GameSource.STEAM, "100", "My Game", tmp_path, orig_cover)
    repo.reconcile(GameSource.STEAM, DiscoveryBatch((game,), "complete"))
    saved = repo.list_games()[0]
    assert saved.custom_cover is False

    dest = store.import_cover(saved.id, custom_src)
    assert dest.is_file()
    assert dest.name == "cover.webp"

    # Re-reconciling from Steam preserves custom cover!
    repo.reconcile(GameSource.STEAM, DiscoveryBatch((game,), "complete"))
    after_refresh = repo.get_game(saved.id)
    assert after_refresh is not None
    assert after_refresh.custom_cover is True
    assert after_refresh.cover_path == dest

    # Resetting clears custom_cover and removes managed file
    store.reset_cover(saved.id)
    assert not dest.exists()
    after_reset = repo.get_game(saved.id)
    assert after_reset is not None
    assert after_reset.custom_cover is False
    assert after_reset.cover_path is None


def test_steamgriddb_is_strictly_opt_in_and_fetches_wide_grids_when_enabled() -> None:
    called: list[str] = []

    def fake_get(url: str, headers: dict[str, str], max_bytes: int) -> bytes:
        called.append(url)
        if "/search/autocomplete/" in url:
            assert headers["Authorization"] == "Bearer secret-key"
            return json.dumps({"success": True, "data": [{"id": 777}]}).encode("utf-8")
        if "/grids/game/777" in url:
            return json.dumps(
                {"success": True, "data": [{"url": "https://cdn2.steamgriddb.com/grid/wide.png"}]}
            ).encode("utf-8")
        return _png_bytes(920, 430)

    # Disabled -> ZERO network calls
    assert fetch_steamgriddb_cover("Hades", enabled=False, api_key="secret-key", http_get=fake_get) is None
    assert called == []

    # Empty key -> ZERO network calls
    assert fetch_steamgriddb_cover("Hades", enabled=True, api_key="   ", http_get=fake_get) is None
    assert called == []

    # Enabled + valid key -> fetches wide grid bytes
    img_bytes = fetch_steamgriddb_cover("Hades", enabled=True, api_key="secret-key", http_get=fake_get)
    assert img_bytes is not None and len(img_bytes) > 32
    assert any("dimensions=460x215,920x430" in u for u in called)
