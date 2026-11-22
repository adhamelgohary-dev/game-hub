"""Read-only game library and its discovery and executable actions."""

from collections.abc import Sequence
from html import escape

from PySide6.QtCore import QDateTime, QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gamehub.core.library.models import GameSource, GameSummary


class LibraryView(QWidget):
    refreshRequested = Signal()
    addRequested = Signal(str)
    assignRequested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._busy = False

        title = QLabel(self.tr("Library"), self)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)

        self._refresh = QPushButton(self.tr("&Refresh"), self)
        self._refresh.clicked.connect(self.refreshRequested)
        self._add = QPushButton(self.tr("&Add game…"), self)
        self._add.clicked.connect(self._pick_game)
        self._assign = QPushButton(self.tr("Assign &executable…"), self)
        self._assign.setToolTip(self.tr("Choose an executable to track for the selected game."))
        self._assign.clicked.connect(self._pick_tracking_target)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._refresh)
        toolbar.addWidget(self._add)
        toolbar.addWidget(self._assign)
        toolbar.addStretch()

        self._progress = QLabel(self.tr("Updating library…"), self)
        self._progress.hide()
        self._error = QLabel(self)
        self._error.setObjectName("libraryError")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()

        self._empty = QLabel(self.tr("No games in your library. Refresh or add a game."), self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._table = QTableWidget(0, 5, self)
        self._table.setAccessibleName(self.tr("Game library"))
        self._table.setHorizontalHeaderLabels([
            self.tr("Name"),
            self.tr("Source"),
            self.tr("Install path"),
            self.tr("Last played"),
            self.tr("Total playtime"),
        ])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.itemSelectionChanged.connect(self._update_actions)
        self._table.verticalHeader().hide()
        header = self._table.horizontalHeader()
        header.setSectionsClickable(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self._content = QStackedWidget(self)
        self._content.addWidget(self._empty)
        self._content.addWidget(self._table)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(toolbar)
        layout.addWidget(self._progress)
        layout.addWidget(self._error)
        layout.addWidget(self._content, stretch=1)
        QWidget.setTabOrder(self._add, self._table)
        QWidget.setTabOrder(self._table, self._assign)
        self._update_actions()

    def present_games(self, games: Sequence[GameSummary]) -> None:
        """Refresh the table while preserving selection if the game remains."""
        selected = self._selected_game()
        self._table.clearSelection()
        self._table.setRowCount(len(games))
        selected_row = None
        locale = QLocale()
        sources = {
            GameSource.STEAM: self.tr("Steam"),
            GameSource.EPIC: self.tr("Epic Games"),
            GameSource.XBOX: self.tr("Xbox"),
            GameSource.MANUAL: self.tr("Manual"),
        }
        for row, game in enumerate(games):
            source = sources[game.source]
            if not game.installed:
                source = self.tr("{source} (not installed)").format(source=source)
            elif not game.tracking:
                source = self.tr("{source} · Assign executable").format(source=source)
            last_played = self.tr("Never")
            if game.last_played is not None:
                date = QDateTime.fromMSecsSinceEpoch(game.last_played).toLocalTime()
                last_played = locale.toString(date, QLocale.FormatType.ShortFormat)
            values = (
                game.name,
                source,
                str(game.install_dir) if game.install_dir is not None else self.tr("Unavailable"),
                last_played,
                self._format_playtime(game.total_playtime),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(f"<span>{escape(value)}</span>")
                self._table.setItem(row, column, item)
            name_item = self._table.item(row, 0)
            name_item.setData(Qt.ItemDataRole.UserRole, game.id)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, game.source != GameSource.MANUAL)
            if game.id == selected:
                selected_row = row

        self._content.setCurrentWidget(self._table if games else self._empty)
        if selected_row is not None:
            self._table.selectRow(selected_row)
        self._update_actions()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._progress.setVisible(busy)
        self._update_actions()

    def show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(bool(message))

    def clear_error(self) -> None:
        self.show_error("")

    def _format_playtime(self, seconds: int) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return self.tr("{hours} h {minutes} min").format(hours=hours, minutes=minutes)
        if minutes or not seconds:
            return self.tr("{minutes} min").format(minutes=minutes)
        return self.tr("{seconds} sec").format(seconds=seconds)

    def _selected_game(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return rows[0].data(Qt.ItemDataRole.UserRole)

    def _update_actions(self) -> None:
        self._refresh.setEnabled(not self._busy)
        self._add.setEnabled(not self._busy)
        rows = self._table.selectionModel().selectedRows()
        self._assign.setEnabled(
            not self._busy and bool(rows and rows[0].data(Qt.ItemDataRole.UserRole + 1))
        )

    def _pick_executable(self, title: str) -> str:
        path, _ = QFileDialog.getOpenFileName(self, title, "", self.tr("Windows executables (*.exe)"))
        return path

    def _pick_game(self) -> None:
        path = self._pick_executable(self.tr("Add game"))
        if path:
            self.addRequested.emit(path)

    def _pick_tracking_target(self) -> None:
        game_id = self._selected_game()
        if game_id is None:
            return
        path = self._pick_executable(self.tr("Assign executable"))
        if path:
            self.assignRequested.emit(game_id, path)
