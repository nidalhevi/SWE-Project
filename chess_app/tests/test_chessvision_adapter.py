"""Adapter wiring tests with model predictions mocked; not accuracy measurements."""
import importlib.util
from pathlib import Path
import tempfile
import sys
import types
import unittest
from unittest.mock import Mock, patch

AVAILABLE = importlib.util.find_spec('numpy') is not None and importlib.util.find_spec('PIL') is not None


@unittest.skipUnless(AVAILABLE, 'Install NumPy and Pillow for the image adapter wiring tests')
class ChessvisionAdapterTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from PIL import Image
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / 'board image ü.png'
        Image.new('RGB', (3, 2), (10, 20, 30)).save(self.path)
        self.probabilities = np.zeros((64, 13))
        self.probabilities[:, 0] = 1

    def tearDown(self):
        self.directory.cleanup()

    def test_white_bottom_uses_orientation_zero_and_bgr(self):
        from chessvision_adapter import recognize
        package = types.ModuleType('chessvision')
        package.__path__ = []
        module = types.ModuleType('chessvision.classifier')
        instance = Mock()
        instance.probs.return_value = self.probabilities
        factory = Mock(return_value=instance)
        module.SquareClassifier = factory
        with patch.dict(sys.modules, {'chessvision': package, 'chessvision.classifier': module}):
            result = recognize(str(self.path), white_bottom=True)
        factory.assert_called_once_with()
        image = instance.probs.call_args.args[0]
        self.assertEqual(instance.probs.call_args.kwargs['orientation'], 0)
        self.assertEqual(image[0, 0].tolist(), [30, 20, 10])
        self.assertTrue(image.flags.c_contiguous)
        self.assertEqual(len(result['pieces']), 64)

    def test_black_bottom_uses_orientation_two_not_one(self):
        from chessvision_adapter import recognize
        with patch('chessvision_adapter._classify', return_value=self.probabilities) as classify:
            recognize(str(self.path), white_bottom=False)
        self.assertEqual(classify.call_args.args[1], 2)

    def test_label_and_square_order_matches_actual_model(self):
        from chessvision_adapter import recognize
        self.probabilities[0, :] = 0
        self.probabilities[0, 4] = 1  # White rook, a1.
        self.probabilities[63, :] = 0
        self.probabilities[63, 12] = 1  # Black king, h8.
        with patch('chessvision_adapter._classify', return_value=self.probabilities):
            result = recognize(str(self.path), white_bottom=True)
        self.assertEqual(result['pieces']['a1'], 'R')
        self.assertEqual(result['pieces']['h8'], 'k')
        self.assertIsNone(result['pieces']['e4'])

    def test_weak_prediction_remains_unknown(self):
        from chessvision_adapter import recognize
        self.probabilities[0, :] = 1 / 13
        with patch('chessvision_adapter._classify', return_value=self.probabilities):
            result = recognize(str(self.path), white_bottom=True)
        self.assertEqual(result['pieces']['a1'], '?')

    def test_phone_exif_rotation_is_applied(self):
        from PIL import Image
        from chessvision_adapter import _load_bgr
        path = self.root / 'rotated.jpg'
        exif = Image.Exif()
        exif[274] = 6
        Image.new('RGB', (3, 2)).save(path, exif=exif)
        self.assertEqual(_load_bgr(path).shape, (3, 2, 3))

    def test_corrupt_image_reports_error(self):
        from chessvision_adapter import _load_bgr
        self.path.write_text('not an image')
        with self.assertRaisesRegex(ValueError, 'Cannot read'):
            _load_bgr(self.path)

    def test_missing_image_reports_error(self):
        from chessvision_adapter import _load_bgr
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            _load_bgr(self.root / 'missing.png')

    def test_heic_requests_conversion(self):
        from chessvision_adapter import _load_bgr
        path = self.root / 'phone.heic'
        path.write_bytes(b'fixture')
        with self.assertRaisesRegex(ValueError, 'Convert HEIC'):
            _load_bgr(path)

    def test_classifier_failure_is_not_replaced_with_fake_predictions(self):
        from chessvision_adapter import recognize
        with patch('chessvision_adapter._classify', side_effect=ValueError('no board found')):
            with self.assertRaisesRegex(ValueError, 'no board found'):
                recognize(str(self.path), white_bottom=True)

    def test_invalid_probability_shape_is_rejected(self):
        from chessvision_adapter import recognize
        with patch('chessvision_adapter._classify', return_value=[]):
            with self.assertRaisesRegex(ValueError, '64'):
                recognize(str(self.path), white_bottom=True)

    def test_metadata_is_left_for_the_gui_review(self):
        from chessvision_adapter import recognize
        with patch('chessvision_adapter._classify', return_value=self.probabilities):
            result = recognize(str(self.path), white_bottom=True)
        self.assertEqual(set(result), {'pieces', 'confidence', 'message'})

    def test_orientation_must_be_explicit_boolean(self):
        from chessvision_adapter import recognize
        with self.assertRaisesRegex(ValueError, 'True or False'):
            recognize(str(self.path), white_bottom=2)
