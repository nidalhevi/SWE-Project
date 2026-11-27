"""A game read from photos: the JSON record, its PGN text, and loading it in the window."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QFileDialog

from models import STARTING_FEN
from pgn_service import parse_pgn_text
from photo_game import game_from_record, load_photo_game, pgn_text
from tests.gui_support import WindowCase, stage4

AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'
AFTER_E5 = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2'
AFTER_NF3 = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2'
AFTER_NC6 = 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3'


def ply(n, san, uci, fen, recovered=False):
    return {'n': n, 'san': san, 'uci': uci, 'fen_after': fen, 'photo': f'{n}.jpg',
            'confidence': 9.0, 'recovered': recovered, 'corrected': False}


RECORD = {
    'version': 1, 'start_fen': STARTING_FEN, 'final_fen': AFTER_E5, 'status': 'ongoing',
    'pgn': '1. e4 e5 *\n',
    'plies': [ply(1, 'e4', 'e2e4', AFTER_E4), ply(2, 'e5', 'e7e5', AFTER_E5, recovered=True)],
}
FOUR = dict(RECORD, final_fen=AFTER_NC6, pgn='1. e4 e5 2. Nf3 Nc6 *\n', plies=[
    ply(1, 'e4', 'e2e4', AFTER_E4), ply(2, 'e5', 'e7e5', AFTER_E5),
    ply(3, 'Nf3', 'g1f3', AFTER_NF3, recovered=True), ply(4, 'Nc6', 'b8c6', AFTER_NC6)])


class RecordTests(unittest.TestCase):
    def test_positions_and_labels(self):
        game = game_from_record(RECORD)
        self.assertEqual(game.position_at(0).fen, STARTING_FEN)
        self.assertEqual(game.position_at(1).pieces['e4'], 'P')
        self.assertEqual(game.position_at(2).fen, AFTER_E5)
        self.assertEqual([p.label for p in game.plies], ['1. e4', '1... e5 ?'])
        self.assertEqual((game.plies[0].move.uci, game.plies[0].move.san), ('e2e4', 'e4'))
        with self.assertRaises(IndexError):
            game.position_at(3)

    def test_empty_game(self):
        record = dict(RECORD, plies=[], final_fen=STARTING_FEN)
        self.assertEqual(game_from_record(record).position_at(0).fen, STARTING_FEN)

    def test_malformed_records_are_rejected(self):
        damages = {
            'version': lambda r: r.update(version=2),
            'no start': lambda r: r.pop('start_fen'),
            'final fen': lambda r: r.update(final_fen=AFTER_E4),
            'numbering': lambda r: r['plies'][1].update(n=5),
            'uci': lambda r: r['plies'][0].update(uci='e2'),
            'fen': lambda r: r['plies'][0].update(fen_after='not a fen'),
            'plies': lambda r: r.update(plies=None),
        }
        for name, damage in damages.items():
            with self.subTest(name):
                record = copy.deepcopy(RECORD)
                damage(record)
                with self.assertRaises(ValueError):
                    game_from_record(record)

    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / 'game.json'
            good.write_text(json.dumps(RECORD))
            self.assertEqual(len(load_photo_game(str(good)).plies), 2)
            bad = Path(directory) / 'bad.json'
            bad.write_text('[1, 2')
            with self.assertRaises(ValueError):
                load_photo_game(str(bad))


class PgnTextTests(unittest.TestCase):
    def test_unclear_moves_carry_a_comment_and_black_is_renumbered_after_it(self):
        text = pgn_text(game_from_record(FOUR))
        self.assertIn('1. e4 e5 2. Nf3 {unclear photo} 2... Nc6 *', text)
        self.assertIn('[Event "Photo game"]', text)
        self.assertNotIn('[FEN', text)

    def test_text_parses_back_to_the_same_moves(self):
        game = parse_pgn_text(pgn_text(game_from_record(FOUR)))[0]
        sans = [game.nodes[i].san for i in sorted(game.nodes)[1:]]
        self.assertEqual(sans, ['e4', 'e5', 'Nf3', 'Nc6'])
        self.assertEqual(game.nodes[3].comment, 'unclear photo')
        self.assertIn('4 moves, 1 marked', game.nodes[0].comment)

    def test_game_from_another_position_keeps_its_fen_and_numbers(self):
        record = dict(RECORD, start_fen=AFTER_E4, final_fen=AFTER_NF3, pgn='1... e5 2. Nf3 *\n', plies=[
            ply(1, 'e5', 'e7e5', AFTER_E5), ply(2, 'Nf3', 'g1f3', AFTER_NF3)])
        text = pgn_text(game_from_record(record))
        self.assertIn(f'[FEN "{AFTER_E4}"]', text)
        self.assertIn('1... e5 2. Nf3 *', text)
        self.assertEqual(parse_pgn_text(text)[0].starting_position.fen, AFTER_E4)

    def test_result_comes_from_the_reader(self):
        record = dict(RECORD, status='checkmate', pgn='1. e4 e5 1-0\n')
        self.assertTrue(pgn_text(game_from_record(record)).rstrip().endswith('1-0'))


class PhotoGameWindowTests(WindowCase):
    def test_finished_reader_loads_the_game_with_unclear_moves_marked(self):
        self.window.photos.finished.emit(game_from_record(FOUR))
        self.ready()
        tree = self.controller.tree
        self.assertEqual([node.move.san for node in tree.mainline()], ['e4', 'e5', 'Nf3', 'Nc6'])
        nf3 = tree.mainline()[2].node_id
        self.assertEqual(tree.annotations(nf3).comment, 'unclear photo')
        self.assertEqual(tree.headers['Event'], 'Photo game')
        self.assertFalse(self.window.error_label.isVisible())

    def test_reader_failure_is_shown_and_the_game_is_kept(self):
        self.play('e2e4')
        before = self.controller.position.fen
        self.window.photos.failed.emit('Photo reader failed (code 1): no photos in folder')
        self.assertEqual(self.window.error_label.text(), 'Photos: Photo reader failed (code 1): no photos in folder')
        self.assertTrue(self.window.error_label.isVisible())
        self.assertEqual(self.controller.position.fen, before)

    def test_button_starts_the_reader_on_the_chosen_folder_and_locks_while_busy(self):
        started = []
        with patch.object(QFileDialog, 'getExistingDirectory', return_value='/photos/game1'), \
                patch.object(type(self.window.photos), 'start', lambda importer, folder: started.append(folder)), \
                patch.object(type(self.window.photos), 'busy', property(lambda importer: bool(started))):
            self.window.photo_game_button.click()
            self.assertEqual(started, ['/photos/game1'])
            self.assertFalse(self.window.photo_game_button.isEnabled())
            self.window.photo_game_button.click()
            self.assertEqual(len(started), 1)

    def test_cancelled_folder_dialog_does_nothing(self):
        with patch.object(QFileDialog, 'getExistingDirectory', return_value=''), \
                patch.object(type(self.window.photos), 'start') as start:
            self.window.photo_game_button.click()
            start.assert_not_called()


class MoveListLayoutTests(WindowCase):
    def test_a_line_is_flat_and_only_alternatives_are_indented(self):
        text = '1. e4 e5 (1... c5 2. Nf3) 2. Nf3 Nc6 *'
        self.controller.import_game(parse_pgn_text(text)[0])
        self.ready()
        widget, items, tree = self.window.moves_tree, self.window._node_items, self.controller.tree
        main = tree.mainline()
        self.assertEqual([widget.topLevelItem(i).text(0) for i in range(widget.topLevelItemCount())],
                         ['Starting position', '1. e4', '1... e5', '2. Nf3', '2... Nc6'])
        e5 = items[main[1].node_id]
        self.assertEqual([e5.child(i).text(0) for i in range(e5.childCount())],
                         ['1... c5 (variation)', '2. Nf3'])
        self.assertEqual(len(items), len(tree))


if __name__ == '__main__':
    unittest.main()
