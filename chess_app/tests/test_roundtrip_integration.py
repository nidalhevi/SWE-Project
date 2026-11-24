"""Actual C referee + PGN/tree + analysis history. No Qt or ML weights needed."""
import unittest
from engine_protocol import SearchRequest, parse_info
from image_import import ImageDraft, PositionMetadata
from models import Move
from pgn_service import PgnError, export_pgn
from tests_stage6.test_pgn_referee import RefereeDriver, signature


def custom(fen, moves):
    return f'[SetUp "1"]\n[FEN "{fen}"]\n\n{moves}'


class CrossFeatureCoreTests(unittest.TestCase):
    def setUp(self):
        self.referee = RefereeDriver()

    def tearDown(self):
        self.referee.close()

    def test_special_move_branches_roundtrip_and_supply_analysis_history(self):
        cases = [
            ('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 10', '10.O-O (10.O-O-O) O-O-O *'),
            ('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2', '2.exd6 (2.Kd2) *'),
            ('7k/P7/8/8/8/8/8/7K w - - 0 1', '1.a8=Q+ (1.a8=R+) (1.a8=B) (1.a8=N) *'),
        ]
        for fen, moves in cases:
            with self.subTest(fen=fen):
                tree = self.referee.import_text(custom(fen, moves))
                before = signature(tree)
                copy = self.referee.import_text(export_pgn(tree))
                self.assertEqual(signature(copy), before)
                for node in copy.iter_nodes():
                    history = tuple(item.move for item in copy.path_to(node.node_id))
                    request = SearchRequest(1, node.position, copy.root.position, history, 100, 1)
                    expected = 'position fen ' + fen
                    if history:
                        expected += ' moves ' + ' '.join(move.uci for move in history)
                    self.assertEqual(request.command, expected)

    def test_transposed_positions_keep_distinct_paths_with_identical_fen(self):
        tree = self.referee.import_text('1.Nf3 (1.Nc3 Nc6 2.Nf3 Nf6) Nf6 2.Nc3 Nc6 *')
        leaves = [node for node in tree.iter_nodes() if len(tree.path_to(node.node_id)) == 4]
        self.assertEqual(len(leaves), 2)
        self.assertEqual(leaves[0].position.fen, leaves[1].position.fen)
        self.assertNotEqual(leaves[0].node_id, leaves[1].node_id)
        commands = []
        for node in leaves:
            path = tuple(item.move for item in tree.path_to(node.node_id))
            commands.append(SearchRequest(1, node.position, tree.root.position, path, 100, 1).command)
        self.assertNotEqual(*commands)
        copy = self.referee.import_text(export_pgn(tree))
        self.assertEqual(signature(copy), signature(tree))

    def test_reviewed_image_metadata_roundtrips_through_pgn_and_analysis(self):
        draft = ImageDraft()
        draft.load_placement('r3k2r/8/8/8/8/8/8/R3K2R')
        position = draft.position(PositionMetadata('b', 'KQkq', '-', 23, 42), reviewed=True)
        tree = self.referee.import_text(custom(position.fen, '42...O-O *'))
        copy = self.referee.import_text(export_pgn(tree))
        self.assertEqual(copy.root.position.fen, position.fen)
        node = copy.mainline()[-1]
        self.assertEqual(node.position.pieces['g8'], 'k')
        self.assertEqual(node.position.pieces['f8'], 'r')
        self.assertEqual(copy.label(node.node_id), '42... O-O')
        request = SearchRequest(2, node.position, copy.root.position, (node.move,), 100, 2)
        self.assertTrue(request.command.endswith(' moves e8g8'))

    def test_black_custom_root_scores_stay_white_perspective(self):
        fen = '7k/8/8/8/8/8/8/R6K b - - 19 42'
        tree = self.referee.import_text(custom(fen, '*'))
        request = SearchRequest(12, tree.root.position, tree.root.position, (), 100, 3)
        result = parse_info('info depth 9 score cp 87 pv h8g8', request)
        self.assertEqual(result.position.fen, fen)
        self.assertEqual(result.request_id, 12)
        self.assertEqual(result.score_cp, -87)
        self.assertEqual(result.best_move.uci, 'h8g8')

    def test_illegal_import_does_not_contaminate_next_valid_import(self):
        with self.assertRaises(PgnError):
            self.referee.import_text('1.e4 e5 (1...Bh6) *')
        good = self.referee.import_text('1.d4 d5 2.c4 *')
        self.assertEqual([node.move.uci for node in good.mainline()], ['d2d4', 'd7d5', 'c2c4'])
        self.assertEqual(self.referee.ask('fen'), good.root.position.fen)
