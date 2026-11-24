"""Candidate review dialog for selecting games found inside a scanned folder."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gamehub.core.library.folder_scanner import FolderCandidate


class ScanFolderDialog(QDialog):
    """Review executable candidates found in a user-selected folder."""

    def __init__(
        self,
        folder: Path,
        candidates: Sequence[FolderCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._folder = folder
        self._candidates = tuple(candidates)
        self.setWindowTitle(self.tr("Review games in folder"))
        self.resize(680, 440)

        intro = QLabel(
            self.tr(
                "Tick the games you want to add from {folder}. Unticked items are remembered and skipped next time. You can rename any title directly in the table."
            ).format(folder=str(folder)),
            self,
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.PlainText)

        self._table = QTableWidget(len(self._candidates), 2, self)
        self._table.setHorizontalHeaderLabels(
            [self.tr("Game title"), self.tr("Executable")]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 240)

        for row, cand in enumerate(self._candidates):
            title_item = QTableWidgetItem(cand.suggested_name)
            title_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
            )
            checked = cand.previous_decision != "ignore"
            title_item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            title_item.setData(Qt.ItemDataRole.UserRole, str(cand.exe_path))

            try:
                rel_display = str(cand.exe_path.relative_to(folder))
            except ValueError:
                rel_display = str(cand.exe_path)
            path_item = QTableWidgetItem(rel_display)
            path_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            path_item.setToolTip(str(cand.exe_path))

            self._table.setItem(row, 0, title_item)
            self._table.setItem(row, 1, path_item)

        select_row = QHBoxLayout()
        select_all = QPushButton(self.tr("Select all"), self)
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        select_none = QPushButton(self.tr("Clear selection"), self)
        select_none.clicked.connect(lambda: self._set_all_checked(False))
        select_row.addWidget(select_all)
        select_row.addWidget(select_none)
        select_row.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(self.tr("Save selection"))
            ok_btn.setObjectName("primaryButton")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(self.tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addLayout(select_row)
        layout.addWidget(self._table, stretch=1)
        layout.addWidget(buttons)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None:
                item.setCheckState(state)

    def choices(self) -> list[tuple[Path, str, str | None]]:
        """Return (exe_path, decision, custom_name) for every candidate row."""
        result: list[tuple[Path, str, str | None]] = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is None:
                continue
            exe = Path(str(item.data(Qt.ItemDataRole.UserRole)))
            decision = "include" if item.checkState() == Qt.CheckState.Checked else "ignore"
            name = item.text().strip() or exe.stem
            result.append((exe, decision, name))
        return result
