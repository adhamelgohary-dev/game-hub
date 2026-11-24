"""Load local game cover artwork asynchronously with zero-stretch cropping and disk WebP cache."""

from __future__ import annotations

import os
import stat
import time
import weakref
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from hashlib import blake2b
from pathlib import Path
from threading import Lock

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QCoreApplication,
    QIODevice,
    QObject,
    QRect,
    QSize,
    Qt,
    Signal,
)
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

from gamehub.core.library.paths import local_path
from gamehub.core.storage import media

_MAX_COVER_PIXELS = 24_000_000
_MAX_COVER_SOURCE_BYTES = 24 * 1024 * 1024
_MAX_CACHE_WEBP_BYTES = 4 * 1024 * 1024
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

_CacheKey = tuple[str, int, int, str, int, int, int]
_CACHE: OrderedDict[_CacheKey, QPixmap] = OrderedDict()
_DISK_CACHE_DIR: Path | None = None
_LOADER: _AsyncCoverLoader | None = None


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def set_cover_cache_dir(cache_dir: Path | None) -> None:
    """Configure the on-disk WebP thumbnail cache directory (e.g. <data_root>/cache/covers)."""
    global _DISK_CACHE_DIR
    if cache_dir is None:
        _DISK_CACHE_DIR = None
        return
    try:
        safe = local_path(cache_dir)
        if safe is None:
            _DISK_CACHE_DIR = None
            return
        safe.mkdir(parents=True, exist_ok=True)
        verified = local_path(safe)
        if verified is None or _is_reparse(verified.lstat()):
            _DISK_CACHE_DIR = None
            return
        _DISK_CACHE_DIR = verified
    except OSError:
        _DISK_CACHE_DIR = None


def clear_cover_cache() -> None:
    """Clear the in-memory cover pixmap cache."""
    _CACHE.clear()


def shutdown_cover_loader(*, wait: bool = False) -> None:
    """Shut down the background cover decode worker pool cleanly."""
    global _LOADER
    loader = _LOADER
    _LOADER = None
    if loader is not None:
        loader.close(wait=wait)


def wait_for_cover_loads(timeout_sec: float = 10.0) -> None:
    """Pump Qt events until all queued asynchronous cover decodes complete."""
    if _LOADER is None:
        return
    _LOADER.wait_for_idle(timeout_sec)


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
        safe = local_path(path)
        if safe is None:
            return ("", 0, 0)
        st = safe.lstat()
        if not stat.S_ISREG(st.st_mode) or _is_reparse(st):
            return ("", 0, 0)
        return (os.path.normcase(str(safe)), st.st_mtime_ns, st.st_size)
    except OSError:
        return ("", 0, 0)


def _disk_cache_path(
    cache_dir: Path | None,
    norm_path: str,
    mtime_ns: int,
    size: int,
    width: int,
    height: int,
    radius: int,
) -> Path | None:
    if cache_dir is None or not norm_path or size <= 0:
        return None
    raw = f"{norm_path}|{mtime_ns}|{size}|{width}x{height}|r{radius}".encode("utf-8", "ignore")
    digest = blake2b(raw, digest_size=16).hexdigest()
    return cache_dir / f"{digest}.webp"


def _load_cached_disk_image(cache_file: Path) -> QImage | None:
    try:
        safe = local_path(cache_file)
        if safe is None:
            return None
        data = media.read_file(safe, _MAX_CACHE_WEBP_BYTES)
        if not data:
            return None
        image = QImage()
        if not image.loadFromData(data, "WEBP") or image.isNull():
            return None
        return image
    except OSError:
        return None


def _save_cached_disk_image(cache_file: Path, image: QImage) -> None:
    try:
        safe_dir = local_path(cache_file.parent)
        if safe_dir is None:
            return
        safe_dir.mkdir(parents=True, exist_ok=True)
        if _is_reparse(safe_dir.lstat()):
            return
        safe_target = safe_dir / cache_file.name
        if safe_target.exists() and _is_reparse(safe_target.lstat()):
            return
        buf = QBuffer()
        if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
            return
        try:
            if not image.save(buf, "WEBP", 85):
                return
            encoded = bytes(buf.data())
        finally:
            buf.close()
        if not encoded or len(encoded) > _MAX_CACHE_WEBP_BYTES:
            return
        with media.protect_directory(safe_dir):
            tmp = safe_dir / f"{safe_target.stem}.{os.getpid()}.{time.time_ns()}.webp.tmp"
            try:
                with tmp.open("xb") as handle:
                    handle.write(encoded)
                tmp.replace(safe_target)
            except OSError:
                tmp.unlink(missing_ok=True)
    except OSError:
        pass


