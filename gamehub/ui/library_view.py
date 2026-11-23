"""Cover-art card grid game library with search, filtering, and quick Play/Details actions."""

from collections.abc import Callable, Sequence
from html import escape

from PySide6.QtCore import QDateTime, QLocale, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gamehub.core.library.models import GameSource, GameSummary
from gamehub.ui.covers import load_cover_pixmap


class GameCard(QFrame):
    """Clickable game cover card with Play and Details actions."""

    clicked = Signal(str)
    selected = Signal(str)
    playRequested = Signal(str)
    detailsRequested = Signal(str)

    def __init__(
        self,
        game: GameSummary,
        *,
        source_label: str,
        last_played_label: str,
        playtime_label: str,
        strict_mode: bool,
        strict_text: str,
        full_text: str,
        play_text: str,
        details_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.game_id = game.id
        self.setObjectName("gameCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(game.name)
        self.setToolTip(f"<span>{escape(game.name)}</span>")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._cover = QLabel(self)
        self._cover.setFixedHeight(132)
        self._cover.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover.setScaledContents(True)
        self._cover.setPixmap(load_cover_pixmap(game.cover_path, game.name, 264, 132, radius=9))
        layout.addWidget(self._cover)

        meta_top = QHBoxLayout()
        meta_top.setSpacing(6)
        source = QLabel(source_label, self)
        source.setObjectName("mutedText")
        source.setTextFormat(Qt.TextFormat.PlainText)
        badge = QLabel(strict_text if strict_mode else full_text, self)
        badge.setObjectName("badgeStrict" if strict_mode else "badgeFull")
        badge.setTextFormat(Qt.TextFormat.PlainText)
        meta_top.addWidget(source)
        meta_top.addStretch()
        meta_top.addWidget(badge)
        layout.addLayout(meta_top)

        title = QLabel(game.name, self)
        title.setObjectName("cardTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)

        stats = QLabel(f"{last_played_label} · {playtime_label}", self)
        stats.setObjectName("mutedText")
        stats.setTextFormat(Qt.TextFormat.PlainText)
        stats.setWordWrap(True)
        layout.addWidget(stats)

        layout.addStretch()

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._play_btn = QPushButton(play_text, self)
        self._play_btn.setObjectName("primaryButton")
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.clicked.connect(self._on_play)
        self._details_btn = QPushButton(details_text, self)
        self._details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._details_btn.clicked.connect(self._on_details)
        actions.addWidget(self._play_btn, 1)
        actions.addWidget(self._details_btn, 1)
        layout.addLayout(actions)

    def set_selected(self, value: bool) -> None:
        self.setProperty("selected", value)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_busy(self, busy: bool) -> None:
        self._play_btn.setEnabled(not busy)
        self._details_btn.setEnabled(not busy)

    def _on_play(self) -> None:
        self.selected.emit(self.game_id)
        self.playRequested.emit(self.game_id)

    def _on_details(self) -> None:
        self.selected.emit(self.game_id)
        self.detailsRequested.emit(self.game_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.game_id)
            self.clicked.emit(self.game_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.selected.emit(self.game_id)
            self.clicked.emit(self.game_id)
            event.accept()
            return
        super().keyPressEvent(event)


class LibraryView(QWidget):
    refreshRequested = Signal()
    addRequested = Signal(str)
    assignRequested = Signal(str, str)
    lastMomentsRequested = Signal(str)
    playRequested = Signal(str)
    gameOpened = Signal(str)
    settingsRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._games: tuple[GameSummary, ...] = ()
        self._selected_id: str | None = None
        self._filter_mode = "all"
        self._cards: list[GameCard] = []
        self._columns = 3
        self._is_strict_game: Callable[[GameSummary], bool] = (
            lambda game: game.protection_mode == "strict"
        )

        # Header row
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self._title = QLabel(self.tr("Library"), self)
        self._title.setObjectName("pageTitle")
        self._subtitle = QLabel(self)
        self._subtitle.setObjectName("mutedText")
        title_box.addWidget(self._title)
        title_box.addWidget(self._subtitle)

        self._search = QLineEdit(self)
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(190)
        self._search.setMaximumWidth(260)
        self._search.textChanged.connect(self._rebuild_grid)

        self._refresh = QPushButton(self.tr("Refresh"), self)
        self._refresh.clicked.connect(self.refreshRequested)
        self._add = QPushButton(self.tr("Add game…"), self)
        self._add.setObjectName("primaryButton")
        self._add.clicked.connect(self._pick_game)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(self._search)
        header.addWidget(self._refresh)
        header.addWidget(self._add)

        # Filter chips row
        self._chip_all = QPushButton(self)
        self._chip_all.setObjectName("chipButton")
        self._chip_all.setCheckable(True)
        self._chip_all.setChecked(True)
        self._chip_all.clicked.connect(lambda: self._set_filter("all"))

        self._chip_full = QPushButton(self)
        self._chip_full.setObjectName("chipButton")
        self._chip_full.setCheckable(True)
        self._chip_full.clicked.connect(lambda: self._set_filter("full"))

        self._chip_strict = QPushButton(self)
        self._chip_strict.setObjectName("chipButton")
        self._chip_strict.setCheckable(True)
        self._chip_strict.clicked.connect(lambda: self._set_filter("strict"))

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(self._chip_all)
        filters.addWidget(self._chip_full)
        filters.addWidget(self._chip_strict)
        filters.addStretch()

        self._progress = QLabel(self.tr("Updating library…"), self)
        self._progress.setObjectName("mutedText")
        self._progress.hide()

        self._error = QLabel(self)
        self._error.setObjectName("libraryError")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()

        self._empty = QLabel(self.tr("No games in your library. Refresh or add a game."), self)
        self._empty.setObjectName("mutedText")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)

        self._grid_container = QWidget(self)
        self._grid_container.setObjectName("canvas")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 4, 8, 12)
        self._grid_layout.setHorizontalSpacing(16)
        self._grid_layout.setVerticalSpacing(16)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._grid_container)

        self._content = QStackedWidget(self)
        self._content.addWidget(self._empty)
        self._content.addWidget(self._scroll)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(filters)
        layout.addWidget(self._progress)
        layout.addWidget(self._error)
        layout.addWidget(self._content, stretch=1)
        self.retranslate_ui()

    def set_strict_resolver(self, resolver: Callable[[GameSummary], bool]) -> None:
        self._is_strict_game = resolver
        self._rebuild_grid()

    def retranslate_ui(self) -> None:
        self._title.setText(self.tr("Library"))
        self._search.setPlaceholderText(self.tr("Search games…"))
        self._refresh.setText(self.tr("Refresh"))
        self._add.setText(self.tr("Add game…"))
        self._progress.setText(self.tr("Updating library…"))
        self._rebuild_grid()

    def present_games(self, games: Sequence[GameSummary]) -> None:
        self._games = tuple(games)
        ids = {g.id for g in self._games}
        if self._selected_id not in ids:
            self._selected_id = None
        self._rebuild_grid()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._progress.setVisible(busy)
        self._refresh.setEnabled(not busy)
        self._add.setEnabled(not busy)
        for card in self._cards:
            card.set_busy(busy)

    def show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(bool(message))

    def clear_error(self) -> None:
        self.show_error("")

    def selected_game(self) -> str | None:
        return self._selected_id

    def select_game(self, game_id: str | None) -> None:
        self._selected_id = game_id
        for card in self._cards:
            card.set_selected(card.game_id == game_id)

    def cards(self) -> tuple[GameCard, ...]:
        return tuple(self._cards)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        avail = max(1, event.size().width() - 56)
        cols = max(1, min(4, (avail + 16) // 260))
        if cols != self._columns:
            self._columns = cols
            self._relayout_cards()

    def _set_filter(self, mode: str) -> None:
        self._filter_mode = mode
        self._chip_all.setChecked(mode == "all")
        self._chip_full.setChecked(mode == "full")
        self._chip_strict.setChecked(mode == "strict")
        self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        strict_count = sum(1 for g in self._games if self._is_strict_game(g))
        full_count = len(self._games) - strict_count
        self._chip_all.setText(self.tr("All ({count})").format(count=len(self._games)))
        self._chip_full.setText(self.tr("Full mode ({count})").format(count=full_count))
        self._chip_strict.setText(self.tr("Strict mode ({count})").format(count=strict_count))
        if self._games:
            self._subtitle.setText(
                self.tr("{count} games · Click any card for Details or press Play").format(
                    count=len(self._games)
                )
            )
        else:
            self._subtitle.setText(self.tr("Add a game or refresh to scan your local launchers."))

        query = self._search.text().strip().casefold()
        filtered: list[tuple[GameSummary, bool]] = []
        for game in self._games:
            is_strict = self._is_strict_game(game)
            if self._filter_mode == "strict" and not is_strict:
                continue
            if self._filter_mode == "full" and is_strict:
                continue
            if query and query not in game.name.casefold():
                continue
            filtered.append((game, is_strict))

        for card in self._cards:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        if not self._games:
            self._empty.setText(self.tr("No games in your library. Refresh or add a game."))
            self._content.setCurrentWidget(self._empty)
            return
        if not filtered:
            self._empty.setText(self.tr("No games match your current search or filter."))
            self._content.setCurrentWidget(self._empty)
            return

        locale = QLocale()
        sources = {
            GameSource.STEAM: self.tr("Steam"),
            GameSource.EPIC: self.tr("Epic Games"),
            GameSource.XBOX: self.tr("Xbox"),
            GameSource.MANUAL: self.tr("Manual"),
        }
        strict_text = self.tr("Strict")
        full_text = self.tr("Full")
        play_text = self.tr("Play")
        details_text = self.tr("Details")

        for game, is_strict in filtered:
            source = sources[game.source]
            if not game.installed:
                source = self.tr("{source} (not installed)").format(source=source)
            last_played = self.tr("Never")
            if game.last_played is not None:
                date = QDateTime.fromMSecsSinceEpoch(game.last_played).toLocalTime()
                last_played = locale.toString(date, QLocale.FormatType.ShortFormat)
            card = GameCard(
                game,
                source_label=source,
                last_played_label=last_played,
                playtime_label=self._format_playtime(game.total_playtime),
                strict_mode=is_strict,
                strict_text=strict_text,
                full_text=full_text,
                play_text=play_text,
                details_text=details_text,
                parent=self._grid_container,
            )
            card.set_selected(game.id == self._selected_id)
            card.set_busy(self._busy)
            card.selected.connect(self.select_game)
            card.clicked.connect(self._emit_open)
            card.detailsRequested.connect(self._emit_open)
            card.playRequested.connect(self._emit_play)
            self._cards.append(card)

        self._relayout_cards()
        self._content.setCurrentWidget(self._scroll)

    def _relayout_cards(self) -> None:
        while self._grid_layout.count():
            self._grid_layout.takeAt(0)
        cols = max(1, self._columns)
        for index, card in enumerate(self._cards):
            self._grid_layout.addWidget(card, index // cols, index % cols)
        for col in range(cols):
            self._grid_layout.setColumnStretch(col, 1)
        row_count = (len(self._cards) + cols - 1) // cols
        self._grid_layout.setRowStretch(row_count, 1)

    def _emit_open(self, game_id: str) -> None:
        if not self._busy:
            self.gameOpened.emit(game_id)

    def _emit_play(self, game_id: str) -> None:
        if not self._busy:
            self.playRequested.emit(game_id)

    def _format_playtime(self, seconds: int) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return self.tr("{hours} h {minutes} min").format(hours=hours, minutes=minutes)
        if minutes or not seconds:
            return self.tr("{minutes} min").format(minutes=minutes)
        return self.tr("{seconds} sec").format(seconds=seconds)

    def _pick_executable(self, title: str) -> str:
        path, _ = QFileDialog.getOpenFileName(self, title, "", self.tr("Windows executables (*.exe)"))
        return path

    def _pick_game(self) -> None:
        path = self._pick_executable(self.tr("Add game"))
        if path:
            self.addRequested.emit(path)
