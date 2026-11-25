"""Metric accounting checks; these do not load neural weights or claim accuracy."""
from pathlib import Path
import tempfile
import unittest
import importlib.util
import sys
import types
from unittest.mock import patch
from evaluate_chessred import Accuracy, options, sha256


class ChessredAuditTests(unittest.TestCase):
    def test_perfect_board_and_occupied_accuracy(self):
        truth = [0] * 32 + [1] * 16 + [7] * 16
        accuracy = Accuracy()
        accuracy.add(truth, truth)
        result = accuracy.summary()
        self.assertEqual(result['square_accuracy_percent'], 100)
        self.assertEqual(result['occupied_square_accuracy_percent'], 100)
        self.assertEqual(result['fully_correct_boards_percent'], 100)

    def test_empty_only_baseline_does_not_hide_piece_failure(self):
        accuracy = Accuracy()
        accuracy.add([0] * 48 + [1] * 16, [0] * 64)
        result = accuracy.summary()
        self.assertEqual(result['square_accuracy_percent'], 75)
        self.assertEqual(result['always_empty_baseline_percent'], 75)
        self.assertEqual(result['occupied_square_accuracy_percent'], 0)
        self.assertEqual(result['fully_correct_boards_percent'], 0)

    def test_failed_prediction_is_counted_as_wrong(self):
        accuracy = Accuracy()
        truth = [0] * 32 + [1] * 32
        accuracy.add(truth, truth)
        accuracy.add(truth, None)
        result = accuracy.summary()
        self.assertEqual(result['images'], 2)
        self.assertEqual(result['failed_images'], 1)
        self.assertEqual(result['square_accuracy_percent'], 50)
        self.assertEqual(result['occupied_square_accuracy_percent'], 50)

    def test_no_support_is_not_reported_as_perfect(self):
        accuracy = Accuracy()
        accuracy.add([0] * 64, [0] * 64)
        result = accuracy.summary()
        self.assertIsNone(result['occupied_square_accuracy_percent'])
        self.assertIsNone(result['per_class_recall']['WK']['accuracy_percent'])

    def test_invalid_labels_cannot_be_scored(self):
        for truth, prediction in [([0] * 63, [0] * 64), ([0] * 64, [13] * 64)]:
            with self.subTest(length=len(truth)), self.assertRaises(ValueError):
                Accuracy().add(truth, prediction)

    def test_checkpoint_hash_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'weights.pt'
            path.write_bytes(b'abc')
            self.assertEqual(sha256(path), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')

    def test_default_is_small_held_out_evaluation(self):
        args = options(['--vision-path', 'vision', '--dataset-dir', 'data'])
        self.assertEqual(args.split, 'test')
        self.assertEqual(args.limit, 20)
        self.assertEqual(args.mode, 'both')

    @unittest.skipUnless(importlib.util.find_spec('numpy') is not None, 'NumPy needed for mocked evaluation flow')
    def test_both_modes_run_and_report_checkpoint_identity(self):
        import numpy as np
        from evaluate_chessred import evaluate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vision = root / 'vision'
            (vision / 'chessvision').mkdir(parents=True)
            (vision / 'chessvision/classifier.py').write_text('# fixture')
            (vision / 'weights').mkdir()
            square_path, corner_path = vision / 'weights/square.pt', vision / 'weights/corner.pt'
            square_path.write_bytes(b'square fixture')
            corner_path.write_bytes(b'corner fixture')
            dataset = root / 'dataset'
            dataset.mkdir()
            (dataset / 'annotations.json').write_text('{}')
            image_path = dataset / 'fixture.jpg'
            image_path.write_bytes(b'image fixture')
            truth = [0] * 64
            truth[4], truth[60] = 6, 12
            corners = np.asarray([[0, 0], [7, 0], [7, 7], [0, 7]], dtype=np.float32)
            sample = types.SimpleNamespace(corners=corners, path=str(image_path), labels=truth, width=8, height=8)
            probabilities = np.eye(13)[truth]
            modules = {name: types.ModuleType(name) for name in (
                'cv2', 'torch', 'torchvision', 'chessvision', 'chessvision.classifier',
                'chessvision.corner_net', 'chessvision.board', 'chessvision.data',
                'chessvision.data.chessred', 'chessvision.labels')}
            modules['chessvision'].__path__ = []
            modules['chessvision.data'].__path__ = []
            cv = modules['cv2']
            cv.__version__ = 'fixture'
            cv.IMREAD_COLOR, cv.COLOR_BGR2GRAY, cv.IMWRITE_JPEG_QUALITY = 1, 2, 3
            cv.imdecode = lambda *args: np.zeros((8, 8, 3), dtype=np.uint8)
            cv.cvtColor = lambda image, code: image[:, :, 0]
            cv.imencode = lambda *args: (True, np.zeros(10, dtype=np.uint8))
            torch = modules['torch']
            torch.__version__ = modules['torchvision'].__version__ = 'fixture'
            torch.device, torch.set_num_threads = str, lambda threads: None
            classifier = modules['chessvision.classifier']
            classifier.__file__, classifier.DEFAULT_WEIGHTS = str(vision / 'chessvision/classifier.py'), str(square_path)
            classifier.SquareClassifier = lambda **kwargs: types.SimpleNamespace(grid_probs=lambda warped: probabilities)
            corner = modules['chessvision.corner_net']
            corner.DEFAULT_WEIGHTS = str(corner_path)
            corner.CornerPredictor = lambda **kwargs: lambda image: corners
            board = modules['chessvision.board']
            board.warp_for_crops = lambda image, corners: image
            board.grid_of_square = lambda orientation: np.arange(64)
            board.orientation_from_named = lambda corners, named: 0
            board.refine_by_warp = lambda gray, predicted: predicted
            board.corner_error = lambda predicted, named: 0.0
            modules['chessvision.data.chessred'].ChessReD = lambda path: types.SimpleNamespace(ids=lambda *args: [1], sample=lambda ident: sample)
            modules['chessvision.labels'].placement_to_fen = lambda labels: 'fixture placement'
            modules['chessvision'].classifier, modules['chessvision'].corner_net = classifier, corner
            args = options(['--vision-path', str(vision), '--dataset-dir', str(dataset)])
            with patch.dict(sys.modules, modules), patch('builtins.print'), patch.object(sys, 'path', list(sys.path)):
                report = evaluate(args)
            self.assertEqual(set(report['results']), {'annotated', 'detected'})
            self.assertEqual(report['results']['detected']['square_accuracy_percent'], 100)
            self.assertEqual(report['results']['annotated']['occupied_square_accuracy_percent'], 100)
            self.assertEqual(report['square_sha256'], sha256(square_path))
