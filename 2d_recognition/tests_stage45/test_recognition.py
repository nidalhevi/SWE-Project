"""Generated pixel fixtures establish decisions, not real screenshot accuracy."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image, ImageDraw
from lichess_2d.recognizer_2d import RecognitionSettings, Recognizer2D
from lichess_2d.notation import parse_placement
from lichess_2d.theme_profiles import START, approve_profile, create_profile
from tests_lichess2d.fixtures import render, MIDDLE, END


class SquareRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.model = Recognizer2D()
        p = create_profile(render(START), name='Unit-test calibration',
                           output_dir=Path(cls.directory.name) / 'profile', white_bottom=True)
        approve_profile(p.path)
        cls.profile_model = Recognizer2D(p.path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_uniform_light_dark_and_highlight_are_known_empty(self):
        for color in ('#f0d9b5', '#b58863', '#cdd26a'):
            with self.subTest(color=color):
                result = self.model.predict_square(Image.new('RGB', (64, 64), color))
                self.assertIsNone(result.piece)
                self.assertEqual(result.decision, 'empty')
                self.assertEqual(result.reason, 'uniform_background')

    def test_unrecognized_foreground_is_unknown_not_empty(self):
        tile = Image.new('RGB', (64, 64), '#f0d9b5')
        ImageDraw.Draw(tile).rectangle((10, 12, 51, 55), fill='#3a56ff')
        result = self.model.predict_square(tile)
        self.assertEqual(result.piece, '?')
        self.assertEqual(result.reason, 'poor_template_match')
        self.assertGreater(result.foreground_fraction, 0)

    def test_small_foreground_mark_does_not_become_empty(self):
        tile = Image.new('RGB', (64, 64), '#f0d9b5')
        ImageDraw.Draw(tile).rectangle((30, 30, 33, 33), fill='#604020')
        result = self.model.predict_square(tile)
        self.assertEqual(result.piece, '?')

    def test_ambiguous_best_match_remains_unknown(self):
        model = Recognizer2D(settings=RecognitionSettings(min_piece_margin=1))
        tile = render(START, cell=64).crop((64, 448, 128, 512))
        result = model.predict_square(tile)
        self.assertEqual(result.piece, '?')
        self.assertEqual(result.reason, 'ambiguous_piece_match')
        self.assertEqual(result.best_piece, 'N')
        self.assertNotEqual(result.best_piece, result.second_piece)

    def test_alignment_tolerance_and_diagnostics(self):
        tile = render(START, cell=64).crop((64, 448, 128, 512))
        moved = Image.new('RGB', (64, 64), '#f0d9b5')
        moved.paste(tile, (1, -1))
        result = self.model.predict_square(moved)
        self.assertEqual(result.piece, 'N')
        self.assertIn(result.alignment['dx'], (-1, 0, 1))
        self.assertIn(result.alignment['template_size'], (62, 64, 66))
        self.assertLess(result.best_error, result.second_error)
        self.assertGreater(result.margin, 0)

    def test_flipped_board_preserves_canonical_names(self):
        result, _ = self.profile_model.predict(render(END, white_bottom=False), white_bottom=False)
        self.assertEqual(result['pieces'], parse_placement(END))

    def test_multiple_resolutions(self):
        for size in (256, 511, 777):
            result, _ = self.model.predict(render(MIDDLE).resize((size, size)), white_bottom=True)
            self.assertEqual(result['pieces'], parse_placement(MIDDLE))

    def test_all_types_on_both_square_colors_with_calibrated_profile(self):
        for placement in ('PNBRQK2/pnbrqk2/8/8/8/8/8/8', '1PNBRQK1/1pnbrqk1/8/8/8/8/8/8'):
            result, _ = self.profile_model.predict(render(placement), white_bottom=True)
            self.assertEqual(result['pieces'], parse_placement(placement))

    def test_scores_are_named_quality_not_probability(self):
        result, _ = self.model.predict(render(END), white_bottom=True)
        self.assertIn('match_quality', result)
        self.assertNotIn('confidence', result)
        self.assertIn('not probabilities', result['engine']['score_meaning'])

    def test_nonfinite_thresholds_and_wrong_crop_size_rejected(self):
        with self.assertRaises(ValueError):
            RecognitionSettings(max_template_error=float('nan'))
        with self.assertRaises(ValueError):
            self.model.predict_square(Image.new('RGB', (32, 32)))

    def test_unknown_prevents_complete_piece_placement(self):
        image = render(END, cell=64)
        ImageDraw.Draw(image).rectangle((10, 12, 51, 55), fill='#3a56ff')
        result, _ = self.model.predict(image, white_bottom=True)
        self.assertEqual(result['pieces']['a8'], '?')
        self.assertIsNone(result['placement'])
