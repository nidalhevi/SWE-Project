"""Corrected drafts validated against the actual C referee; no Qt required."""
import unittest
from image_import import ImageDraft, PositionMetadata
from tests_stage6.test_pgn_referee import RefereeDriver
from pgn_service import PgnError


class ImageRefereeTests(unittest.TestCase):
    def setUp(self):
        self.referee = RefereeDriver()

    def tearDown(self):
        self.referee.close()

    def load(self, placement, metadata):
        draft = ImageDraft()
        draft.load_placement(placement)
        position = draft.position(metadata, reviewed=True)
        text = f'[SetUp "1"]\n[FEN "{position.fen}"]\n*'
        return self.referee.import_text(text)

    def test_castling_metadata_preserved(self):
        tree = self.load('r3k2r/8/8/8/8/8/8/R3K2R', PositionMetadata('w', 'KQkq', '-', 0, 42))
        self.assertEqual(tree.root.position.fen, 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 42')

    def test_en_passant_metadata_preserved(self):
        tree = self.load('4k3/8/8/3pP3/8/8/8/4K3', PositionMetadata('w', '-', 'd6', 0, 2))
        self.assertIn(' d6 ', tree.root.position.fen)

    def test_missing_kings_rejected(self):
        with self.assertRaises(PgnError):
            self.load('8/8/8/8/8/8/8/8', PositionMetadata('w'))

    def test_impossible_castling_right_rejected(self):
        with self.assertRaises(PgnError):
            self.load('4k3/8/8/8/8/8/8/4K3', PositionMetadata('w', 'K'))

    def test_impossible_en_passant_rejected(self):
        with self.assertRaises(PgnError):
            self.load('4k3/8/8/8/8/8/8/R3K3', PositionMetadata('w', '-', 'd6'))

    def test_black_move_number_preserved(self):
        tree = self.load('7k/8/8/8/8/8/8/R6K', PositionMetadata('b', '-', '-', 19, 42))
        self.assertTrue(tree.root.position.fen.endswith('b - - 19 42'))
