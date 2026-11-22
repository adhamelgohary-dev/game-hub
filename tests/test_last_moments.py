import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from gamehub.ui.last_moments import LastMomentsDialog


@pytest.fixture(scope="module")
def app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Game Hub test"])


def test_carousel_displays_webp_and_skips_unavailable_image(app: QApplication, tmp_path: Path) -> None:
    screenshot = tmp_path / "shot.webp"
    image = QImage(64, 36, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(screenshot), "webp")
    corrupt = tmp_path / "corrupt.webp"
    corrupt.write_bytes(b"not a WebP file")
    missing = tmp_path / "missing.webp"
    requested = []

    def load_fixture(path: Path) -> bytes | None:
        requested.append(path)
        try:
            with path.open("rb") as file:
                return file.read(4096)
        except FileNotFoundError:
            return None

    dialog = LastMomentsDialog("<Game>", (screenshot, missing, corrupt, screenshot), load_image=load_fixture)
    dialog.show()
    app.processEvents()

    try:
        assert dialog.windowTitle() == "Last moments · <Game>"
        assert dialog._position.text() == "Screenshot 1 of 4"
        assert not dialog._previous.isEnabled()
        assert not dialog._preview.pixmap().isNull()
        QTest.keyClick(dialog, Qt.Key.Key_Right)
        assert dialog._position.text() == "Screenshot 2 of 4"
        assert dialog._preview.text() == "This screenshot is unavailable."
        dialog._next.click()
        assert dialog._position.text() == "Screenshot 3 of 4"
        assert dialog._preview.text() == "This screenshot is unavailable."
        dialog._next.click()
        assert not dialog._next.isEnabled()
        assert not dialog._preview.pixmap().isNull()
        QTest.keyClick(dialog, Qt.Key.Key_Right)
        assert dialog._position.text() == "Screenshot 4 of 4"
        QTest.keyClick(dialog, Qt.Key.Key_Left)
        assert dialog._position.text() == "Screenshot 3 of 4"
        assert requested == [screenshot, missing, corrupt, screenshot, corrupt]
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert not dialog.isVisible()
    finally:
        dialog.close()


def test_carousel_explains_empty_history(app: QApplication) -> None:
    dialog = LastMomentsDialog("Game", (), load_image=lambda _path: None)
    assert dialog._preview.text() == "No screenshots have been saved for this game."
    assert not dialog._previous.isEnabled()
    assert not dialog._next.isEnabled()
