"""Protected-game catalog and anti-cheat safety classification."""

from .catalog import (
    BUNDLED_CATALOG_PATH,
    ProtectedGameDetected,
    ProtectedGameEntry,
    ProtectedGameExited,
    ProtectedGamesCatalog,
)

__all__ = [
    "BUNDLED_CATALOG_PATH",
    "ProtectedGameDetected",
    "ProtectedGameEntry",
    "ProtectedGameExited",
    "ProtectedGamesCatalog",
]
