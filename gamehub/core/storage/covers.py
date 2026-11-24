"""Managed local custom cover storage under <data_root>/media/<game_id>/cover.webp."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from gamehub.core.library.paths import local_path
from gamehub.core.storage.db import Database, StorageError
from gamehub.core.storage.library import LibraryRepository
from gamehub.core.storage.media import (
    UUID,
    delete_file,
    read_file,
    stage_file,
    validate_root,
)

MAX_COVER_SOURCE_BYTES = 12 * 1024 * 1024
MAX_COVER_PIXELS = 24_000_000
MAX_COVER_EDGE = 1280
ALLOWED_FORMATS = ("PNG", "JPEG", "WEBP")


def encode_cover_webp(raw_bytes: bytes) -> bytes:
    """Validate bounded image bytes, normalize orientation, strip metadata, and encode WebP."""
    if not raw_bytes or len(raw_bytes) > MAX_COVER_SOURCE_BYTES:
        raise ValueError("Selected image is empty or too large.")
    from PIL import Image, ImageOps, UnidentifiedImageError

    previous_max = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_COVER_PIXELS
    try:
        with Image.open(BytesIO(raw_bytes), formats=ALLOWED_FORMATS) as opened:
            opened.load()
            width, height = opened.size
            if width <= 0 or height <= 0 or width * height > MAX_COVER_PIXELS:
                raise ValueError("Unsupported image dimensions.")
            normalized = ImageOps.exif_transpose(opened)
            if normalized.mode not in {"RGB", "RGBA"}:
                normalized = normalized.convert("RGB")
            if max(normalized.size) > MAX_COVER_EDGE:
                normalized.thumbnail((MAX_COVER_EDGE, MAX_COVER_EDGE), Image.Resampling.LANCZOS)
            out = BytesIO()
            normalized.save(out, format="WEBP", quality=86, method=4)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("Choose a valid PNG, JPG, or WebP image.") from error
    finally:
        Image.MAX_IMAGE_PIXELS = previous_max


class CoverStore:
    """Persist user-chosen or opted-in fetched covers inside managed storage."""

    def __init__(self, database: Database, data_root: Path) -> None:
        self._database = database
        self._library = LibraryRepository(database)
        self._root = validate_root(data_root, database.path)
        self._media = self._root / "media"

    def _dest_for(self, game_id: str) -> Path:
        if not UUID.fullmatch(game_id):
            raise StorageError("Invalid game identifier for cover storage.")
        return self._media / game_id / "cover.webp"

    def import_cover(self, game_id: str, source: Path) -> Path:
        safe = local_path(source)
        if safe is None or not safe.is_file():
            raise ValueError("Choose an accessible local image file.")
        raw = read_file(safe, MAX_COVER_SOURCE_BYTES)
        if raw is None:
            raise ValueError("Selected image is empty or too large.")
        return self.import_cover_bytes(game_id, raw)

    def import_cover_bytes(self, game_id: str, raw_bytes: bytes) -> Path:
        encoded = encode_cover_webp(raw_bytes)
        dest = self._dest_for(game_id)
        tmp = dest.with_suffix(".webp.tmp")
        if tmp.exists():
            delete_file(tmp, "cover_temp_cleanup_failed")
        stage_file(self._media, dest, encoded)
        self._library.set_custom_cover(game_id, dest, custom=True)
        return dest

    def reset_cover(self, game_id: str) -> None:
        dest = self._dest_for(game_id)
        delete_file(dest, "cover_delete_failed")
        self._library.set_custom_cover(game_id, None, custom=False)
