"""Arrange the board, controller, promotion dialog, and referee lifecycle."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget, QSplitter,
    QTreeWidget, QTreeWidgetItem,
)
from board_widget import BoardWidget
from controller import ChessController
from models import PositionSnapshot, STARTING_FEN
from referee_client import RefereeClient


class MainWindow(QMainWindow):
    def __init__(self, program, arguments=None, initial=None):
        super().__init__()
        self.setWindowTitle('Chess Analysis — Games and Variations')
        self.resize(1120, 850)
        self._program = program
        self._arguments = arguments
        self._initial = initial or PositionSnapshot(STARTING_FEN)
        self._closing = False
        self._referee_stopped = False
        self._promotion_dialog = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        instructions = QLabel('Select a piece, then click a highlighted destination.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
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
        self.flip_button.clicked.connect(self.board.flip)
        self.clear_button.clicked.connect(self.controller.clear_selection)
        self.first_button.clicked.connect(self.controller.first)
        self.previous_button.clicked.connect(self.controller.previous)
        self.next_button.clicked.connect(self.controller.next)
        self.last_button.clicked.connect(self.controller.last)
        self.moves_tree.currentItemChanged.connect(self._on_node_selected)
        self.new_button.clicked.connect(self._new_game)
        self.fen_button.clicked.connect(self._load_fen)
        self._update_controls()
        QTimer.singleShot(0, self._start)

    def _start(self):
        if not self._closing:
            self.controller.start(self._program, self._arguments, self._initial)

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
                item.setToolTip(0, node.position.fen)
                self._node_items[node.node_id] = item
            self.moves_tree.expandAll()
            current = self._node_items[tree.current.node_id]
            self.moves_tree.setCurrentItem(current)
            self.moves_tree.scrollToItem(current)
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
                self.controller.load_position(position)

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
        if self._referee_stopped:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self.controller.close()
        if self._promotion_dialog is not None:
            self._promotion_dialog.reject()

    def _on_referee_closed(self):
        self._referee_stopped = True
        if self._closing:
            QTimer.singleShot(0, self.close)
