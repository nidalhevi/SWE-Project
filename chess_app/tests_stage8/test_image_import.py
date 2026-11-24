import json
import unittest
from image_import import (
    ImageDraft, ImageImportError, PositionMetadata, SQUARES, UNKNOWN, parse_recognition,
    recognition_from_probabilities,
)
from models import STARTING_FEN


def response(*, ident=1, **changes):
    payload = dict(version=1, request_id=ident, status='ok', pieces={}, confidence={})
    payload.update(changes)
    return json.dumps(payload).encode()


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.draft = ImageDraft()

    def complete(self):
        self.draft.load_placement(STARTING_FEN.split()[0])

    def test_unknown_is_distinct_from_empty(self):
        self.assertEqual(len(self.draft.unknown_squares), 64)
        self.draft.set_square('a1', None)
        self.assertEqual(len(self.draft.unknown_squares), 63)
        self.assertIsNone(self.draft.cells['a1'])

    def test_recognition_keeps_omitted_squares_unknown(self):
        self.draft.apply(parse_recognition(response(pieces={'e1': 'K', 'e8': 'k', 'a1': None}), 1))
        self.assertEqual(self.draft.cells['e1'], 'K')
        self.assertEqual(self.draft.cells['a2'], UNKNOWN)
        self.assertEqual(len(self.draft.unknown_squares), 61)

    def test_confidence_and_manual_correction(self):
        self.draft.apply(parse_recognition(response(pieces={'e1': 'K'}, confidence={'e1': .6}), 1))
        self.assertEqual(self.draft.uncertain_squares, ('e1',))
        self.draft.set_square('e1', 'Q')
        self.assertFalse(self.draft.uncertain_squares)

    def test_rotation_preserves_color_and_confidence(self):
        self.draft.apply(parse_recognition(response(pieces={'a1': 'R', 'e8': 'k'}, confidence={'a1': .7}), 1))
        self.draft.rotate_assignments()
        self.assertEqual(self.draft.cells['h8'], 'R')
        self.assertEqual(self.draft.cells['d1'], 'k')
        self.assertEqual(self.draft.confidence['h8'], .7)
        self.draft.rotate_assignments()
        self.assertEqual(self.draft.cells['a1'], 'R')

    def test_unknowns_block_position_even_after_review(self):
        with self.assertRaisesRegex(ImageImportError, 'unknown'):
            self.draft.position(PositionMetadata(turn='w'), reviewed=True)

    def test_turn_must_be_explicit(self):
        self.complete()
        with self.assertRaisesRegex(ImageImportError, 'turn'):
            self.draft.position(PositionMetadata(), reviewed=True)

    def test_review_must_be_explicit(self):
        self.complete()
        with self.assertRaisesRegex(ImageImportError, 'Review'):
            self.draft.position(PositionMetadata(turn='w'))

    def test_all_six_fen_fields_are_preserved(self):
        self.draft.load_placement('r3k2r/8/8/8/8/8/8/R3K2R')
        position = self.draft.position(PositionMetadata('b', 'KQkq', '-', 23, 42), reviewed=True)
        self.assertEqual(position.fen, 'r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 23 42')

    def test_placement_paste_does_not_accept_hidden_metadata(self):
        with self.assertRaisesRegex(ImageImportError, 'only'):
            self.draft.load_placement(STARTING_FEN)

    def test_invalid_placement_leaves_old_draft(self):
        self.complete()
        before = self.draft.cells.copy()
        with self.assertRaises(ImageImportError):
            self.draft.load_placement('9/8/8/8/8/8/8/8')
        self.assertEqual(self.draft.cells, before)

    def test_unavailable_does_not_replace_manual_edits(self):
        self.draft.set_square('e1', 'K')
        result = parse_recognition(response(status='unavailable', message='No classifier'), 1)
        self.assertFalse(self.draft.apply(result))
        self.assertEqual(self.draft.cells['e1'], 'K')

    def test_counter_limits(self):
        self.complete()
        for half, full in [(-1, 1), (10000, 1), (0, 0), (0, 10000), (True, 1)]:
            with self.subTest(half=half, full=full), self.assertRaises(ImageImportError):
                self.draft.position(PositionMetadata('w', '-', '-', half, full), reviewed=True)

    def test_mark_unknown_empty_retains_pieces(self):
        self.draft.set_square('e1', 'K')
        self.draft.mark_unknown_empty()
        self.assertFalse(self.draft.unknown_squares)
        self.assertEqual(self.draft.cells['e1'], 'K')

    def test_preview_does_not_change_unknowns(self):
        self.draft.preview()
        self.assertEqual(len(self.draft.unknown_squares), 64)

    def test_square_and_piece_validation(self):
        for square, piece in [('i1', 'K'), ('a0', 'K'), ('a1', 'queen'), ('a1', 3)]:
            with self.subTest(square=square, piece=piece), self.assertRaises(ImageImportError):
                self.draft.set_square(square, piece)


