"""Windows 11 / Fluent QSS theme system, app icon loader, and smooth page transitions."""

import os
import sys
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QStyle, QWidget

if os.name == "nt":
    import winreg

DARK_TOKENS: dict[str, str] = {
    "bg_canvas": "#17191E",
    "bg_shell": "#1E2128",
    "bg_card": "#252933",
    "bg_card_hover": "#2D323E",
    "bg_input": "#1B1E25",
    "bg_elevated": "#292E3A",
    "border": "#343947",
    "border_strong": "#464D5F",
    "text": "#F3F5F8",
    "text_sec": "#A4ABBB",
    "text_muted": "#7A8194",
    "accent": "#4CC2FF",
    "accent_hover": "#6AD0FF",
    "accent_pressed": "#35AEEC",
    "accent_fg": "#0B1924",
    "strict_bg": "#1B3A2B",
    "strict_fg": "#7DE071",
    "full_bg": "#1B314A",
    "full_fg": "#6CD0FF",
    "error_bg": "#3F1D21",
    "error_fg": "#FF9494",
    "scroll_handle": "#3E4556",
}

LIGHT_TOKENS: dict[str, str] = {
    "bg_canvas": "#F3F5F9",
    "bg_shell": "#E8EEF5",
    "bg_card": "#FFFFFF",
    "bg_card_hover": "#F5F8FC",
    "bg_input": "#F8FAFD",
    "bg_elevated": "#FFFFFF",
    "border": "#D4DCE7",
    "border_strong": "#B6C2D4",
    "text": "#14171F",
    "text_sec": "#4E5668",
    "text_muted": "#757E91",
    "accent": "#0067C0",
    "accent_hover": "#0058A6",
    "accent_pressed": "#004B8D",
    "accent_fg": "#FFFFFF",
    "strict_bg": "#DFF6DD",
    "strict_fg": "#0F6B0F",
    "full_bg": "#E5F1FB",
    "full_fg": "#005FB8",
    "error_bg": "#FDE7E9",
    "error_fg": "#B42318",
    "scroll_handle": "#C0CBD9",
}


def detect_system_theme() -> Literal["dark", "light"]:
    """Read Windows AppsUseLightTheme read-only; fall back to dark if unavailable."""
    if os.name != "nt":
        return "dark"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value == 1 else "dark"
    except OSError:
        return "dark"


def resolve_theme(preference: str) -> Literal["dark", "light"]:
    if preference == "light":
        return "light"
    if preference == "system":
        return detect_system_theme()
    return "dark"


