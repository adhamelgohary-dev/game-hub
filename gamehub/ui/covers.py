"""Load local game cover artwork with bounded decoding and stylized fallback placeholders."""

from collections import OrderedDict
from hashlib import blake2b
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)

_MAX_COVER_PIXELS = 24_000_000
_MAX_CACHE_ITEMS = 128

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

_CACHE: OrderedDict[tuple[str, str, int, int, int], QPixmap] = OrderedDict()


def _monogram(name: str) -> str:
    words = [part for part in name.replace(":", " ").replace("-", " ").split() if part]
    if not words:
        return "GH"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(word[0] for word in words[:3]).upper()


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
    p.setBrush(QColor(255, 255, 255, 28))
    orb = max(16, int(min(width, height) * 0.42))
    p.drawEllipse(int(width * 0.65), int(height * 0.12), orb, orb)

    p.setBrush(QColor(0, 0, 0, 75))
    hill = QPainterPath()
    hill.moveTo(0, height)
    hill.lineTo(0, height * 0.72)
    hill.lineTo(width * 0.30, height * 0.48)
    hill.lineTo(width * 0.56, height * 0.68)
    hill.lineTo(width * 0.82, height * 0.42)
    hill.lineTo(width, height * 0.60)
    hill.lineTo(width, height)
    hill.closeSubpath()
    p.drawPath(hill)

    p.setPen(QColor(255, 255, 255, 210))
    font_size = max(10, min(22, height // 6))
    p.setFont(QFont("Segoe UI", font_size, QFont.Weight.Bold))
    p.drawText(
        pm.rect().adjusted(10, 8, -10, -8),
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
        _monogram(game_name),
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
    """Return a rounded cover pixmap from local art if valid, else a stylized placeholder."""
    key = (str(cover_path) if cover_path is not None else "", game_name, width, height, radius)
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached

    loaded = _load_local_image(cover_path, width, height) if cover_path is not None else None
    pixmap = (
        _rounded_crop(loaded, width, height, radius)
        if loaded is not None
        else _placeholder(game_name, width, height, radius)
    )
    _CACHE[key] = pixmap
    if len(_CACHE) > _MAX_CACHE_ITEMS:
        _CACHE.popitem(last=False)
    return pixmap
