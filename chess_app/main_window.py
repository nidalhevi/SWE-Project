"""Arrange PGN controls, move tree, board, and referee lifecycle."""
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QSplitter,
    QTreeWidget, QTreeWidgetItem, QFileDialog, QPlainTextEdit, QDialogButtonBox, QSpinBox,
)
from board_widget import BoardWidget
from controller import ChessController
from models import PositionSnapshot, STARTING_FEN
from referee_client import RefereeClient
from engine_client import EngineClient
from analysis_controller import AnalysisController
from engine_protocol import format_score
from pgn_service import PgnError, parse_pgn_text, read_pgn_file, write_pgn_file
from image_import import ImageImportError
from image_import_dialog import ImageImportDialog


class MainWindow(QMainWindow):
    def __init__(self, program, arguments=None, initial=None, *, engine_program=None, engine_arguments=None, analysis_ms=1000,
                 image_recognizer=None, vision_path=None):
        super().__init__()
        self.setWindowTitle('Chess Analysis — Stockfish')
        self.resize(1120, 850)
        self._program = program
        self._arguments = arguments
        self._initial = initial or PositionSnapshot(STARTING_FEN)
        self._closing = False
        self._referee_stopped = False
        self._promotion_dialog = None
        self.engine = None
        self.analysis = None
        self._engine_stopped = True
        self._engine_program = engine_program
        self._engine_arguments = engine_arguments
        self._image_recognizer = image_recognizer
        self._vision_path = vision_path
        self._image_dialog = None
        self._image_pending = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        instructions = QLabel('Select a piece, then click a highlighted destination.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        imports = QHBoxLayout()
        self.open_pgn_button = QPushButton('Open PGN')
        self.paste_pgn_button = QPushButton('Paste PGN')
        self.save_pgn_button = QPushButton('Save PGN')
        self.import_image_button = QPushButton('Import image')
        self.save_pgn_button.setToolTip('Save the current game and all its variations as one PGN game.')
        for button in (self.open_pgn_button, self.paste_pgn_button, self.save_pgn_button, self.import_image_button):
            imports.addWidget(button)
        imports.addStretch()
        layout.addLayout(imports)
        self.board = BoardWidget()
        self.board.set_position(self._initial)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.board)
        sidebar = QWidget()
        sidebar.setMinimumWidth(270)
        side_layout = QVBoxLayout(sidebar)
        self.moves_tree = QTreeWidget()
        self.moves_tree.setHeaderLabel('Moves and variations')
        self.moves_tree.setMinimumWidth(250)
        side_layout.addWidget(self.moves_tree, stretch=1)
        self.game_label = QLabel('')
        self.game_label.setWordWrap(True)
        side_layout.addWidget(self.game_label)
        self.comment_view = QPlainTextEdit()
        self.comment_view.setReadOnly(True)
        self.comment_view.setPlaceholderText('Comments and annotations for the selected move')
        self.comment_view.setMaximumHeight(130)
        side_layout.addWidget(self.comment_view)
        side_layout.addWidget(QLabel('Stockfish analysis — scores from White’s perspective'))
        engine_controls = QHBoxLayout()
        self.load_engine_button = QPushButton('Load Stockfish')
        self.analysis_toggle = QPushButton('Pause analysis')
        self.analysis_toggle.setCheckable(True)
        self.analysis_toggle.setChecked(True)
        self.analysis_toggle.setEnabled(False)
        engine_controls.addWidget(self.load_engine_button)
        engine_controls.addWidget(self.analysis_toggle)
        side_layout.addLayout(engine_controls)
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel('Time per position:'))
        self.analysis_time = QSpinBox()
        self.analysis_time.setRange(100, 10000)
        self.analysis_time.setSingleStep(500)
        self.analysis_time.setValue(analysis_ms)
        self.analysis_time.setSuffix(' ms')
        time_row.addWidget(self.analysis_time)
        side_layout.addLayout(time_row)
        self.evaluation_label = QLabel('Evaluation: —')
        self.depth_label = QLabel('Depth: —')
        self.best_move_label = QLabel('Best move: —')
        for label in (self.evaluation_label, self.depth_label, self.best_move_label):
            side_layout.addWidget(label)
        self.pv_view = QPlainTextEdit()
        self.pv_view.setReadOnly(True)
        self.pv_view.setPlaceholderText('Suggested continuation in UCI notation (e2e4, g1f3, …)')
        self.pv_view.setMaximumHeight(85)
        side_layout.addWidget(self.pv_view)
        self.engine_status = QLabel('Load a Stockfish executable to enable analysis.')
        self.engine_status.setWordWrap(True)
        side_layout.addWidget(self.engine_status)
        navigation = QHBoxLayout()
        self.first_button = QPushButton('First')
        self.previous_button = QPushButton('Previous')
        self.next_button = QPushButton('Next')
        self.last_button = QPushButton('Last')
        self.undo_button = self.previous_button  # Stage-4 compatibility.
        for button in (self.first_button, self.previous_button,
                       self.next_button, self.last_button):
            navigation.addWidget(button)
        side_layout.addLayout(navigation)
        hint = QLabel('Select a move to revisit it. Play a different move to add a variation. '
                      'Previous preserves the continuation; Next follows the last visited line.')
        hint.setWordWrap(True)
        side_layout.addWidget(hint)
        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, stretch=1)
        self._node_items = {}
        controls = QHBoxLayout()
        self.flip_button = QPushButton('Flip board')
        self.clear_button = QPushButton('Clear selection')
        self.new_button = QPushButton('New game')
        self.fen_button = QPushButton('Load FEN')
        for button in (self.flip_button, self.clear_button,
                       self.new_button, self.fen_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.status_label = QLabel('Starting referee…')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet('color: #D85B5B;')
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.referee = RefereeClient(self, timeout_ms=10000)
        self.controller = ChessController(self.referee, self)
        self.board.square_clicked.connect(self.controller.on_square_clicked)
        self.controller.position_changed.connect(self.board.set_position)
        self.controller.selection_changed.connect(self.board.set_selection)
        self.controller.last_move_changed.connect(self.board.set_last_move)
        self.controller.status_changed.connect(self.status_label.setText)
        self.controller.controls_changed.connect(self._update_controls)
        self.controller.tree_changed.connect(self._render_tree)
        self.controller.promotion_requested.connect(self._show_promotion)
        self.controller.problem.connect(self._show_problem)
        self.controller.closed.connect(self._on_referee_closed)
        self.controller.import_failed.connect(self._show_import_error)
        self.controller.import_succeeded.connect(self._clear_import_error)
        self.controller.import_failed.connect(self._image_import_failed)
        self.controller.import_succeeded.connect(self._image_import_succeeded)
        self.open_pgn_button.clicked.connect(self._open_pgn)
        self.paste_pgn_button.clicked.connect(self._paste_pgn)
        self.save_pgn_button.clicked.connect(self._save_pgn)
        self.import_image_button.clicked.connect(self._open_image)
        self.flip_button.clicked.connect(self.board.flip)
        self.clear_button.clicked.connect(self.controller.clear_selection)
        self.first_button.clicked.connect(self.controller.first)
        self.previous_button.clicked.connect(self.controller.previous)
        self.next_button.clicked.connect(self.controller.next)
        self.last_button.clicked.connect(self.controller.last)
        self.moves_tree.currentItemChanged.connect(self._on_node_selected)
        self.new_button.clicked.connect(self._new_game)
        self.fen_button.clicked.connect(self._load_fen)
        self.load_engine_button.clicked.connect(self._choose_engine)
        self.analysis_toggle.clicked.connect(self._toggle_analysis)
        self.analysis_time.valueChanged.connect(self._change_analysis_time)
        self._update_controls()
        QTimer.singleShot(0, self._start)

    def _start(self):
        if not self._closing:
            self.controller.start(self._program, self._arguments, self._initial)
            if self._engine_program is not None:
                self._start_engine(self._engine_program, self._engine_arguments)

    def _update_controls(self):
        self.board.set_interactive(self.controller.can_move)
        self.clear_button.setEnabled(self.controller.can_move)
        self.first_button.setEnabled(self.controller.can_previous)
        self.previous_button.setEnabled(self.controller.can_previous)
        self.next_button.setEnabled(self.controller.can_next)
        self.last_button.setEnabled(self.controller.can_next)
        self.moves_tree.setEnabled(self.controller.can_load)
        self.new_button.setEnabled(self.controller.can_load)
        self.fen_button.setEnabled(self.controller.can_load)
        self.flip_button.setEnabled(not self._closing)
        self.open_pgn_button.setEnabled(self.controller.can_load)
        self.paste_pgn_button.setEnabled(self.controller.can_load)
        self.save_pgn_button.setEnabled(self.controller.can_load)
        self.import_image_button.setEnabled(self.controller.can_load and self._image_dialog is None)

    def _choose_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose Stockfish executable', '', 'All files (*)')
        if path:
            self._start_engine(path, [])

    def _start_engine(self, program, arguments=None):
        # Engine instances start once. Restart the app to select another binary.
        if self.engine is not None or self._closing:
            return
        self._engine_stopped = False
        self.load_engine_button.setEnabled(False)
        self.engine = EngineClient(self)
        self.analysis = AnalysisController(self.controller, self.engine, self,
                                           movetime_ms=self.analysis_time.value())
        self.analysis.result_changed.connect(self._show_analysis)
        self.analysis.message_changed.connect(self.engine_status.setText)
        self.engine.ready.connect(self._analysis_ready)
        self.engine.error.connect(self._analysis_error)
        self.engine.closed.connect(self._on_engine_closed)
        self.engine_status.setText('Starting Stockfish…')
        self.engine.start(program, arguments)

    def _analysis_ready(self):
        if not self._closing:
            self.analysis_toggle.setEnabled(True)

    def _analysis_error(self, message):
        self.analysis_toggle.setEnabled(False)
        # The analysis controller reports the error separately from referee errors.

    def _toggle_analysis(self, checked):
        self.analysis_toggle.setText('Pause analysis' if checked else 'Resume analysis')
        if self.analysis is not None:
            self.analysis.set_enabled(checked)

    def _change_analysis_time(self, milliseconds):
        if self.analysis is not None:
            self.analysis.set_movetime(milliseconds)

    def _show_analysis(self, result):
        self.evaluation_label.setText('Evaluation: ' + format_score(result))
        self.depth_label.setText(f'Depth: {result.depth}' if result else 'Depth: —')
        best = result.best_move if result else None
        if best:
            promotion = '=' + best.promotion.upper() if best.promotion else ''
            self.best_move_label.setText(f'Best move: {best.from_square} → {best.to_square}{promotion}')
        else:
            self.best_move_label.setText('Best move: —')
        self.pv_view.setPlainText(' '.join(move.uci for move in result.principal_variation) if result else '')

    def _render_tree(self):
        tree = self.controller.tree
        if tree is None:
            return
        # Programmatic selection must not trigger a second navigation request.
        blocked = self.moves_tree.blockSignals(True)
        try:
            self.moves_tree.clear()
            self._node_items.clear()
            for node in tree.iter_nodes():
                parent = self.moves_tree if node.parent_id is None else self._node_items[node.parent_id]
                label = tree.label(node.node_id)
                if node.parent_id is not None:
                    siblings = tree.node(node.parent_id).children
                    if siblings.index(node.node_id) > 0:
                        label += ' (variation)'
                item = QTreeWidgetItem(parent, [label])
                item.setData(0, Qt.ItemDataRole.UserRole, node.node_id)
                annotation = tree.annotations(node.node_id)
                if annotation.nags:
                    item.setText(0, label + ' ' + ' '.join(f'${nag}' for nag in annotation.nags))
                item.setToolTip(0, annotation.comment or node.position.fen)
                self._node_items[node.node_id] = item
            self.moves_tree.expandAll()
            current = self._node_items[tree.current.node_id]
            self.moves_tree.setCurrentItem(current)
            self.moves_tree.scrollToItem(current)
            headers = tree.headers
            self.game_label.setText(
                f"{headers.get('White', '?')} — {headers.get('Black', '?')}\n"
                f"{headers.get('Event', 'Analysis')} | Result: {headers.get('Result', '*')}"
            )
            annotation = tree.annotations(tree.current.node_id)
            self.comment_view.setPlainText('\n'.join(
                text for text in (annotation.starting_comment, annotation.comment) if text
            ))
        finally:
            self.moves_tree.blockSignals(blocked)

    def _on_node_selected(self, item, previous):
        if item is not None and self.controller.can_load:
            self.controller.go_to(item.data(0, Qt.ItemDataRole.UserRole))

    def _confirm_new_tree(self):
        tree = self.controller.tree
        if tree is None or len(tree) == 1:
            return True
        answer = QMessageBox.question(
            self, 'Replace current game?',
            'This will replace the current game and all its variations. Continue?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _new_game(self):
        if self._confirm_new_tree():
            self._clear_import_error()
            self.controller.new_game()

    def _load_fen(self):
        text, accepted = QInputDialog.getText(
            self, 'Load position', 'Complete FEN (starts a new game tree):',
            text=self.controller.position.fen,
        )
        if accepted:
            try:
                position = PositionSnapshot(text)
            except ValueError as error:
                QMessageBox.warning(self, 'Invalid FEN format', str(error))
                return
            if self._confirm_new_tree():
                self._clear_import_error()
                self.controller.load_position(position)

    def _clear_import_error(self):
        self.error_label.clear()
        self.error_label.hide()

    def _show_import_error(self, message):
        self.error_label.setText(('Image: ' if self._image_pending else 'PGN: ') + message)
        self.error_label.show()

    def _open_image(self):
        if not self.controller.can_load or self._image_dialog is not None or self._closing:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Import board image', '',
                                             'Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)')
        if path:
            self._open_image_path(path)

    def _open_image_path(self, path):
        if not self.controller.can_load or self._image_dialog is not None or self._closing:
            return
        try:
            dialog = ImageImportDialog(path, self, backend=self._image_recognizer, vision_path=self._vision_path)
        except (ImageImportError, OSError) as error:
            self.error_label.setText('Image: ' + str(error))
            self.error_label.show()
            return
        self._image_dialog = dialog
        dialog.position_requested.connect(self._confirm_image_position)
        dialog.finished.connect(self._image_dialog_finished)
        self._update_controls()
        dialog.open()

    def _confirm_image_position(self, position):
        dialog = self._image_dialog
        if dialog is None or self._image_pending or self._closing:
            return
        if not self.controller.can_load:
            dialog.validation_failed('Wait for the current referee request to finish')
            return
        if not self._confirm_new_tree():
            return
        self._image_pending = True
        self._clear_import_error()
        dialog.begin_validation()
        try:
            self.controller.import_image_position(position)
        except ValueError as error:
            self._image_import_failed(str(error))

    def _image_import_failed(self, message):
        if self._image_pending and self._image_dialog is not None:
            self._image_pending = False
            self._image_dialog.validation_failed(message)

    def _image_import_succeeded(self):
        if self._image_pending and self._image_dialog is not None:
            self._image_pending = False
            self._image_dialog.validation_succeeded()

    def _image_dialog_finished(self, result):
        dialog = self._image_dialog
        self._image_dialog = None
        self._image_pending = False
        if dialog is not None:
            dialog.deleteLater()
        self._update_controls()
        if self._closing and self._referee_stopped and self._engine_stopped:
            QTimer.singleShot(0, self.close)

    def _choose_game(self, games):
        if len(games) == 1:
            return games[0]
        labels = [f'{index + 1}. {game.description}' for index, game in enumerate(games)]
        selected, accepted = QInputDialog.getItem(
            self, 'Select PGN game', 'The input contains multiple games:', labels, 0, False,
        )
        return games[labels.index(selected)] if accepted else None

    def _import_games(self, games):
        chosen = self._choose_game(games)
        if chosen is not None and self._confirm_new_tree():
            self._clear_import_error()
            self.controller.import_game(chosen)

    def _open_pgn(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open PGN', '', 'PGN files (*.pgn);;All files (*)')
        if not path:
            return
        try:
            try:
                games = read_pgn_file(path)
            except UnicodeDecodeError:
                answer = QMessageBox.question(
                    self, 'File encoding',
                    'This file is not UTF-8. Try reading it as Latin-1?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                games = read_pgn_file(path, encoding='latin-1')
            self._import_games(games)
        except (PgnError, OSError) as error:
            self._show_import_error(str(error))

    def _paste_pgn(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Paste PGN')
        dialog.resize(650, 430)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setPlaceholderText('1. e4 e5 2. Nf3 Nc6 *')
        layout.addWidget(editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self._import_games(parse_pgn_text(editor.toPlainText()))
            except PgnError as error:
                self._show_import_error(str(error))
        dialog.deleteLater()

    def _save_pgn(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save PGN', 'analysis.pgn', 'PGN files (*.pgn)')
        if not path:
            return
        if not path.lower().endswith('.pgn'):
            path += '.pgn'
            if Path(path).exists():
                answer = QMessageBox.question(
                    self, 'Replace PGN file?', f'{path} already exists. Replace it?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        try:
            write_pgn_file(path, self.controller.tree)
            self._clear_import_error()
            self.status_label.setText('Saved PGN with all variations')
        except (PgnError, OSError) as error:
            self._show_import_error(str(error))

    def _show_promotion(self, candidates):
        # open() is asynchronous, keeping process events on the normal loop.
        dialog = QDialog(self)
        dialog.setWindowTitle('Promote pawn')
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Choose the promoted piece:'))
        row = QHBoxLayout()
        names = {'q': 'Queen', 'r': 'Rook', 'b': 'Bishop', 'n': 'Knight'}
        choices = {move.promotion for move in candidates}
        choice = {'piece': None}

        def choose(piece):
            choice['piece'] = piece
            dialog.accept()

        for piece in ('q', 'r', 'b', 'n'):
            if piece in choices:
                button = QPushButton(names[piece])
                button.setObjectName('promote_' + piece)
                button.clicked.connect(lambda checked=False, p=piece: choose(p))
                row.addWidget(button)
        layout.addLayout(row)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(dialog.reject)
        layout.addWidget(cancel)

        def finished(result):
            self._promotion_dialog = None
            piece = choice['piece'] if result == QDialog.DialogCode.Accepted else None
            self.controller.choose_promotion(piece)
            dialog.deleteLater()

        dialog.finished.connect(finished)
        self._promotion_dialog = dialog
        dialog.open()

    def _show_problem(self, message):
        if self._promotion_dialog is not None:
            self._promotion_dialog.reject()
        self._render_tree()
        self.error_label.setText(message)
        self.error_label.show()

    def closeEvent(self, event):
        if self._referee_stopped and self._engine_stopped and self._image_dialog is None:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        if self._image_dialog is not None:
            self._image_dialog.force_close()
        if self.analysis is not None:
            self.analysis.dispose()
        if self.engine is not None:
            self.engine.close()
        self.controller.close()
        if self._promotion_dialog is not None:
            self._promotion_dialog.reject()

    def _on_referee_closed(self):
        self._referee_stopped = True
        if self._closing and self._engine_stopped and self._image_dialog is None:
            QTimer.singleShot(0, self.close)

    def _on_engine_closed(self):
        self._engine_stopped = True
        if self._closing and self._referee_stopped and self._image_dialog is None:
            QTimer.singleShot(0, self.close)
