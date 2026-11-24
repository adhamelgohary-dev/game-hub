"""Plain-language Translations & Mods UI (sidebar page + per-game tab)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gamehub.core.library.models import GameSummary
from gamehub.modules.mods.models import GameModsState, ModConflict, ModItem


def _is_arabic_ui() -> bool:
    return QLocale().language() == QLocale.Language.Arabic


def _item_display_name(item: ModItem) -> str:
    if _is_arabic_ui() and item.name_ar:
        return item.name_ar
    return item.name


class GameModsWidget(QWidget):
    """Per-game Translations & Mods panel used in both GamePage tab and sidebar ModsView."""

    importRequested = Signal(str, str)  # (game_id, zip_path)
    toggleRequested = Signal(str, str, bool)  # (game_id, item_id, enabled)
    removeRequested = Signal(str, str)  # (game_id, item_id)
    restoreOriginalRequested = Signal(str)  # (game_id,)
    conflictWinnerRequested = Signal(str, str, str, str)  # (game_id, item_a, item_b, winner_id)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state: GameModsState | None = None
        self._expanded_conflicts: set[tuple[str, str]] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        self._error = QLabel(self)
        self._error.setObjectName("errorBanner")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()
        root.addWidget(self._error)

        self._status_notice = QLabel(self)
        self._status_notice.setObjectName("badgeStrict")
        self._status_notice.setTextFormat(Qt.TextFormat.PlainText)
        self._status_notice.setWordWrap(True)
        self._status_notice.hide()
        root.addWidget(self._status_notice)

        # Protected-game friendly lock card (zero actionable controls)
        self._lock_card = QFrame(self)
        self._lock_card.setObjectName("panelCard")
        lock_layout = QVBoxLayout(self._lock_card)
        lock_layout.setContentsMargins(32, 36, 32, 36)
        lock_layout.setSpacing(12)
        lock_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lock_icon = QLabel("🔒", self._lock_card)
        self._lock_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lock_icon.setStyleSheet("font-size: 32px;")
        self._lock_title = QLabel(self._lock_card)
        self._lock_title.setObjectName("pageTitle")
        self._lock_title.setTextFormat(Qt.TextFormat.PlainText)
        self._lock_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lock_message = QLabel(self._lock_card)
        self._lock_message.setObjectName("mutedText")
        self._lock_message.setTextFormat(Qt.TextFormat.PlainText)
        self._lock_message.setWordWrap(True)
        self._lock_message.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lock_layout.addWidget(self._lock_icon)
        lock_layout.addWidget(self._lock_title)
        lock_layout.addWidget(self._lock_message)
        self._lock_card.hide()
        root.addWidget(self._lock_card)

        # Normal single-player content container
        self._normal_box = QWidget(self)
        normal_layout = QVBoxLayout(self._normal_box)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        header_col = QVBoxLayout()
        header_col.setSpacing(6)
        self._game_heading = QLabel(self._normal_box)
        self._game_heading.setObjectName("sectionHeading")
        self._game_heading.setTextFormat(Qt.TextFormat.PlainText)
        self._backup_status = QLabel(self._normal_box)
        self._backup_status.setObjectName("badgeStrict")
        self._backup_status.setTextFormat(Qt.TextFormat.PlainText)
        header_col.addWidget(self._game_heading)
        header_col.addWidget(self._backup_status, alignment=Qt.AlignmentFlag.AlignLeft)
        top_row.addLayout(header_col, stretch=1)

        self._import_btn = QPushButton(self._normal_box)
        self._import_btn.setObjectName("primaryButton")
        self._import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._import_btn.clicked.connect(self._choose_zip)
        top_row.addWidget(self._import_btn, alignment=Qt.AlignmentFlag.AlignTop)
        normal_layout.addLayout(top_row)

        self._no_folder_note = QLabel(self._normal_box)
        self._no_folder_note.setObjectName("mutedText")
        self._no_folder_note.setTextFormat(Qt.TextFormat.PlainText)
        self._no_folder_note.setWordWrap(True)
        self._no_folder_note.hide()
        normal_layout.addWidget(self._no_folder_note)

        # Plain-language conflict container
        self._conflicts_container = QWidget(self._normal_box)
        self._conflicts_layout = QVBoxLayout(self._conflicts_container)
        self._conflicts_layout.setContentsMargins(0, 0, 0, 0)
        self._conflicts_layout.setSpacing(10)
        self._conflicts_container.hide()
        normal_layout.addWidget(self._conflicts_container)

        # Scrollable list of installed translations & mods
        self._items_scroll = QScrollArea(self._normal_box)
        self._items_scroll.setWidgetResizable(True)
        self._items_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._items_body = QWidget(self._items_scroll)
        self._items_layout = QVBoxLayout(self._items_body)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(10)
        self._items_scroll.setWidget(self._items_body)
        normal_layout.addWidget(self._items_scroll, stretch=1)

        # Big clear restore button
        footer_row = QHBoxLayout()
        self._restore_btn = QPushButton(self._normal_box)
        self._restore_btn.setObjectName("restoreButton")
        self._restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restore_btn.clicked.connect(self._confirm_restore)
        footer_row.addWidget(self._restore_btn)
        footer_row.addStretch()
        normal_layout.addLayout(footer_row)

        root.addWidget(self._normal_box, stretch=1)

        # Empty placeholder when no game is selected
        self._empty_selection = QLabel(self)
        self._empty_selection.setObjectName("mutedText")
        self._empty_selection.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_selection.setWordWrap(True)
        root.addWidget(self._empty_selection, stretch=1)

        self._normal_box.hide()
        self.retranslate_ui()

    @property
    def game_id(self) -> str | None:
        return self._state.game_id if self._state is not None else None

    def show_error(self, message: str) -> None:
        self._status_notice.hide()
        self._error.setText(message)
        self._error.show()

    def show_notice(self, message: str) -> None:
        self._error.hide()
        self._status_notice.setText(message)
        self._status_notice.show()

    def clear_messages(self) -> None:
        self._error.hide()
        self._status_notice.hide()

    def clear_selection(self) -> None:
        self._state = None
        self.clear_messages()
        self._lock_card.hide()
        self._normal_box.hide()
        self._empty_selection.show()

    def present_state(self, state: GameModsState) -> None:
        self._state = state
        self._empty_selection.hide()
        if state.protected:
            self._import_btn.setEnabled(False)
            self._restore_btn.setEnabled(False)
            self._clear_layout(self._conflicts_layout)
            self._clear_layout(self._items_layout)
            self._normal_box.hide()
            self._lock_card.show()
            return

        self._lock_card.hide()
        self._normal_box.show()
        self._game_heading.setText(state.game_name)
        if state.backed_up_count > 0:
            self._backup_status.setText(self.tr("Original game files are backed up ✓"))
        else:
            self._backup_status.setText(self.tr("Original game files are untouched ✓"))

        can_modify = state.install_dir_available
        self._import_btn.setEnabled(can_modify)
        self._restore_btn.setEnabled(can_modify and (state.has_mod_changes or state.backed_up_count > 0))
        self._no_folder_note.setVisible(not can_modify)
        self._rebuild_conflicts(state.conflicts)
        self._rebuild_items(state.items, can_modify=can_modify)

    def retranslate_ui(self) -> None:
        self._lock_title.setText(self.tr("Protected online game"))
        self._lock_message.setText(
            self.tr("Mods and translations are turned off for online games to protect your account.")
        )
        self._import_btn.setText(self.tr("Import translation or mod (.zip)"))
        self._restore_btn.setText(self.tr("Restore the original game"))
        self._no_folder_note.setText(
            self.tr("This game does not have an accessible local install folder yet.")
        )
        self._empty_selection.setText(
            self.tr("Select a game to manage its translations and mods.")
        )
        if self._state is not None:
            self.present_state(self._state)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_conflicts(self, conflicts: Sequence[ModConflict]) -> None:
        self._clear_layout(self._conflicts_layout)
        if not conflicts:
            self._conflicts_container.hide()
            return
        self._conflicts_container.show()
        for conflict in conflicts:
            card = QFrame(self._conflicts_container)
            card.setObjectName("conflictCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 12, 14, 12)
            layout.setSpacing(10)

            name_a = _item_display_name(conflict.item_a)
            name_b = _item_display_name(conflict.item_b)
            if conflict.item_a.kind == "translation" and conflict.item_b.kind == "mod":
                prompt = self.tr(
                    "This translation and this mod change the same file. Which one should win?"
                )
            else:
                prompt = self.tr(
                    "Two enabled items change the same file. Which one should win?"
                )
            title = QLabel(prompt, card)
            title.setObjectName("cardTitle")
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            layout.addWidget(title)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(8)
            btn_a = QPushButton(
                (self.tr("Use {name} ✓") if conflict.winner_item_id == conflict.item_a.id else self.tr("Use {name}")).format(
                    name=name_a
                ),
                card,
            )
            btn_b = QPushButton(
                (self.tr("Use {name} ✓") if conflict.winner_item_id == conflict.item_b.id else self.tr("Use {name}")).format(
                    name=name_b
                ),
                card,
            )
            if conflict.winner_item_id == conflict.item_a.id:
                btn_a.setObjectName("primaryButton")
            if conflict.winner_item_id == conflict.item_b.id:
                btn_b.setObjectName("primaryButton")
            btn_a.clicked.connect(
                lambda _checked=False, c=conflict: self._emit_winner(c, c.item_a.id)
            )
            btn_b.clicked.connect(
                lambda _checked=False, c=conflict: self._emit_winner(c, c.item_b.id)
            )

            pair_key = (conflict.item_a.id, conflict.item_b.id)
            details_btn = QPushButton(self.tr("Details"), card)
            details_btn.setCursor(Qt.CursorShape.PointingHandCursor)

            btn_row.addWidget(btn_a)
            btn_row.addWidget(btn_b)
            btn_row.addStretch()
            btn_row.addWidget(details_btn)
            layout.addLayout(btn_row)

            details_lbl = QLabel("\n".join(conflict.rel_paths), card)
            details_lbl.setObjectName("mutedText")
            details_lbl.setTextFormat(Qt.TextFormat.PlainText)
            details_lbl.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            details_lbl.setWordWrap(True)
            details_lbl.setVisible(pair_key in self._expanded_conflicts)
            layout.addWidget(details_lbl)

            def _toggle_details(_checked: bool = False, key=pair_key, lbl=details_lbl) -> None:
                if key in self._expanded_conflicts:
                    self._expanded_conflicts.discard(key)
                    lbl.hide()
                else:
                    self._expanded_conflicts.add(key)
                    lbl.show()

            details_btn.clicked.connect(_toggle_details)
            self._conflicts_layout.addWidget(card)

    def _rebuild_items(self, items: Sequence[ModItem], *, can_modify: bool) -> None:
        self._clear_layout(self._items_layout)
        if not items:
            empty = QLabel(
                self.tr(
                    "No translations or mods installed for this game yet. Click 'Import translation or mod (.zip)' to add one."
                ),
                self._items_body,
            )
            empty.setObjectName("mutedText")
            empty.setTextFormat(Qt.TextFormat.PlainText)
            empty.setWordWrap(True)
            self._items_layout.addWidget(empty)
            self._items_layout.addStretch()
            return

        for item in items:
            row = QFrame(self._items_body)
            row.setObjectName("panelCard")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(16, 12, 16, 12)
            row_layout.setSpacing(12)

            info = QVBoxLayout()
            info.setSpacing(4)
            title_row = QHBoxLayout()
            title_row.setSpacing(8)
            name_lbl = QLabel(_item_display_name(item), row)
            name_lbl.setObjectName("cardTitle")
            name_lbl.setTextFormat(Qt.TextFormat.PlainText)
            kind_lbl = QLabel(
                self.tr("Translation") if item.kind == "translation" else self.tr("Mod"), row
            )
            kind_lbl.setObjectName("badgeStrict" if item.kind == "translation" else "badgeFull")
            title_row.addWidget(name_lbl)
            title_row.addWidget(kind_lbl)
            title_row.addStretch()

            status_word = self.tr("On") if item.enabled else self.tr("Off")
            sub = QLabel(
                self.tr("{status} · Version {version}").format(
                    status=status_word, version=item.version
                ),
                row,
            )
            sub.setObjectName("mutedText")
            sub.setTextFormat(Qt.TextFormat.PlainText)
            info.addLayout(title_row)
            info.addWidget(sub)
            row_layout.addLayout(info, stretch=1)

            toggle_btn = QPushButton(self.tr("On") if item.enabled else self.tr("Off"), row)
            toggle_btn.setCheckable(True)
            toggle_btn.setChecked(item.enabled)
            toggle_btn.setObjectName("primaryButton" if item.enabled else "chipButton")
            toggle_btn.setMinimumWidth(68)
            toggle_btn.setEnabled(can_modify)
            toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle_btn.toggled.connect(
                lambda checked, iid=item.id: self._emit_toggle(iid, checked)
            )

            remove_btn = QPushButton(self.tr("Remove"), row)
            remove_btn.setEnabled(can_modify)
            remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_btn.clicked.connect(lambda _checked=False, it=item: self._confirm_remove(it))

            row_layout.addWidget(toggle_btn)
            row_layout.addWidget(remove_btn)
            self._items_layout.addWidget(row)

        self._items_layout.addStretch()

    def _choose_zip(self) -> None:
        if self._state is None:
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import translation or mod (.zip)"),
            "",
            self.tr("Mod or translation packs (*.zip)"),
        )
        if selected:
            self.importRequested.emit(self._state.game_id, selected)

    def _emit_toggle(self, item_id: str, enabled: bool) -> None:
        if self._state is not None:
            self.toggleRequested.emit(self._state.game_id, item_id, enabled)

    def _emit_winner(self, conflict: ModConflict, winner_id: str) -> None:
        if self._state is not None:
            self.conflictWinnerRequested.emit(
                self._state.game_id, conflict.item_a.id, conflict.item_b.id, winner_id
            )

    def _confirm_remove(self, item: ModItem) -> None:
        if self._state is None:
            return
        answer = QMessageBox.question(
            self,
            self.tr("Remove"),
            self.tr("Remove {name} and restore any files it changed?").format(
                name=_item_display_name(item)
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.removeRequested.emit(self._state.game_id, item.id)

    def _confirm_restore(self) -> None:
        if self._state is None:
            return
        answer = QMessageBox.question(
            self,
            self.tr("Restore the original game"),
            self.tr(
                "Turn off all translations and mods and restore the original game files?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.restoreOriginalRequested.emit(self._state.game_id)


class ModsView(QWidget):
    """Global sidebar page for Translations & Mods with game search and per-game panel."""

    gameSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._games: list[tuple[GameSummary, bool]] = []
        self._selected_game_id: str | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left column: title + search box + games list
        left = QFrame(self)
        left.setObjectName("sidebar")
        left.setFixedWidth(260)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 18, 14, 14)
        left_layout.setSpacing(10)

        self._heading = QLabel(left)
        self._heading.setObjectName("sectionHeading")
        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        left_layout.addWidget(self._heading)

        self._search = QLineEdit(left)
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._rebuild_game_list)
        left_layout.addWidget(self._search)

        self._games_scroll = QScrollArea(left)
        self._games_scroll.setWidgetResizable(True)
        self._games_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._games_body = QWidget(self._games_scroll)
        self._games_layout = QVBoxLayout(self._games_body)
        self._games_layout.setContentsMargins(0, 0, 0, 0)
        self._games_layout.setSpacing(6)
        self._games_scroll.setWidget(self._games_body)
        left_layout.addWidget(self._games_scroll, stretch=1)

        self.panel = GameModsWidget(self)

        root.addWidget(left)
        root.addWidget(self.panel, stretch=1)
        self.retranslate_ui()

    @property
    def selected_game_id(self) -> str | None:
        return self._selected_game_id

    def set_games(self, games: Sequence[tuple[GameSummary, bool]]) -> None:
        self._games = list(games)
        if self._selected_game_id is not None and not any(
            g.id == self._selected_game_id for g, _ in self._games
        ):
            self._selected_game_id = None
        if self._selected_game_id is None and self._games:
            # Prefer selecting the first non-protected game by default
            first_open = next((g.id for g, prot in self._games if not prot), self._games[0][0].id)
            self._selected_game_id = first_open
        self._rebuild_game_list()

    def select_game(self, game_id: str) -> None:
        self._selected_game_id = game_id
        self._rebuild_game_list()
        self.gameSelected.emit(game_id)

    def _rebuild_game_list(self) -> None:
        while self._games_layout.count():
            child = self._games_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

        query = self._search.text().strip().casefold()
        shown = [
            (game, protected)
            for game, protected in self._games
            if not query or query in game.name.casefold()
        ]
        if not shown:
            empty = QLabel(self.tr("No games match your search."), self._games_body)
            empty.setObjectName("mutedText")
            empty.setWordWrap(True)
            self._games_layout.addWidget(empty)
            self._games_layout.addStretch()
            return

        for game, protected in shown:
            suffix = f" ({self.tr('Online')})" if protected else ""
            btn = QPushButton(f"{game.name}{suffix}".replace("&", "&&"), self._games_body)
            btn.setObjectName("navButton")
            btn.setProperty("active", game.id == self._selected_game_id)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, gid=game.id: self.select_game(gid))
            self._games_layout.addWidget(btn)
        self._games_layout.addStretch()

    def retranslate_ui(self) -> None:
        self._heading.setText(self.tr("Translations & Mods"))
        self._search.setPlaceholderText(self.tr("Search games…"))
        self._rebuild_game_list()
        self.panel.retranslate_ui()
