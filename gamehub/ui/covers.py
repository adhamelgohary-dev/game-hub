"""Load local game cover artwork with zero-stretch cropping, disk WebP cache, and clean placeholders."""

from __future__ import annotations

import os
from collections import OrderedDict
from hashlib import blake2b
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

_MAX_COVER_PIXELS = 24_000_000
_MAX_CACHE_ITEMS = 192

_PALETTES: tuple[tuple[str, str], ...] = (
    ("#2B1D47", "#7C2D12"),
    ("#0F172A", "#1D4ED8"),
    ("#450A0A", "#B91C1C"),
    ("#1E293B", "#9A6700"),
    ("#3B0764", "#BE185D"),
    ("#064E3B", "#0F766E"),
    ("#172554", "#4338CA"),
    ("#1F2937", "#4B5563"),
)

_CACHE: OrderedDict[tuple[str, int, int, str, int, int, int], QPixmap] = OrderedDict()
_DISK_CACHE_DIR: Path | None = None


def set_cover_cache_dir(cache_dir: Path | None) -> None:
    """Configure the on-disk WebP thumbnail cache directory (e.g. <data_root>/cache/covers)."""
    global _DISK_CACHE_DIR
    _DISK_CACHE_DIR = cache_dir
    if cache_dir is not None:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            _DISK_CACHE_DIR = None


def clear_cover_cache() -> None:
    """Clear the in-memory cover pixmap cache."""
    _CACHE.clear()


def _monogram(name: str) -> str:
    words = [part for part in name.replace(":", " ").replace("-", " ").split() if part]
    if not words:
        return "GH"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(word[0] for word in words[:3]).upper()


def _file_signature(path: Path | None) -> tuple[str, int, int]:
    if path is None:
        return ("", 0, 0)
    try:
        st = path.stat()
        return (os.path.normcase(str(path)), st.st_mtime_ns, st.st_size)
    except OSError:
        return (os.path.normcase(str(path)), 0, 0)


def _disk_cache_path(
    norm_path: str, mtime_ns: int, size: int, width: int, height: int, radius: int
) -> Path | None:
    if _DISK_CACHE_DIR is None or not norm_path or size <= 0:
        return None
    raw = f"{norm_path}|{mtime_ns}|{size}|{width}x{height}|r{radius}".encode("utf-8", "ignore")
    digest = blake2b(raw, digest_size=16).hexdigest()
    return _DISK_CACHE_DIR / f"{digest}.webp"


def _load_cached_disk_pixmap(cache_file: Path) -> QPixmap | None:
    try:
        if not cache_file.is_file():
            return None
        image = QImage(str(cache_file), "WEBP")
        if image.isNull():
            return None
        return QPixmap.fromImage(image)
    except OSError:
        return None


def _save_cached_disk_pixmap(cache_file: Path, pixmap: QPixmap) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".webp.tmp")
        if pixmap.toImage().save(str(tmp), "WEBP", 85):
            tmp.replace(cache_file)
        else:
            tmp.unlink(missing_ok=True)
    except OSError:
        pass


def _load_local_image(path: Path, width: int, height: int) -> QPixmap | None:
    try:
        if not path.is_file():
            return None
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isEmpty() or size.width() * size.height() > _MAX_COVER_PIXELS:
            return None
        scaled = size.scaled(
            QSize(max(width * 2, 320), max(height * 2, 180)),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        )
        reader.setScaledSize(scaled)
        image = reader.read()
        if image.isNull():
            return None
        return QPixmap.fromImage(image)
    except OSError:
        return None