class RecognitionSchemaTests(unittest.TestCase):
    def test_complete_known_empty_mapping(self):
        result = parse_recognition(response(pieces=dict.fromkeys(SQUARES)), 1)
        self.assertEqual(len(result.squares), 64)
        self.assertTrue(all(item.piece is None for item in result.squares))

    def test_wrong_id_and_version_rejected(self):
        for changes in [dict(request_id=2), dict(request_id=True), dict(version=2), dict(version=True)]:
            with self.subTest(changes=changes), self.assertRaises(ImageImportError):
                parse_recognition(response(**changes), 1)

    def test_invalid_schema_rejected(self):
        for changes in [dict(pieces=[]), dict(pieces={'z9': 'K'}), dict(pieces={'e1': 'king'}),
                        dict(confidence={'e1': float('nan')}), dict(confidence={'e1': True}),
                        dict(confidence={'e1': 1.1}), dict(status='failed'), dict(message=3),
                        dict(status='unavailable', pieces={'e1': 'K'})]:
            with self.subTest(changes=changes), self.assertRaises(ImageImportError):
                parse_recognition(response(**changes), 1)

    def test_duplicate_fields_rejected(self):
        with self.assertRaisesRegex(ImageImportError, 'Duplicate'):
            parse_recognition(b'{"version":1,"version":1,"request_id":1,"status":"ok"}', 1)

    def test_oversized_and_truncated_output_rejected(self):
        for data in [b'{' * 262145, b'{"version":1', b'[]', b'not JSON', b'\xff']:
            with self.subTest(length=len(data)), self.assertRaises(ImageImportError):
                parse_recognition(data, 1)


class ProbabilityAdapterTests(unittest.TestCase):
    def rows(self):
        return [[1.] + [0.] * 12 for _ in range(64)]

    def test_label_order_and_square_index_match_teammate(self):
        rows = self.rows()
        rows[0] = [0.] * 13
        rows[0][4] = 1.  # White rook on a1.
        rows[63] = [0.] * 13
        rows[63][12] = 1.  # Black king on h8.
        result = recognition_from_probabilities(rows)
        self.assertEqual(result['pieces']['a1'], 'R')
        self.assertEqual(result['pieces']['h8'], 'k')
        self.assertIsNone(result['pieces']['e4'])

    def test_low_confidence_and_ties_remain_unknown(self):
        rows = self.rows()
        rows[0] = [1 / 13] * 13
        rows[1] = [.5, .5] + [0.] * 11
        result = recognition_from_probabilities(rows)
        self.assertEqual(result['pieces']['a1'], UNKNOWN)
        self.assertEqual(result['pieces']['b1'], UNKNOWN)

    def test_invalid_shapes_and_logits_rejected(self):
        for rows in [[], [[1.] * 13] * 64, [[0.] * 12] * 64, [[float('nan')] * 13] * 64]:
            with self.subTest(length=len(rows)), self.assertRaises(ImageImportError):
                recognition_from_probabilities(rows)

    def test_threshold_controls_uncertainty(self):
        rows = self.rows()
        rows[0] = [.7, .3] + [0.] * 11
        self.assertEqual(recognition_from_probabilities(rows, min_confidence=.8)['pieces']['a1'], UNKNOWN)
