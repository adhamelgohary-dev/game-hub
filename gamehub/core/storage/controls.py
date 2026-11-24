"""Store per-game pinned control images and strategy text notes."""

import logging
import re
import sqlite3
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from time import time_ns
from uuid import uuid4

from gamehub.core.library.paths import local_path
from gamehub.core.storage import media
from gamehub.core.storage.db import Database, StorageError

LOGGER = logging.getLogger(__name__)
MAX_TEXT_LENGTH = 8_000
MAX_IMPORT_BYTES = 16 * 1024 * 1024
MAX_CONTROL_WEBP_BYTES = 16 * 1024 * 1024
MAX_IMPORT_PIXELS = 33_177_600
_ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "BMP"}
_CONTROL_NAME = re.compile(rf"control_({media.UUID_PATTERN})\.webp")
_FILENAME = re.compile(rf"control_{media.UUID_PATTERN}\.webp(?:\.tmp)?")


@dataclass(frozen=True, slots=True)
class ControlItem:
    id: str
    game_id: str
    kind: str
    created_at: int
    text: str | None = None
    path: Path | None = None
    available: bool = True


def control_image_path(game_id: str, control_id: str) -> PurePosixPath:
    return PurePosixPath("media", game_id, "controls", f"control_{control_id}.webp")


def is_bounded_webp(data: bytes) -> bool:
    return (
        12 <= len(data) <= MAX_CONTROL_WEBP_BYTES
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    )


def encode_uploaded_image(source: Path) -> bytes:
    """Safely read, validate, strip metadata, and re-encode a local image to WebP."""
    validated = local_path(source)
    if validated is None:
        raise ValueError("Select a supported local image (PNG, JPEG, WebP, or BMP) up to 16 MB.")
    try:
        raw = media.read_file(validated, MAX_IMPORT_BYTES)
    except (FileNotFoundError, OSError) as error:
        raise ValueError(
            "Select a supported local image (PNG, JPEG, WebP, or BMP) up to 16 MB."
        ) from error
    if not raw:
        raise ValueError("Select a supported local image (PNG, JPEG, WebP, or BMP) up to 16 MB.")

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(BytesIO(raw), formats=tuple(_ALLOWED_FORMATS)) as loaded:
            if loaded.format not in _ALLOWED_FORMATS:
                raise ValueError("Unsupported image format.")
            width, height = loaded.size
            if width <= 0 or height <= 0 or width * height > MAX_IMPORT_PIXELS:
                raise ValueError("Image dimensions exceed the safety limit.")
            transposed = ImageOps.exif_transpose(loaded)
            mode = "RGBA" if "A" in transposed.getbands() else "RGB"
            with transposed.convert(mode) as clean, BytesIO() as output:
                clean.thumbnail((1600, 1000))
                clean.save(output, "WEBP", quality=85, method=3)
                encoded = output.getvalue()
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as error:
        raise ValueError(
            "Select a supported local image (PNG, JPEG, WebP, or BMP) up to 16 MB."
        ) from error

    if not is_bounded_webp(encoded):
        raise ValueError("GameRewind could not encode this image.")
    return encoded


def _require_game(connection: sqlite3.Connection, game_id: str) -> None:
    if not media.UUID.fullmatch(game_id):
        raise StorageError("GameRewind could not validate this game.")
    row = connection.execute("SELECT 1 FROM games WHERE id = ? AND hidden = 0", (game_id,)).fetchone()
    if row is None:
        raise StorageError("GameRewind could not find this game.")


