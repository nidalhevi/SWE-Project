"""Qt + actual C integration checks; run from chess_app with unittest.

The referee must already be built. Tests use the offscreen Qt platform.
On Windows they default to WSL Ubuntu, matching main.py's launch defaults.
Override CHESS_BIN and CHESS_DISTRO environment variables if necessary.
"""
import os
from pathlib import Path
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from main import launch_command
from main_window import MainWindow
from models import PositionSnapshot, STARTING_FEN

APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


def wait_until(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Timed out waiting for the referee or GUI')
        QTest.qWait(10)


def command():
    binary = os.environ.get('CHESS_BIN')
    native_windows = bool(binary and binary.lower().endswith('.exe'))
    wsl = os.name == 'nt' and not native_windows
    if binary is None:
        binary = (Path(__file__).resolve().parents[2] / 'build/release/chess').as_posix()
        if wsl:
            binary = '/mnt/' + binary[0].lower() + binary[2:]
    return launch_command(binary, wsl, os.environ.get('CHESS_DISTRO', 'Ubuntu'))


class LegalMoveGuiTests(unittest.TestCase):
    def setUp(self):
        program, arguments = command()
        self.window = MainWindow(program, arguments)
        self.window.show()
        self.controller = self.window.controller
        self.ready()

    def tearDown(self):
        self.window.close()
        wait_until(lambda: self.window._referee_stopped)
        wait_until(lambda: not self.window.isVisible())
        self.window.deleteLater()
        APP.processEvents()

    def ready(self):
        wait_until(lambda: self.controller.phase in ('ready', 'failed', 'closed'))
        self.assertEqual(self.controller.phase, 'ready', self.window.error_label.text())

    def click(self, square):
        board = self.window.board
        left, top, size = board._board_geometry()
        for row in range(8):
            for column in range(8):
                if board._square_name(row, column) == square:
                    point = QPointF(left + (column + .5) * size,
                                    top + (row + .5) * size)
                    self.assertEqual(board.square_at(point), square)
                    QTest.mouseClick(board, Qt.MouseButton.LeftButton, pos=point.toPoint())
                    return
        self.fail('Square not found')

    def play(self, uci):
        self.click(uci[:2])
        self.click(uci[2:4])
        if len(uci) == 5:
            self.assertEqual(self.controller.phase, 'promotion')
            dialog = self.window._promotion_dialog
            button = dialog.findChild(QPushButton, 'promote_' + uci[4])
            self.assertIsNotNone(button)
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.ready()

    def load(self, fen):
        self.controller.load_position(PositionSnapshot(fen))
        self.ready()

    def test_selection_and_illegal_target(self):
        self.click('e7')
        self.assertIsNone(self.controller.selected_square)
        self.click('e2')
        self.assertEqual(self.window.board._legal_targets, {'e3', 'e4'})
        self.click('e5')
        self.assertEqual(self.controller.position.fen, STARTING_FEN)
        self.assertIsNone(self.controller.selected_square)

    def test_move_and_undo(self):
        self.play('e2e4')
        self.assertEqual(self.controller.position.pieces.get('e4'), 'P')
        self.assertNotIn('e2', self.controller.position.pieces)
        self.assertEqual(self.controller.position.turn, 'b')
        self.assertEqual(self.window.board._last_move.uci, 'e2e4')
        self.window.undo_button.click()
        self.ready()
        self.assertEqual(self.controller.position.fen, STARTING_FEN)
        self.assertIsNone(self.window.board._last_move)

    def test_pending_clicks_are_ignored(self):
        # Direct calls avoid QTest processing replies between the extra clicks.
        c = self.controller
        for square in ('e2', 'e4', 'e7', 'e5'):
            c.on_square_clicked(square)
        self.ready()
        self.assertEqual(c.position.turn, 'b')
        self.assertEqual(c.position.pieces.get('e7'), 'p')
        self.assertNotIn('e5', c.position.pieces)

    def test_flipped_coordinates_and_move(self):
        board = self.window.board
        left, top, size = board._board_geometry()
        corner = QPointF(left + size / 2, top + size / 2)
        self.assertEqual(board.square_at(corner), 'a8')
        board.flip()
        self.assertEqual(board.square_at(corner), 'h1')
        self.assertIsNone(board.square_at(QPointF(0, 0)))
        self.play('e2e4')
        self.assertEqual(self.controller.position.pieces.get('e4'), 'P')

    def test_both_castling_directions(self):
        fen = 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1'
        for uci, king, rook, origin in (
            ('e1g1', 'g1', 'f1', 'h1'), ('e1c1', 'c1', 'd1', 'a1'),
        ):
            with self.subTest(uci=uci):
                self.load(fen)
                self.play(uci)
                pieces = self.controller.position.pieces
                self.assertEqual(pieces.get(king), 'K')
                self.assertEqual(pieces.get(rook), 'R')
                self.assertNotIn(origin, pieces)
                self.window.undo_button.click()
                self.ready()
                self.assertEqual(self.controller.position.fen, fen)

    def test_en_passant_and_undo(self):
        fen = '4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2'
        self.load(fen)
        self.play('e5d6')
        pieces = self.controller.position.pieces
        self.assertEqual(pieces.get('d6'), 'P')
        self.assertNotIn('d5', pieces)
        self.assertNotIn('e5', pieces)
        self.window.undo_button.click()
        self.ready()
        self.assertEqual(self.controller.position.fen, fen)

    def test_all_promotion_dialog_choices(self):
        for piece in 'qrbn':
            with self.subTest(piece=piece):
                self.load('7k/P7/8/8/8/8/8/7K w - - 0 1')
                self.play('a7a8' + piece)
                self.assertEqual(self.controller.position.pieces.get('a8'), piece.upper())

    def test_cancel_promotion(self):
        fen = '7k/P7/8/8/8/8/8/7K w - - 0 1'
        self.load(fen)
        self.click('a7')
        self.click('a8')
        self.window._promotion_dialog.reject()
        self.assertEqual(self.controller.phase, 'ready')
        self.assertEqual(self.controller.position.fen, fen)

    def test_terminal_position_and_undo(self):
        for uci in ('f2f3', 'e7e5', 'g2g4', 'd8h4'):
            self.play(uci)
        self.assertEqual(self.controller.game_status, 'checkmate')
        self.assertFalse(self.controller.can_move)
        self.assertTrue(self.controller.can_undo)
        self.window.undo_button.click()
        self.ready()
        self.assertTrue(self.controller.can_move)

    def test_rejected_fen_preserves_position(self):
        self.play('e2e4')
        previous = self.controller.position.fen
        self.load('8/8/8/8/8/8/8/8 w - - 0 1')
        self.assertEqual(self.controller.position.fen, previous)
        self.assertTrue(self.controller.can_move)

    def test_close_during_pending_move(self):
        self.controller.on_square_clicked('e2')
        self.controller.on_square_clicked('e4')
        self.window.close()
        wait_until(lambda: self.window._referee_stopped)
        self.assertEqual(self.controller.phase, 'closed')


class StartupFailureTests(unittest.TestCase):
    def test_failed_start_can_close_window(self):
        window = MainWindow('/this-referee-does-not-exist', ['batch'])
        window.show()
        wait_until(lambda: window._referee_stopped)
        self.assertFalse(window.controller.can_move)
        self.assertTrue(window.error_label.text())
        window.close()
        self.assertFalse(window.isVisible())
        window.deleteLater()


if __name__ == '__main__':
    unittest.main()