def _rounded_crop(source: QPixmap, width: int, height: int, radius: int) -> QPixmap:
    fitted = source.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (fitted.width() - width) // 2)
    y = max(0, (fitted.height() - height) // 2)
    cropped = fitted.copy(x, y, width, height)

    result = QPixmap(width, height)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, width, height, radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return result


def _placeholder(game_name: str, width: int, height: int, radius: int) -> QPixmap:
    digest = blake2b(game_name.encode("utf-8", errors="ignore"), digest_size=2).digest()
    c1, c2 = _PALETTES[int.from_bytes(digest, "big") % len(_PALETTES)]

    pm = QPixmap(width, height)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, width, height, radius, radius)
    p.setClipPath(clip)

    grad = QLinearGradient(0, 0, width, height)
    grad.setColorAt(0.0, QColor(c1))
    grad.setColorAt(1.0, QColor(c2))
    p.fillRect(0, 0, width, height, grad)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 22))
    orb = max(18, int(min(width, height) * 0.48))
    p.drawEllipse(int(width * 0.66), int(height * 0.08), orb, orb)

    p.setBrush(QColor(0, 0, 0, 72))
    hill = QPainterPath()
    hill.moveTo(0, height)
    hill.lineTo(0, height * 0.74)
    hill.lineTo(width * 0.30, height * 0.50)
    hill.lineTo(width * 0.56, height * 0.70)
    hill.lineTo(width * 0.82, height * 0.44)
    hill.lineTo(width, height * 0.62)
    hill.lineTo(width, height)
    hill.closeSubpath()
    p.drawPath(hill)

    # Subtle monogram watermark in top corner
    p.setPen(QColor(255, 255, 255, 70))
    wm_size = max(9, min(14, height // 10))
    p.setFont(QFont("Segoe UI", wm_size, QFont.Weight.Bold))
    p.drawText(
        QRect(12, 8, max(20, width - 24), max(16, height // 3)),
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        _monogram(game_name),
    )

    # Full game name as clean typographic title
    p.setPen(QColor(255, 255, 255, 235))
    title_size = max(9, min(15, height // 9))
    p.setFont(QFont("Segoe UI", title_size, QFont.Weight.DemiBold))
    p.drawText(
        QRect(12, max(20, height // 4), max(20, width - 24), max(24, height - height // 4 - 10)),
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
        game_name.strip() or "Game",
    )
    p.end()
    return pm


def load_cover_pixmap(
    cover_path: Path | None,
    game_name: str,
    width: int,
    height: int,
    *,
    radius: int = 10,
) -> QPixmap:
    """Return a center-cropped rounded cover pixmap (disk-cached WebP) or typographic placeholder."""
    w = max(32, int(width))
    h = max(24, int(height))
    norm_path, mtime_ns, fsize = _file_signature(cover_path)
    key = (norm_path, mtime_ns, fsize, game_name, w, h, radius)
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached

    cache_file = _disk_cache_path(norm_path, mtime_ns, fsize, w, h, radius)
    pixmap: QPixmap | None = None
    if cache_file is not None:
        pixmap = _load_cached_disk_pixmap(cache_file)

    if pixmap is None:
        loaded = _load_local_image(cover_path, w, h) if cover_path is not None else None
        if loaded is not None:
            pixmap = _rounded_crop(loaded, w, h, radius)
            if cache_file is not None:
                _save_cached_disk_pixmap(cache_file, pixmap)
        else:
            pixmap = _placeholder(game_name, w, h, radius)

    _CACHE[key] = pixmap
    if len(_CACHE) > _MAX_CACHE_ITEMS:
        _CACHE.popitem(last=False)
    return pixmap


class CoverLabel(QLabel):
    """Aspect-preserving cover banner that center-crops on resize with zero stretching."""

    def __init__(
        self,
        cover_path: Path | None,
        game_name: str,
        *,
        initial_width: int = 280,
        fixed_height: int = 150,
        radius: int = 9,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cover_path = cover_path
        self._game_name = game_name
        self._radius = radius
        self._rendered_size = (0, 0)
        self.setFixedHeight(fixed_height)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(False)
        self._render_for(initial_width, fixed_height)

    def set_cover(self, cover_path: Path | None, game_name: str) -> None:
        self._cover_path = cover_path
        self._game_name = game_name
        self._rendered_size = (0, 0)
        w = self.width() if self.width() >= 48 else 280
        h = self.height() if self.height() >= 32 else self.minimumHeight() or 150
        self._render_for(w, h)

    def _render_for(self, width: int, height: int) -> None:
        w = max(48, width)
        h = max(32, height)
        if self._rendered_size == (w, h):
            return
        self._rendered_size = (w, h)
        self.setPixmap(load_cover_pixmap(self._cover_path, self._game_name, w, h, radius=self._radius))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        size = event.size()
        if size.width() >= 48 and size.height() >= 32:
            self._render_for(size.width(), size.height())
