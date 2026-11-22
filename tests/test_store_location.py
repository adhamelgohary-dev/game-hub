import json
import os
import subprocess
from io import BytesIO
from pathlib import Path

import numpy
import pytest
import soundfile
from PIL import Image

from gamehub.core.storage.controls import ControlsRepository
from gamehub.core.storage.db import Database
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.location import (
    StoreLocation,
    bootstrap_path,
    resolve_data_root,
)
from gamehub.core.storage.memory import MemoryRepository
from gamehub.core.storage.notes import NoteRepository
from gamehub.core.storage.screenshots import ScreenshotRepository
from gamehub.core.storage.sessions import SessionRepository


def _webp_bytes() -> bytes:
    with BytesIO() as output:
        Image.new("RGB", (16, 16), (30, 90, 150)).save(output, format="WEBP")
        return output.getvalue()


def _voice_clip() -> bytes:
    samples = 0.05 * numpy.sin(2 * numpy.pi * 440 * numpy.arange(1600) / 16000)
    with BytesIO() as output:
        soundfile.write(output, samples, 16000, format="OGG", subtype="VORBIS")
        return output.getvalue()


def test_store_location_verified_move_and_bootstrap_resolution(tmp_path: Path) -> None:
    default_root = tmp_path / "default_store"
    db = Database(default_root / "gamehub.db")
    library = LibraryRepository(db)
    sessions = SessionRepository(db)
    screenshots = ScreenshotRepository(db, default_root)
    notes = NoteRepository(db, default_root)
    controls = ControlsRepository(db, default_root)

    exe = tmp_path / "Journey.exe"
    exe.touch()
    game_id = library.add_manual(exe)
    sid = sessions.open(game_id, 1000)
    screenshots.append(game_id, sid, _webp_bytes(), 1200, 10)
    notes.save_voice(sid, _voice_clip(), "hotkey")
    sessions.finish(sid, 9000, 8, "completed")
    controls.pin_image(game_id, _webp_bytes())

    assert resolve_data_root(default_root) == (default_root, None)

    locator = StoreLocation(default_root, default_root, db)

    # Reject non-empty and nested destinations.
    non_empty = tmp_path / "occupied"
    non_empty.mkdir()
    (non_empty / "existing.txt").write_text("hi", encoding="utf-8")
    assert locator.move(non_empty) == (False, "location_not_empty")
    assert locator.move(default_root / "nested") == (False, "location_nested")
    assert locator.move(default_root) == (False, "location_same")

    # Verified move to fresh destination succeeds and keeps previous copy.
    target = tmp_path / "moved_store"
    assert locator.move(target) == (True, None)
    assert (default_root / "gamehub.db").is_file()
    assert (target / "gamehub.db").is_file()
    assert resolve_data_root(default_root) == (target, None)

    # Reopening at the new root reads all history, screenshots, voice notes, and controls.
    moved_db = Database(target / "gamehub.db")
    moved_mem = MemoryRepository(moved_db, target)
    moved_shots = ScreenshotRepository(moved_db, target)
    moved_controls = ControlsRepository(moved_db, target)
    snap = moved_mem.last_time(game_id)
    assert snap is not None
    assert snap.voice_note is not None and snap.voice_note.available is True
    assert len(snap.screenshots) == 1 and moved_shots.read_image(snap.screenshots[0]) is not None
    assert len(snap.control_images) == 1 and moved_controls.read_image(snap.control_images[0]) is not None


def test_unavailable_custom_store_location_reports_recovery_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_root = tmp_path / "default_store"
    default_root.mkdir()
    missing_root = tmp_path / "unplugged_drive"
    bootstrap_path(default_root).write_text(
        json.dumps({"version": 1, "data_root": str(missing_root)}), encoding="utf-8"
    )
    resolved, error = resolve_data_root(default_root)
    assert resolved == default_root
    assert error == "store_location_unavailable"

    # Invalid bootstrap version is rejected.
    bootstrap_path(default_root).write_text(
        json.dumps({"version": 99, "data_root": str(missing_root)}), encoding="utf-8"
    )
    assert resolve_data_root(default_root) == (default_root, "store_location_invalid")

    # Mid-move failure rolls back destination and leaves bootstrap untouched.
    bootstrap_path(default_root).unlink()
    db = Database(default_root / "gamehub.db")
    locator = StoreLocation(default_root, default_root, db)
    from gamehub.core.storage import location as loc_module

    monkeypatch.setattr(
        loc_module,
        "_verify_staged_database",
        lambda _p: (_ for _ in ()).throw(OSError("corrupt staging")),
    )
    failed_dest = tmp_path / "failed_dest"
    assert locator.move(failed_dest) == (False, "location_move_failed")
    assert not bootstrap_path(default_root).exists()
    assert not failed_dest.exists()

    if os.name == "nt":
        real_dest = tmp_path / "real_dest"
        real_dest.mkdir()
        junction = tmp_path / "junction_dest"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(real_dest)],
            capture_output=True,
            check=False,
        )
        assert locator.move(junction) == (False, "location_invalid")