def build_stylesheet(mode: Literal["dark", "light"]) -> str:
    t = LIGHT_TOKENS if mode == "light" else DARK_TOKENS
    return f"""
    QMainWindow, QDialog, QWidget#canvas {{
        background-color: {t["bg_canvas"]};
        color: {t["text"]};
    }}
    QWidget#tabSurface {{
        background-color: {t["bg_card"]};
        color: {t["text"]};
    }}
    QWidget {{
        color: {t["text"]};
        font-family: "Segoe UI Variable", "Segoe UI", "Tahoma", sans-serif;
        font-size: 13px;
    }}
    QStatusBar {{
        background-color: {t["bg_shell"]};
        color: {t["text_sec"]};
        border-top: 1px solid {t["border"]};
        padding: 2px 10px;
    }}
    QFrame#sidebar {{
        background-color: {t["bg_shell"]};
        border-right: 1px solid {t["border"]};
        border-left: 1px solid {t["border"]};
    }}
    QFrame#panelCard, QFrame#heroCard, QFrame#gameCard, QGroupBox {{
        background-color: {t["bg_card"]};
        border: 1px solid {t["border"]};
        border-radius: 12px;
    }}
    QFrame#gameCard:hover {{
        background-color: {t["bg_card_hover"]};
        border: 1px solid {t["accent"]};
    }}
    QFrame#gameCard[selected="true"] {{
        border: 1.5px solid {t["accent"]};
    }}
    QFrame#innerCard {{
        background-color: {t["bg_input"]};
        border: 1px solid {t["border"]};
        border-radius: 9px;
    }}
    QGroupBox {{
        margin-top: 12px;
        padding: 16px 14px 14px 14px;
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 8px;
        color: {t["accent"]};
    }}
    QLabel {{
        background: transparent;
    }}
    QLabel#pageTitle {{
        font-size: 22px;
        font-weight: 700;
    }}
    QLabel#sectionHeading {{
        font-size: 15px;
        font-weight: 700;
    }}
    QLabel#cardTitle {{
        font-size: 14px;
        font-weight: 700;
    }}
    QLabel#mutedText {{
        color: {t["text_sec"]};
        font-size: 12px;
    }}
    QLabel#badgeStrict {{
        background-color: {t["strict_bg"]};
        color: {t["strict_fg"]};
        border-radius: 9px;
        padding: 2px 9px;
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#badgeFull {{
        background-color: {t["full_bg"]};
        color: {t["full_fg"]};
        border-radius: 9px;
        padding: 2px 9px;
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#errorBanner, QLabel#libraryError {{
        background-color: {t["error_bg"]};
        color: {t["error_fg"]};
        border: 1px solid {t["error_fg"]};
        border-radius: 8px;
        padding: 8px 12px;
    }}
    QLabel#carouselDot {{
        color: {t["text_muted"]};
        font-size: 11px;
        padding: 0 2px;
    }}
    QLabel#carouselDot[active="true"] {{
        color: {t["accent"]};
        font-size: 12px;
    }}
    QPushButton {{
        background-color: {t["bg_card"]};
        color: {t["text"]};
        border: 1px solid {t["border_strong"]};
        border-radius: 7px;
        padding: 7px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {t["bg_card_hover"]};
        border-color: {t["accent"]};
    }}
    QPushButton:pressed {{
        background-color: {t["bg_input"]};
    }}
    QPushButton:disabled {{
        color: {t["text_muted"]};
        border-color: {t["border"]};
    }}
    QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
        border: 1.5px solid {t["accent"]};
    }}
    QPushButton#primaryButton {{
        background-color: {t["accent"]};
        color: {t["accent_fg"]};
        border: 1px solid {t["accent"]};
        font-weight: 700;
    }}
    QPushButton#primaryButton:hover {{
        background-color: {t["accent_hover"]};
        border-color: {t["accent_hover"]};
    }}
    QPushButton#primaryButton:pressed {{
        background-color: {t["accent_pressed"]};
    }}
    QPushButton#primaryButton:disabled {{
        background-color: {t["border"]};
        border-color: {t["border"]};
        color: {t["text_muted"]};
    }}
    QPushButton#navButton {{
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 10px 14px;
        text-align: left;
        color: {t["text_sec"]};
        font-weight: 600;
    }}
    QPushButton#navButton:hover {{
        background-color: {t["bg_card"]};
        color: {t["text"]};
    }}
    QPushButton#navButton[active="true"] {{
        background-color: {t["bg_card"]};
        border: 1px solid {t["border"]};
        color: {t["text"]};
        font-weight: 700;
    }}
    QPushButton#chipButton {{
        border-radius: 14px;
        padding: 5px 13px;
        font-size: 12px;
        background-color: {t["bg_card"]};
        color: {t["text_sec"]};
        border: 1px solid {t["border"]};
    }}
    QPushButton#chipButton:checked {{
        background-color: {t["full_bg"]};
        color: {t["full_fg"]};
        border: 1px solid {t["accent"]};
    }}
    QPushButton#overflowButton {{
        padding: 7px 12px;
        font-size: 15px;
        font-weight: 700;
        min-width: 40px;
    }}
    QPushButton#overflowButton::menu-indicator {{
        image: none;
        width: 0px;
    }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
        background-color: {t["bg_input"]};
        color: {t["text"]};
        border: 1px solid {t["border_strong"]};
        border-radius: 7px;
        padding: 6px 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t["bg_elevated"]};
        color: {t["text"]};
        border: 1px solid {t["border_strong"]};
        selection-background-color: {t["accent"]};
        selection-color: {t["accent_fg"]};
    }}
    QMenu {{
        background-color: {t["bg_elevated"]};
        color: {t["text"]};
        border: 1px solid {t["border_strong"]};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 7px 18px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background-color: {t["accent"]};
        color: {t["accent_fg"]};
    }}
    QTabWidget::pane {{
        border: 1px solid {t["border"]};
        border-radius: 10px;
        background-color: {t["bg_card"]};
        padding: 8px;
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {t["text_sec"]};
        padding: 8px 18px;
        margin-right: 4px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background-color: {t["bg_card"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        border-bottom: 2px solid {t["accent"]};
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t["scroll_handle"]};
        border-radius: 4px;
        min-height: 28px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t["scroll_handle"]};
        border-radius: 4px;
        min-width: 28px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QCheckBox {{
        spacing: 8px;
        background: transparent;
    }}
    """


def apply_theme(app: QApplication, preference: str) -> Literal["dark", "light"]:
    resolved = resolve_theme(preference)
    app.setStyleSheet(build_stylesheet(resolved))
    app.setProperty("gamehub_theme", resolved)
    return resolved


def app_icon_path() -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets" / "GameHub.png")
            candidates.append(Path(meipass) / "assets" / "GameHub.ico")
    repo_assets = Path(__file__).resolve().parents[2] / "packaging" / "assets"
    candidates.append(repo_assets / "GameHub.png")
    candidates.append(repo_assets / "GameHub.ico")
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_app_icon(widget: QWidget | None = None) -> QIcon:
    path = app_icon_path()
    if path is not None:
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    if widget is not None:
        return widget.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    return QIcon()


def fade_in_widget(widget: QWidget, duration_ms: int = 160) -> None:
    """Apply a lightweight fade-in transition on interactive desktops; no-op offscreen."""
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration_ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _cleanup() -> None:
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    anim.finished.connect(_cleanup)
    widget._fade_animation = anim  # type: ignore[attr-defined]
    anim.start()
