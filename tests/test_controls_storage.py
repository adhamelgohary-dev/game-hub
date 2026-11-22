import os
import sqlite3
import subprocess
from contextlib import closing
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from gamehub.core.storage import db
from gamehub.core.storage.controls import (
    MAX_TEXT_LENGTH,
    ControlsRepository,
    encode_uploaded_image,
)
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository


def _webp_bytes(color: tuple[int, int, int] = (20, 60, 120)) -> bytes:
    with BytesIO() as output:
        Image.new("RGB", (32, 24), color).save(output, format="WEBP")
        return output.getvalue()


def _create_v3_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        for statement in (*db.INITIAL_SCHEMA, *db.SCREENSHOT_SCHEMA, *db.NOTE_SCHEMA):
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 3")
        connection.commit()


def test_schema_v3_migrates_to_v4_with_backup_and_preserves_history(tmp_path: Path) -> None:
    db_path = tmp_path / "gamehub.db"
    _create_v3_database(db_path)
    game_id = str(uuid4())
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "INSERT INTO games (id, source, source_id, name, added_at) "
            "VALUES (?, 'manual', ?, 'Legacy Title', 1000)",
            (game_id, game_id),
        )
        connection.commit()

    upgraded = Database(db_path)
    with upgraded.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert connection.execute("SELECT name FROM games WHERE id = ?", (game_id,)).fetchone()[0] == "Legacy Title"

    backup = tmp_path / "gamehub.db-v3.bak"
    assert backup.is_file()
    with closing(sqlite3.connect(backup)) as old:
        assert old.execute("PRAGMA user_version").fetchone()[0] == 3


def test_failed_v3_to_v4_migration_rolls_back_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "gamehub.db"
    _create_v3_database(db_path)
    broken = (*db.CONTROLS_SCHEMA, "CREATE TABLE controls (id TEXT PRIMARY KEY)")
    monkeypatch.setattr(db, "CONTROLS_SCHEMA", broken)
    with pytest.raises(StorageError):
        Database(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE name = 'controls'"
            ).fetchone()
            is None
        )

    monkeypatch.undo()
    repaired = Database(db_path)
    with repaired.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_controls_pin_scoping_and_metadata_stripping_import(tmp_path: Path) -> None:
    database = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(database)
    controls = ControlsRepository(database, tmp_path)

    exe_a = tmp_path / "Alpha.exe"
    exe_b = tmp_path / "Beta.exe"
    exe_a.touch()
    exe_b.touch()
    game_a = library.add_manual(exe_a)
    game_b = library.add_manual(exe_b)

    # Save a PNG with embedded text metadata and verify import strips it into managed WebP.
    upload = tmp_path / "bindings.png"
    exif = Image.Exif()
    exif[0x010E] = "Sensitive Camera Description"
    Image.new("RGBA", (64, 48), (10, 120, 200, 255)).save(upload, format="PNG", exif=exif)

    img_id = controls.import_image(game_a, upload)
    txt_id = controls.pin_text(game_a, "  Parry with Q, dodge with Space.  ")
    controls.pin_text(game_b, "Beta-only note.")

    items_a = controls.list_controls(game_a)
    items_b = controls.list_controls(game_b)
    assert [item.id for item in items_a] == [img_id, txt_id]
    assert items_a[0].kind == "image" and items_a[0].available is True and items_a[0].path is not None
    assert items_a[1].kind == "text" and items_a[1].text == "Parry with Q, dodge with Space."
    assert len(items_b) == 1 and items_b[0].text == "Beta-only note."

    stored_bytes = controls.read_image(items_a[0].path)
    assert stored_bytes is not None
    assert b"Sensitive Camera Description" not in stored_bytes
    with Image.open(BytesIO(stored_bytes)) as decoded:
        assert decoded.format == "WEBP"
        assert decoded.size == (64, 48)


def test_controls_rejects_unsafe_imports_and_recovers_orphans(tmp_path: Path) -> None:
    database = Database(tmp_path / "gamehub.db")
    library = LibraryRepository(database)
    controls = ControlsRepository(database, tmp_path)

    exe = tmp_path / "Solo.exe"
    exe.touch()
    game_id = library.add_manual(exe)

    not_image = tmp_path / "notes.txt"
    not_image.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError):
        encode_uploaded_image(not_image)

    with pytest.raises(ValueError):
        controls.pin_text(game_id, "   ")
    with pytest.raises(ValueError):
        controls.pin_text(game_id, "bad\x00note")
    with pytest.raises(ValueError):
        controls.pin_text(game_id, "x" * (MAX_TEXT_LENGTH + 1))

    if os.name == "nt":
        real_dir = tmp_path / "real_img"
        real_dir.mkdir()
        pic = real_dir / "pic.png"
        Image.new("RGB", (16, 16), (1, 2, 3)).save(pic, format="PNG")
        junction = tmp_path / "linked_img"
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(real_dir)],
            capture_output=True,
            check=False,
        )
        assert created.returncode == 0
        with pytest.raises(ValueError):
            encode_uploaded_image(junction / "pic.png")

    owned_id = controls.pin_image(game_id, _webp_bytes())
    controls_dir = tmp_path / "media" / game_id / "controls"
    orphan = controls_dir / f"control_{uuid4()}.webp"
    abandoned_tmp = controls_dir / f"control_{uuid4()}.webp.tmp"
    unrelated = controls_dir / "keep-me.txt"
    orphan.write_bytes(_webp_bytes())
    abandoned_tmp.write_bytes(_webp_bytes())
    unrelated.write_text("user file", encoding="utf-8")

    # A junction placed inside managed controls storage must never touch outside files.
    outside_target = tmp_path / "outside_precious"
    outside_target.mkdir()
    outside_file = outside_target / f"control_{uuid4()}.webp"
    outside_file.write_bytes(_webp_bytes())
    if os.name == "nt":
        managed_junction = controls_dir / f"control_{uuid4()}.webp"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(managed_junction), str(outside_target)],
            capture_output=True,
            check=False,
        )

    assert controls.read_image(orphan) is None
    assert controls.read_image(tmp_path / "media" / ".." / "outside.webp") is None

    controls.recover_files()
    assert not orphan.exists()
    assert not abandoned_tmp.exists()
    assert unrelated.exists()
    assert outside_file.exists()
    assert (controls_dir / f"control_{owned_id}.webp").exists()

    # Missing owned file stays in list_controls with available=False.
    (controls_dir / f"control_{owned_id}.webp").unlink()
    listed = controls.list_controls(game_id)
    assert len(listed) == 1 and listed[0].available is False
    assert controls.read_image(listed[0].path) is None
