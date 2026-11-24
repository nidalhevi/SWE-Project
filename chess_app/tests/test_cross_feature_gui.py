"""Real GUI/controller/C tests, with deliberately ordered analysis responses."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QFileDialog, QMessageBox
from tests.gui_support import WindowCase, stage4
from tests_stage8.test_image_qt import image_file, FIXTURES
from models import PositionSnapshot, STARTING_FEN
from pgn_service import parse_pgn_text


class CoordinateAndSpecialMoveTests(WindowCase):
    def test_all_64_square_centers_and_boundaries_in_both_orientations(self):
        board = self.window.board
        for flipped in (False, True):
            if board._flipped != flipped:
                board.flip()
            left, top, size = board._board_geometry()
            for row in range(8):
                for column in range(8):
                    expected = ('hgfedcba'[column] + str(row + 1) if flipped
                                else 'abcdefgh'[column] + str(8 - row))
                    with self.subTest(flipped=flipped, square=expected):
                        point = QPointF(left + (column + .5) * size, top + (row + .5) * size)
                        self.assertEqual(board.square_at(point), expected)
            for x, y in [(left - .1, top), (left, top - .1),
                         (left + 8 * size, top), (left, top + 8 * size)]:
                self.assertIsNone(board.square_at(QPointF(x, y)))

    def test_flipped_castling_both_colors_and_directions_survives_navigation(self):
        self.window.board.flip()
        for turn, move, king, rook, origin, code in [
            ('w', 'e1g1', 'g1', 'f1', 'h1', 'K'), ('w', 'e1c1', 'c1', 'd1', 'a1', 'K'),
            ('b', 'e8g8', 'g8', 'f8', 'h8', 'k'), ('b', 'e8c8', 'c8', 'd8', 'a8', 'k'),
        ]:
            with self.subTest(move=move):
                self.load(f'r3k2r/8/8/8/8/8/8/R3K2R {turn} KQkq - 0 10')
                self.click(move[:2])
                self.assertIn(move[2:], self.window.board._legal_targets)
                self.click(move[2:])
                self.ready()
                accepted = self.controller.position.fen
                self.assertEqual(self.controller.position.pieces[king], code)
                self.assertEqual(self.controller.position.pieces[rook], 'R' if turn == 'w' else 'r')
                self.assertNotIn(origin, self.controller.position.pieces)
                self.controller.previous(); self.ready()
                self.controller.next(); self.ready()
                self.assertEqual(self.controller.position.fen, accepted)

    def test_imported_en_passant_replays_correctly_on_flipped_board(self):
        text = '[SetUp "1"]\n[FEN "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"]\n2.exd6 *'
        self.controller.import_game(parse_pgn_text(text)[0]); self.ready()
        self.window.board.flip()
        self.controller.last(); self.ready()
        accepted = self.controller.position.fen
        self.assertNotIn('d5', self.controller.position.pieces)
        self.controller.previous(); self.ready()
        self.click('e5')
        self.assertIn('d6', self.window.board._legal_targets)
        self.click('d6'); self.ready()
        self.assertEqual(self.controller.position.fen, accepted)
        self.assertEqual(len(self.controller.tree), 2)

    def test_imported_promotion_variations_keep_distinct_pieces_when_flipped(self):
        text = ('[SetUp "1"]\n[FEN "7k/P7/8/8/8/8/8/7K w - - 0 1"]\n'
                '1.a8=Q+ (1.a8=R+) (1.a8=B) (1.a8=N) *')
        self.controller.import_game(parse_pgn_text(text)[0]); self.ready()
        self.window.board.flip()
        tree = self.controller.tree
        self.assertEqual(len(tree.root.children), 4)
        for node_id in tree.root.children:
            self.controller.go_to(node_id); self.ready()
            piece = tree.current.move.promotion.upper()
            self.assertEqual(self.window.board._pieces['a8'], piece)
            self.assertNotIn('a7', self.window.board._pieces)


class ImportAndAnalysisTests(WindowCase):
    def test_malformed_pgn_file_preserves_game_selection_and_analysis(self):
        self.add_analysis()
        self.next_search(lambda: self.play('e2e4'))
        self.publish_current()
        tree, node_id, fen = self.controller.tree, self.controller.tree.current.node_id, self.controller.position.fen
        score = self.window.evaluation_label.text()
        count = len(self.engine.requests)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'malformed.pgn'
            path.write_text('1.e4 {unclosed comment', encoding='utf-8')
            with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
                self.window.open_pgn_button.click()
        self.assertIs(self.controller.tree, tree)
        self.assertEqual(self.controller.tree.current.node_id, node_id)
        self.assertEqual(self.controller.position.fen, fen)
        self.assertEqual(self.window.evaluation_label.text(), score)
        self.assertEqual(len(self.engine.requests), count)
        self.assertIn('PGN:', self.window.error_label.text())

    def test_rejected_pgn_clears_late_results_then_restores_analysis_history(self):
        self.add_analysis()
        self.next_search(lambda: self.play('e2e4'))
        old = self.publish_current()
        tree = self.controller.tree
        before = len(self.engine.requests)
        self.controller.import_game(parse_pgn_text('1.d4 d5 2.Bh5 *')[0])
        self.engine.publish(old, 'e7e5', 999)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: —')
        self.ready()
        stage4.wait_until(lambda: len(self.engine.requests) > before)
        current = self.engine.requests[-1]
        self.assertIs(self.controller.tree, tree)
        self.assertEqual([move.uci for move in current.moves], ['e2e4'])
        self.assertEqual(current.game_key, old.game_key)
        self.publish_current(cp=-21)
        self.engine.publish(old, 'e7e5', 999)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: -0.21')

    def test_navigation_rejects_old_result_while_referee_replays(self):
        self.add_analysis()
        self.next_search(lambda: self.play('e2e4'))
        old = self.publish_current()
        count = len(self.engine.requests)
        self.controller.previous()
        self.engine.publish(old, 'e7e5', 999)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: —')
        self.ready()
        stage4.wait_until(lambda: len(self.engine.requests) > count)
        self.publish_current(cp=18)
        self.engine.publish(old, 'e7e5', 999)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: +0.18')

    def test_identical_fen_transpositions_have_separate_requests_and_histories(self):
        self.controller.import_game(parse_pgn_text('1.Nf3 (1.Nc3 Nc6 2.Nf3 Nf6) Nf6 2.Nc3 Nc6 *')[0])
        self.ready()
        tree = self.controller.tree
        leaves = [node for node in tree.iter_nodes() if len(tree.path_to(node.node_id)) == 4]
        self.assertEqual(leaves[0].position.fen, leaves[1].position.fen)
        self.controller.go_to(leaves[0].node_id); self.ready()
        old = self.add_analysis()
        self.engine.publish(old, 'e2e4', 10)
        new = self.next_search(lambda: self.controller.go_to(leaves[1].node_id))
        self.assertNotEqual(old.request_id, new.request_id)
        self.assertNotEqual(old.moves, new.moves)
        self.engine.publish(new, 'e2e4', 23)
        self.engine.publish(old, 'e2e4', 999)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: +0.23')

    def test_same_fen_in_replacement_game_rejects_old_game_results(self):
        old = self.add_analysis()
        tree = self.controller.tree
        new = self.next_search(self.controller.new_game)
        self.assertIsNot(self.controller.tree, tree)
        self.assertEqual(old.position.fen, new.position.fen)
        self.assertNotEqual(old.game_key, new.game_key)
        self.engine.publish(new, 'e2e4', 29)
        self.engine.publish(old, 'e2e4', 999)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: +0.29')

    def test_illegal_suggestion_cannot_replace_accepted_evaluation(self):
        request = self.add_analysis()
        self.engine.publish(request, 'e2e4', 34)
        self.engine.publish(request, 'e2e5', 999, finish=False)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: +0.34')
        self.assertIn('does not match', self.window.engine_status.text())

    def test_accepted_image_starts_analysis_from_custom_root_without_old_moves(self):
        self.add_analysis()
        old = self.next_search(lambda: self.play('e2e4'))
        position = PositionSnapshot('7k/8/8/8/8/8/8/R6K b - - 19 42')
        count = len(self.engine.requests)
        with tempfile.TemporaryDirectory() as directory:
            self.window._open_image_path(image_file(directory))
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                self.window._confirm_image_position(position)
            self.ready()
            stage4.wait_until(lambda: len(self.engine.requests) > count)
        request = self.engine.requests[-1]
        self.assertEqual(request.root.fen, position.fen)
        self.assertEqual(request.position.fen, position.fen)
        self.assertEqual(request.moves, ())
        self.assertNotEqual(request.game_key, old.game_key)
        self.engine.publish(request, 'h8g8', -17)
        self.engine.publish(old, 'e7e5', 999)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: -0.17')

    def test_rejected_image_restores_analysis_for_original_line(self):
        self.add_analysis()
        old = self.next_search(lambda: self.play('e2e4'))
        tree = self.controller.tree
        count = len(self.engine.requests)
        with tempfile.TemporaryDirectory() as directory:
            self.window._open_image_path(image_file(directory))
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                self.window._confirm_image_position(PositionSnapshot('8/8/8/8/8/8/8/8 w - - 0 1'))
            self.engine.publish(old, 'e7e5', 999)
            self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: —')
            self.ready()
            stage4.wait_until(lambda: len(self.engine.requests) > count)
            self.assertIs(self.controller.tree, tree)
            self.assertEqual(self.engine.requests[-1].moves, old.moves)
            self.publish_current(cp=-9)
            self.engine.publish(old, 'e7e5', 999)
            self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: -0.09')
            self.window._image_dialog.reject()

    def test_editing_then_cancelling_image_does_not_publish_draft_to_analysis(self):
        old = self.add_analysis()
        tree = self.controller.tree
        count = len(self.engine.requests)
        with tempfile.TemporaryDirectory() as directory:
            self.window._open_image_path(image_file(directory))
            dialog = self.window._image_dialog
            dialog.draft.set_square('e1', 'q')
            self.engine.publish(old, 'e2e4', 34)
            self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: +0.34')
            dialog.reject()
        self.assertIs(self.controller.tree, tree)
        self.assertEqual(self.controller.position.fen, STARTING_FEN)
        self.assertEqual(len(self.engine.requests), count)

    def test_analysis_failure_still_allows_pgn_import_and_navigation(self):
        self.add_analysis()
        self.engine.error.emit('Injected engine failure')
        self.engine.close()
        self.controller.import_game(parse_pgn_text('1.e4 e5 (1...c5) *')[0]); self.ready()
        self.controller.last(); self.ready()
        self.assertEqual(self.controller.position.pieces.get('e5'), 'p')
        self.assertTrue(self.controller.can_move)
        self.assertIn('unavailable', self.window.engine_status.text())

    def test_close_waits_for_referee_engine_and_recognition_process(self):
        fixture = Path(__file__).resolve().parents[1] / 'tests_stage7/fake_uci.py'
        self.window._start_engine(sys.executable, [str(fixture)])
        stage4.wait_until(lambda: self.window.analysis._expected_id is not None)
        with tempfile.TemporaryDirectory() as directory:
            self.window._open_image_path(image_file(directory))
            dialog = self.window._image_dialog
            dialog.backend, dialog.vision_path = 'fixture_recognizer:slow', FIXTURES
            dialog.orientation.setCurrentIndex(1)
            dialog.recognize_button.click()
            self.window.close()
            stage4.wait_until(lambda: not self.window.isVisible())
        self.assertTrue(self.window._referee_stopped)
        self.assertTrue(self.window._engine_stopped)
        self.assertIsNone(self.window._image_dialog)