def _load_local_qimage(path: Path, width: int, height: int) -> QImage | None:
    try:
        safe = local_path(path)
        if safe is None:
            return None
        data = media.read_file(safe, _MAX_COVER_SOURCE_BYTES)
        if not data:
            return None
        raw = QByteArray(data)
        buf = QBuffer(raw)
        if not buf.open(QIODevice.OpenModeFlag.ReadOnly):
            return None
        try:
            reader = QImageReader(buf)
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
            return image
        finally:
            buf.close()
    except OSError:
        return None


def _rounded_crop_image(source: QImage, width: int, height: int, radius: int) -> QImage:
    fitted = source.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (fitted.width() - width) // 2)
    y = max(0, (fitted.height() - height) // 2)
    cropped = fitted.copy(x, y, width, height)

    result = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, width, height, radius, radius)
    painter.setClipPath(clip)
    painter.drawImage(0, 0, cropped)
    painter.end()
    return result


def _decode_cover_image(
    cover_path: Path | None,
    cache_dir: Path | None,
    norm_path: str,
    mtime_ns: int,
    fsize: int,
    width: int,
    height: int,
    radius: int,
) -> QImage | None:
    """Thread-safe worker function: disk cache hit or full local decode + crop + disk save."""
    cache_file = _disk_cache_path(cache_dir, norm_path, mtime_ns, fsize, width, height, radius)
    if cache_file is not None:
        cached = _load_cached_disk_image(cache_file)
        if cached is not None:
            return cached
    if cover_path is None:
        return None
    loaded = _load_local_qimage(cover_path, width, height)
    if loaded is None:
        return None
    cropped = _rounded_crop_image(loaded, width, height, radius)
    if cache_file is not None:
        _save_cached_disk_image(cache_file, cropped)
    return cropped


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

    p.setPen(QColor(255, 255, 255, 70))
    wm_size = max(9, min(14, height // 10))
    p.setFont(QFont("Segoe UI", wm_size, QFont.Weight.Bold))
    p.drawText(
        QRect(12, 8, max(20, width - 24), max(16, height // 3)),
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        _monogram(game_name),
    )

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


def _cache_put(key: _CacheKey, pixmap: QPixmap) -> None:
    _CACHE[key] = pixmap
    _CACHE.move_to_end(key)
    while len(_CACHE) > _MAX_CACHE_ITEMS:
        _CACHE.popitem(last=False)


class _AsyncCoverLoader(QObject):
    """Decode, crop, and WebP-cache covers off the Qt UI thread."""

    _decoded = Signal(object, object)  # (_CacheKey, QImage | None)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cover-decode")
        self._lock = Lock()
        self._inflight: dict[_CacheKey, list[weakref.ref[CoverLabel]]] = {}
        self._closed = False
        self._decoded.connect(self._on_decoded, Qt.ConnectionType.QueuedConnection)

    def request(
        self,
        key: _CacheKey,
        cover_path: Path,
        width: int,
        height: int,
        radius: int,
        target: CoverLabel,
    ) -> None:
        if self._closed:
            return
        cache_dir = _DISK_CACHE_DIR
        norm_path, mtime_ns, fsize = key[0], key[1], key[2]
        with self._lock:
            waiters = self._inflight.get(key)
            if waiters is not None:
                waiters.append(weakref.ref(target))
                return
            self._inflight[key] = [weakref.ref(target)]

        def _work() -> None:
            image = _decode_cover_image(
                cover_path, cache_dir, norm_path, mtime_ns, fsize, width, height, radius
            )
            if not self._closed:
                self._decoded.emit(key, image)

        try:
            self._pool.submit(_work)
        except RuntimeError:
            with self._lock:
                self._inflight.pop(key, None)

    def _on_decoded(self, key: _CacheKey, image: object) -> None:
        with self._lock:
            waiters = self._inflight.pop(key, [])
        if self._closed:
            return
        pixmap: QPixmap | None = None
        if isinstance(image, QImage) and not image.isNull():
            pixmap = QPixmap.fromImage(image)
            _cache_put(key, pixmap)
        for ref in waiters:
            label = ref()
            if label is not None:
                label._apply_async_result(key, pixmap)

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._inflight)

    def wait_for_idle(self, timeout_sec: float = 10.0) -> None:
        app = QCoreApplication.instance()
        deadline = time.monotonic() + max(0.1, timeout_sec)
        while time.monotonic() < deadline:
            if app is not None:
                app.processEvents()
            if not self.has_pending():
                if app is not None:
                    app.processEvents()
                if not self.has_pending():
                    return
            time.sleep(0.005)

    def close(self, *, wait: bool = False) -> None:
        self._closed = True
        with self._lock:
            self._inflight.clear()
        self._pool.shutdown(wait=wait, cancel_futures=True)


def _get_loader() -> _AsyncCoverLoader:
    global _LOADER
    if _LOADER is None or _LOADER._closed:
        app = QCoreApplication.instance()
        _LOADER = _AsyncCoverLoader(app)
    return _LOADER


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
    key: _CacheKey = (norm_path, mtime_ns, fsize, game_name, w, h, radius)
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached

    image = _decode_cover_image(
        cover_path, _DISK_CACHE_DIR, norm_path, mtime_ns, fsize, w, h, radius
    )
    if image is not None:
        pixmap = QPixmap.fromImage(image)
    else:
        pixmap = _placeholder(game_name, w, h, radius)

    _cache_put(key, pixmap)
    return pixmap


class CoverLabel(QLabel):
    """Aspect-preserving cover banner that loads covers off the UI thread with zero stretching."""

    def __init__(
        self,
        cover_path: Path | None,
        game_name: str,
        *,
        initial_width: int = 280,
        fixed_height: int = 150,
        radius: int = 9,
        defer_load: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cover_path = cover_path
        self._game_name = game_name
        self._radius = radius
        self._rendered_size = (0, 0)
        self._loaded_key: _CacheKey | None = None
        self._pending_key: _CacheKey | None = None
        self._activated = not defer_load
        self._has_real_cover = False
        self.setFixedHeight(fixed_height)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(False)
        self._render_for(initial_width, fixed_height)

    def set_cover(self, cover_path: Path | None, game_name: str) -> None:
        self._cover_path = cover_path
        self._game_name = game_name
        self._rendered_size = (0, 0)
        self._loaded_key = None
        self._pending_key = None
        self._has_real_cover = False
        w = self.width() if self.width() >= 48 else 280
        h = self.height() if self.height() >= 32 else self.minimumHeight() or 150
        self._render_for(w, h)

    def ensure_loaded(self) -> None:
        """Activate background cover decoding once this card approaches the visible viewport."""
        if self._activated:
            return
        self._activated = True
        w, h = self._rendered_size
        if w < 48 or h < 32:
            w = self.width() if self.width() >= 48 else 280
            h = self.height() if self.height() >= 32 else self.minimumHeight() or 150
        self._request_cover(w, h)

    def _render_for(self, width: int, height: int) -> None:
        w = max(48, width)
        h = max(32, height)
        if self._rendered_size == (w, h):
            return
        self._rendered_size = (w, h)

        if self._cover_path is None:
            ph_key: _CacheKey = ("", 0, 0, self._game_name, w, h, self._radius)
            pm = _CACHE.get(ph_key)
            if pm is None:
                pm = _placeholder(self._game_name, w, h, self._radius)
                _cache_put(ph_key, pm)
            self._loaded_key = ph_key
            self._pending_key = None
            self.setPixmap(pm)
            return

        if not self._activated:
            # Show lightweight placeholder immediately until card enters visible viewport.
            ph_key = ("", 0, 0, self._game_name, w, h, self._radius)
            pm = _CACHE.get(ph_key)
            if pm is None:
                pm = _placeholder(self._game_name, w, h, self._radius)
                _cache_put(ph_key, pm)
            self.setPixmap(pm)
            return

        self._request_cover(w, h)

    def _request_cover(self, w: int, h: int) -> None:
        if self._cover_path is None:
            return
        norm_path, mtime_ns, fsize = _file_signature(self._cover_path)
        key: _CacheKey = (norm_path, mtime_ns, fsize, self._game_name, w, h, self._radius)
        if self._loaded_key == key:
            return

        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            self._loaded_key = key
            self._pending_key = None
            self._has_real_cover = True
            self.setPixmap(cached)
            return

        # Keep UI thread non-blocking: show exact-size placeholder immediately, decode in background.
        ph_key: _CacheKey = ("", 0, 0, self._game_name, w, h, self._radius)
        ph = _CACHE.get(ph_key)
        if ph is None:
            ph = _placeholder(self._game_name, w, h, self._radius)
            _cache_put(ph_key, ph)
        self.setPixmap(ph)

        if fsize <= 0:
            self._loaded_key = key
            self._pending_key = None
            return

        self._pending_key = key
        _get_loader().request(key, self._cover_path, w, h, self._radius, self)

    def _apply_async_result(self, key: _CacheKey, pixmap: QPixmap | None) -> None:
        if self._pending_key != key:
            return
        self._pending_key = None
        self._loaded_key = key
        if pixmap is not None and not pixmap.isNull():
            self._has_real_cover = True
            self.setPixmap(pixmap)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        size = event.size()
        if size.width() >= 48 and size.height() >= 32:
            self._render_for(size.width(), size.height())
