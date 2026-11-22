"""English and Arabic translation catalog and Qt RTL direction switching."""

from PySide6.QtCore import QCoreApplication, QLocale, Qt, QTranslator
from PySide6.QtGui import QGuiApplication

from gamehub.core.i18n.catalog import AR_CATALOG

_ACTIVE_TRANSLATOR: "CatalogTranslator | None" = None


class CatalogTranslator(QTranslator):
    """In-memory Qt translator backed by a verified English-to-Arabic dictionary."""

    def __init__(self, mapping: dict[str, str]) -> None:
        super().__init__()
        self._mapping = mapping

    def translate(
        self,
        context: str,
        sourceText: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        return self._mapping.get(sourceText, "")


def ltr_isolate(text: str) -> str:
    """Wrap file paths, key chords, or mixed-script literals for RTL legibility."""
    return f"\u2066{text}\u2069"


def apply_language(app: QCoreApplication, language: str) -> None:
    """Install or remove the Arabic translator, locale, and layout direction."""
    global _ACTIVE_TRANSLATOR
    if _ACTIVE_TRANSLATOR is not None:
        app.removeTranslator(_ACTIVE_TRANSLATOR)
        _ACTIVE_TRANSLATOR = None

    if language == "ar":
        translator = CatalogTranslator(AR_CATALOG)
        app.installTranslator(translator)
        _ACTIVE_TRANSLATOR = translator
        direction = Qt.LayoutDirection.RightToLeft
        QLocale.setDefault(QLocale("ar"))
    else:
        direction = Qt.LayoutDirection.LeftToRight
        QLocale.setDefault(QLocale("en"))

    if isinstance(app, QGuiApplication):
        app.setLayoutDirection(direction)
