"""Real Qt/referee chapter navigation, document saving and analysis isolation."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox
from notation import NotationLine
from pgn_service import parse_pgn_text
from tests.gui_support import WindowCase, stage4

STUDY = '''[Event "Chapter A"]
[Result "*"]

1. e4 {King pawn} e5 (1... c5 {Sicilian}) 2. Nf3 *

[Event "Chapter B"]
[Result "*"]

1. d4 d5 2. c4 *

[Event "Black to move"]
[SetUp "1"]
[FEN "4k3/8/8/8/8/8/8/4K3 b - - 0 12"]
[Result "*"]

12... Kf7 *
'''


class ChapterGuiTests(WindowCase):
    def open_study(self, text=STUDY):
        self.controller.open_study(parse_pgn_text(text))
        self.ready()

    def switch(self, index):
        self.window._chapter_selected(index)
        self.ready()

    def test_open_pgn_retains_all_games_and_loads_first(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chapters.pgn'
            path.write_text(STUDY, encoding='utf-8')
            with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
                self.window.open_pgn_button.click()
            self.ready()
        self.assertEqual(self.window.chapter_selector.count(), 3)
        self.assertEqual(self.controller.tree.headers['Event'], 'Chapter A')
        self.assertEqual(self.window.chapter_counter.text(), 'Chapter 1 of 3')
        self.assertIsNone(self.controller.study.chapters[1].tree)

    def test_buttons_and_selector_remember_each_selected_move(self):
        self.open_study()
        self.window.last_button.click(); self.ready()
        first, node = self.controller.tree, self.controller.tree.current.node_id
        self.window.next_chapter_button.click(); self.ready()
        self.window.next_button.click(); self.ready()
        second, second_node = self.controller.tree, self.controller.tree.current.node_id
        self.window.previous_chapter_button.click(); self.ready()
        self.assertIs(self.controller.tree, first)
        self.assertEqual(first.current.node_id, node)
        self.switch(1)
        self.assertIs(self.controller.tree, second)
        self.assertEqual(second.current.node_id, second_node)
        self.assertEqual(self.window.chapter_selector.currentIndex(), 1)

    def test_variation_and_comment_edits_survive_switching(self):
        self.open_study()
        first = self.controller.tree
        first.annotate(0, comment='My chapter notes')
        self.play('d2d4')
        alternative = first.current.node_id
        self.switch(1); self.switch(0)
        self.assertIs(self.controller.tree, first)
        self.assertEqual(first.current.node_id, alternative)
        self.assertEqual(first.annotations(0).comment, 'My chapter notes')
        self.assertEqual(len(first.root.children), 2)

    def test_navigation_boundaries_and_single_game(self):
        self.open_study('1.e4 *')
        self.assertFalse(self.window.previous_chapter_button.isEnabled())
        self.assertFalse(self.window.next_chapter_button.isEnabled())
        self.assertFalse(self.controller.select_chapter('unknown-chapter'))
        self.assertEqual(self.controller.study.active_index, 0)

    def test_custom_fen_black_move_numbers(self):
        self.open_study(); self.switch(2)
        self.assertEqual(self.controller.position.turn, 'b')
        self.window.last_button.click(); self.ready()
        self.assertTrue(self.controller.tree.label(self.controller.tree.current.node_id).startswith('12...'))

    def test_illegal_chapter_restores_previous_document_and_history(self):
        self.open_study('[Event "A"]\n*\n[Event "Bad"]\n1.e4 e5 2.Bh6 *')
        for uci in ('g1f3', 'g8f6', 'f3g1', 'f6g8') * 2:
            self.play(uci)
        study, tree = self.controller.study, self.controller.tree
        self.switch(1)
        self.assertIs(self.controller.study, study)
        self.assertIs(self.controller.tree, tree)
        self.assertEqual(self.controller.game_status, 'threefold-repetition')
        self.assertEqual(self.window.chapter_selector.currentIndex(), 0)
        self.assertIn('Bh6', self.window.error_label.text())

    def test_extra_chapter_and_board_requests_are_ignored_while_busy(self):
        self.open_study()
        self.controller.next_chapter()
        self.assertFalse(self.controller.can_load)
        self.assertFalse(self.window.chapter_selector.isEnabled())
        self.controller.next_chapter()
        self.controller.on_square_clicked('e2')
        self.ready()
        self.assertEqual(self.controller.study.active_index, 1)
        self.assertEqual(self.controller.tree.current.node_id, 0)

    def test_save_all_includes_unopened_chapters_and_restores_selection(self):
        self.open_study()
        self.window.last_button.click(); self.ready()
        tree, node, fen = self.controller.tree, self.controller.tree.current.node_id, self.controller.position.fen
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'all.pgn'
            with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
                self.window.save_study_button.click()
            self.ready()
            self.assertTrue(target.exists())
            games = parse_pgn_text(target.read_text(encoding='utf-8'))
        self.assertEqual([g.headers['Event'] for g in games], ['Chapter A', 'Chapter B', 'Black to move'])
        self.assertIs(self.controller.tree, tree)
        self.assertEqual(tree.current.node_id, node)
        self.assertEqual(self.controller.position.fen, fen)
        self.assertTrue(all(c.tree is not None for c in self.controller.study.chapters))

    def test_failed_save_all_does_not_overwrite_file(self):
        self.open_study('[Event "A"]\n1.e4 *\n[Event "Bad"]\n1.e4 e5 2.Bh6 *')
        tree = self.controller.tree
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'keep.pgn'; target.write_text('original', encoding='utf-8')
            with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
                self.window.save_study_button.click()
            self.ready()
            self.assertEqual(target.read_text(), 'original')
        self.assertIs(self.controller.tree, tree)
        self.assertIn('Chapter 2', self.window.error_label.text())

    def test_stale_analysis_and_notation_cannot_replace_current_chapter(self):
        self.open_study()
        old = self.add_analysis()
        self.publish_current()
        self.controller.next_chapter()
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: —')
        self.window._show_notation(NotationLine(old.position.fen, ('e2e4',), ('e4',)))
        self.assertEqual(self.window.pv_view.toPlainText(), '')
        self.engine.publish(old, 'e2e4', 999)
        self.ready()
        self.assertNotIn('9.99', self.window.evaluation_label.text())

    def test_same_fen_in_different_chapters_still_rejects_old_analysis(self):
        self.open_study('[Event "A"]\n*\n[Event "B"]\n*')
        old = self.add_analysis()
        self.next_search(lambda: self.controller.next_chapter())
        self.engine.publish(old, 'e2e4', 999)
        self.assertNotIn('9.99', self.window.evaluation_label.text())

    def test_new_document_failure_keeps_all_existing_chapters(self):
        self.open_study()
        original = self.controller.study
        self.controller.open_study(parse_pgn_text('1.e4 e5 2.Bh6 *'))
        self.ready()
        self.assertIs(self.controller.study, original)
        self.assertEqual(len(original.chapters), 3)

    def test_replacing_root_only_chapter_still_confirms_entire_study(self):
        self.open_study('[Event "A"]\n*\n[Event "B"]\n*')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No) as question:
            self.window.new_button.click()
        self.assertEqual(question.call_count, 1)
        self.assertEqual(len(self.controller.study.chapters), 2)

    def test_close_during_chapter_load_stops_helpers(self):
        self.open_study()
        self.controller.next_chapter()
        self.window.close()
        stage4.wait_until(lambda: self.window._helpers_stopped())
        self.assertEqual(self.controller.phase, 'closed')
