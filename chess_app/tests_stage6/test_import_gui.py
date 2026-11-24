"""Qt/C import transactions, plus inherited stage-5/4 regression tests."""
import tempfile
from pathlib import Path
from PySide6.QtWidgets import QFileDialog
from unittest.mock import patch
import tests_stage5.test_navigation as stage5
import tests_stage5.test_game_tree as tree_checks
from pgn_service import parse_pgn_text, export_pgn
from tests_stage6.test_pgn_referee import SAMPLE


class PgnGuiTests(stage5.NavigationTests):
    def import_text(self, text):
        self.controller.import_game(parse_pgn_text(text)[0])
        self.ready()

    def test_import_shows_game_and_all_variations(self):
        self.import_text(SAMPLE)
        tree = self.controller.tree
        self.assertEqual(len(tree), 8)
        self.assertEqual(len(self.window._node_items), 8)
        self.assertEqual(tree.current.node_id, 0)
        self.assertIn('Nidal', self.window.game_label.text())
        self.window.last_button.click()
        self.ready()
        self.assertEqual(self.controller.position, tree.mainline()[-1].position)

    def test_imported_comments_and_nags_displayed(self):
        self.import_text(SAMPLE)
        tree = self.controller.tree
        e4 = tree.root.children[0]
        e5, c5 = tree.node(e4).children
        self.go(c5)
        self.assertIn('Sicilian', self.window.comment_view.toPlainText())
        self.assertIn('$1', self.window._node_items[e5].text(0))

    def test_illegal_variation_restores_previous_game(self):
        self.make_original_line()
        previous = self.controller.tree
        node_id = previous.current.node_id
        fen = self.controller.position.fen
        self.import_text('1.e4 e5 (1... Bh6) 2.Nf3 *')
        self.assertIs(self.controller.tree, previous)
        self.assertEqual(previous.current.node_id, node_id)
        self.assertEqual(self.controller.position.fen, fen)
        self.assertIn('Bh6', self.window.error_label.text())
        self.assertTrue(self.controller.can_move)

    def test_invalid_start_restores_previous_game(self):
        self.play('e2e4')
        previous = self.controller.tree
        self.import_text('[SetUp "1"]\n[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n*')
        self.assertIs(self.controller.tree, previous)
        self.assertEqual(self.controller.position.pieces.get('e4'), 'P')

    def test_failed_import_restores_repetition_history(self):
        for uci in ('g1f3', 'g8f6', 'f3g1', 'f6g8') * 2:
            self.play(uci)
        previous = self.controller.tree
        self.import_text('1.e4 e5 2.Bh6 *')
        self.assertIs(self.controller.tree, previous)
        self.assertEqual(self.controller.game_status, 'threefold-repetition')

    def test_imported_variation_can_be_extended(self):
        self.import_text('1.e4 e5 (1... c5) *')
        tree = self.controller.tree
        e4 = tree.root.children[0]
        original, sicilian = tree.node(e4).children
        self.go(sicilian)
        self.play('g1f3')
        self.assertEqual(tree.node(e4).children, (original, sicilian))
        copy = parse_pgn_text(export_pgn(tree))[0]
        self.assertEqual(len(copy.nodes), 5)

    def test_extra_input_ignored_during_import(self):
        c = self.controller
        c.import_game(parse_pgn_text('1.e4 e5 2.Nf3 *')[0])
        c.on_square_clicked('d2')
        c.on_square_clicked('d4')
        c.first()
        self.ready()
        self.assertEqual(len(c.tree), 4)
        self.assertEqual(c.tree.current.node_id, 0)

    def test_close_during_import(self):
        self.controller.import_game(parse_pgn_text(SAMPLE)[0])
        self.window.close()
        stage5.stage4.wait_until(lambda: self.window._referee_stopped)
        self.assertEqual(self.controller.phase, 'closed')

    def test_successful_import_clears_old_error(self):
        self.import_text('1.e4 e5 2.Bh6 *')
        self.assertTrue(self.window.error_label.text())
        self.import_text('1.d4 d5 *')
        self.assertEqual(self.window.error_label.text(), '')

    def test_recorded_result_preserved_for_variation(self):
        self.import_text('[Result "1-0"]\n1.e4 e5 1-0')
        self.go(self.controller.tree.root.children[0])
        self.play('c7c5')
        self.assertEqual(self.controller.tree.headers['Result'], '1-0')

    def test_extending_mainline_resets_recorded_result(self):
        self.import_text('[Result "1-0"]\n1.e4 e5 1-0')
        self.window.last_button.click()
        self.ready()
        self.play('g1f3')
        self.assertEqual(self.controller.tree.headers['Result'], '*')

    def test_open_file_button_and_save_file_button(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.pgn'
            target = Path(directory) / 'output.pgn'
            source.write_text(SAMPLE, encoding='utf-8')
            with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(source), '')):
                self.window.open_pgn_button.click()
            self.ready()
            self.assertEqual(len(self.controller.tree), 8)
            with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
                self.window.save_pgn_button.click()
            self.assertTrue(target.is_file())
            self.assertEqual(parse_pgn_text(target.read_text(encoding='utf-8'))[0].headers['Event'], 'Opening study')


class TreeRegressionTests(tree_checks.GameTreeTests):
    pass


class StartupFailureTests(stage5.StartupFailureTests):
    pass
