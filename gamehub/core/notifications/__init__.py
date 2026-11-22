"""Passive OS notification adapters (never creates windows over games or tray icons)."""

from .windows import WindowsNotifier

__all__ = ["WindowsNotifier"]
