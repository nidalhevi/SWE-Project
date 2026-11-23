"""Arrange the board, controller, promotion dialog, and referee lifecycle."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
from board_widget import BoardWidget
from controller import ChessController
from models import PositionSnapshot, STARTING_FEN
from referee_client import RefereeClient


class MainWindow(QMainWindow):
    def __init__(self, program, arguments=None, initial=None):
        super().__init__()
        self.setWindowTitle('Chess Analysis — Legal Moves')
        self.resize(760, 850)
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
        layout.addWidget(self.board, stretch=1)
        controls = QHBoxLayout()
        self.flip_button = QPushButton('Flip board')
        self.clear_button = QPushButton('Clear selection')
        self.undo_button = QPushButton('Undo')
        self.new_button = QPushButton('New game')
        self.fen_button = QPushButton('Load FEN')
        for button in (self.flip_button, self.clear_button, self.undo_button,
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
        self.controller.promotion_requested.connect(self._show_promotion)
        self.controller.problem.connect(self._show_problem)
        self.controller.closed.connect(self._on_referee_closed)
        self.flip_button.clicked.connect(self.board.flip)
        self.clear_button.clicked.connect(self.controller.clear_selection)
        self.undo_button.clicked.connect(self.controller.undo)
        self.new_button.clicked.connect(self.controller.new_game)
        self.fen_button.clicked.connect(self._load_fen)
        self._update_controls()
        QTimer.singleShot(0, self._start)

    def _start(self):
        if not self._closing:
            self.controller.start(self._program, self._arguments, self._initial)

    def _update_controls(self):
        self.board.set_interactive(self.controller.can_move)
        self.clear_button.setEnabled(self.controller.can_move)
        self.undo_button.setEnabled(self.controller.can_undo)
        self.new_button.setEnabled(self.controller.can_load)
        self.fen_button.setEnabled(self.controller.can_load)
        self.flip_button.setEnabled(not self._closing)

    def _load_fen(self):
        text, accepted = QInputDialog.getText(
            self, 'Load position', 'Complete FEN (loading clears undo history):',
            text=self.controller.position.fen,
        )
        if accepted:
            try:
                position = PositionSnapshot(text)
            except ValueError as error:
                QMessageBox.warning(self, 'Invalid FEN format', str(error))
                return
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