class ControlsRepository:
    def __init__(self, database: Database, data_root: Path) -> None:
        self._database = database
        self._root = media.validate_root(data_root, database.path)
        self._media = self._root / "media"

    def pin_image(self, game_id: str, data: bytes) -> str:
        """Persist a bounded WebP controls image under managed game storage."""
        if not is_bounded_webp(data):
            raise ValueError("Expected a bounded WebP controls image.")

        control_id = str(uuid4())
        created_at = time_ns() // 1_000_000
        try:
            with self._database.write() as connection:
                _require_game(connection, game_id)
                relative = control_image_path(game_id, control_id)
                media.stage_file(self._media, self._root.joinpath(*relative.parts), data)
                connection.execute(
                    "INSERT INTO controls (id, game_id, kind, path_or_text, created_at) "
                    "VALUES (?, ?, 'image', ?, ?)",
                    (control_id, game_id, relative.as_posix(), created_at),
                )
        except OSError as error:
            raise StorageError("GameRewind could not save this controls image.") from error
        return control_id

    def import_image(self, game_id: str, source: Path) -> str:
        """Validate, sanitize, re-encode, and store a user-selected local image."""
        return self.pin_image(game_id, encode_uploaded_image(source))

    def pin_text(self, game_id: str, text: str) -> str:
        """Validate and save a per-game controls or strategy text note."""
        if not isinstance(text, str) or "\0" in text or len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Controls note text must be nonblank and within the character limit.")
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Controls note text must be nonblank and within the character limit.")

        control_id = str(uuid4())
        created_at = time_ns() // 1_000_000
        with self._database.write() as connection:
            _require_game(connection, game_id)
            connection.execute(
                "INSERT INTO controls (id, game_id, kind, path_or_text, created_at) "
                "VALUES (?, ?, 'text', ?, ?)",
                (control_id, game_id, cleaned, created_at),
            )
        return control_id

    def list_controls(self, game_id: str) -> tuple[ControlItem, ...]:
        """List pinned control images and text notes for a game in chronological order."""
        if not media.UUID.fullmatch(game_id):
            return ()
        with self._database.read() as connection:
            rows = connection.execute(
                "SELECT id, game_id, kind, path_or_text, created_at FROM controls "
                "WHERE game_id = ? ORDER BY created_at, id",
                (game_id,),
            ).fetchall()

        items: list[ControlItem] = []
        for row in rows:
            control_id = row["id"]
            if row["kind"] == "text":
                items.append(
                    ControlItem(
                        id=control_id,
                        game_id=game_id,
                        kind="text",
                        created_at=row["created_at"],
                        text=row["path_or_text"],
                    )
                )
            elif media.UUID.fullmatch(control_id):
                relative = control_image_path(game_id, control_id)
                if row["path_or_text"] == relative.as_posix():
                    path = self._root.joinpath(*relative.parts)
                    items.append(
                        ControlItem(
                            id=control_id,
                            game_id=game_id,
                            kind="image",
                            created_at=row["created_at"],
                            path=path,
                            available=self._image_available(path),
                        )
                    )
        return tuple(items)

    def read_image(self, path: Path) -> bytes | None:
        """Read bounded WebP bytes for a validated, database-owned controls image."""
        if not path.is_relative_to(self._media):
            return None
        relative = path.relative_to(self._root)
        parts = relative.parts
        match = _CONTROL_NAME.fullmatch(parts[3]) if len(parts) == 4 else None
        if (
            match is None
            or parts[0] != "media"
            or not media.UUID.fullmatch(parts[1])
            or parts[2] != "controls"
        ):
            return None

        game_id, control_id = parts[1], match[1]
        try:
            with self._database.read() as connection:
                owned = connection.execute(
                    "SELECT 1 FROM controls "
                    "WHERE id = ? AND game_id = ? AND kind = 'image' AND path_or_text = ?",
                    (control_id, game_id, relative.as_posix()),
                ).fetchone()
                if owned is None:
                    return None
            canonical = self._root.joinpath(*parts)
            data = media.read_file(canonical, MAX_CONTROL_WEBP_BYTES)
            return data if data is not None and is_bounded_webp(data) else None
        except FileNotFoundError:
            return None
        except (OSError, StorageError):
            LOGGER.warning("controls_image_read_incomplete")
            return None

    def recover_files(self) -> None:
        """Remove unreferenced or abandoned control images while preserving owned items."""
        with self._database.write() as connection:
            rows = connection.execute(
                "SELECT id, game_id, path_or_text FROM controls WHERE kind = 'image'"
            )
            owned = {
                row["path_or_text"]
                for row in rows
                if media.UUID.fullmatch(row["game_id"])
                and media.UUID.fullmatch(row["id"])
                and row["path_or_text"] == control_image_path(row["game_id"], row["id"]).as_posix()
            }
            media.reconcile_game_subfolder(
                self._media, "controls", owned, _FILENAME, "controls_reconciliation_incomplete"
            )

    def _image_available(self, path: Path) -> bool:
        try:
            prefix = media.read_file(path, MAX_CONTROL_WEBP_BYTES, prefix_bytes=12)
        except (FileNotFoundError, OSError):
            return False
        return prefix is not None and len(prefix) == 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
