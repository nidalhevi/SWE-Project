"""Execute the actual adapter subprocess. Test plugins make no recognition claim."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from image_import import ImageImportError, parse_recognition

WORKER = str(Path(__file__).resolve().parents[1] / 'image_recognition_worker.py')


class RecognitionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.image = self.root / 'photo with spaces ü.png'
        # Adapter tests pass a file; image decoding is independently tested in Qt.
        self.image.write_bytes(b'fixture')

    def tearDown(self):
        self.directory.cleanup()

    def run_worker(self, source=None, **changes):
        if source is not None:
            (self.root / 'fixture_backend.py').write_text(source, encoding='utf-8')
        request = dict(path=str(self.image), request_id=7, white_bottom=False,
                       backend='fixture_backend:recognize' if source else None,
                       vision_path=str(self.root))
        request.update(changes)
        return subprocess.run([sys.executable, WORKER, '--request', json.dumps(request)],
                              capture_output=True, timeout=5)

    def test_missing_classifier_reports_unavailable(self):
        process = self.run_worker()
        self.assertEqual(process.returncode, 0)
        result = parse_recognition(process.stdout, 7)
        self.assertEqual(result.status, 'unavailable')
        self.assertIn('No piece recognizer', result.message)

    def test_plugin_receives_path_and_orientation(self):
        process = self.run_worker('''def recognize(path, *, white_bottom):
    assert "photo with spaces" in path
    assert white_bottom is False
    return {"pieces": {"e1": "K", "e8": "k", "a1": None}, "confidence": {"e1": 0.75}}
''')
        self.assertEqual(process.returncode, 0, process.stderr)
        result = parse_recognition(process.stdout, 7)
        self.assertEqual(result.squares[4].piece, 'K')

    def test_plugin_prints_do_not_corrupt_json(self):
        process = self.run_worker('''def recognize(path, *, white_bottom):
    print("loading model")
    return {"pieces": {"e1": "K"}}
''')
        self.assertIn(b'loading model', process.stderr)
        self.assertEqual(parse_recognition(process.stdout, 7).status, 'ok')

    def test_plugin_cannot_override_request_id(self):
        process = self.run_worker('''def recognize(path, *, white_bottom):
    return {"request_id": 999, "status": "unavailable", "pieces": {}}
''')
        self.assertEqual(parse_recognition(process.stdout, 7).request_id, 7)

    def test_plugin_errors_are_nonzero(self):
        process = self.run_worker('''def recognize(path, *, white_bottom):
    raise RuntimeError("model weights missing")
''')
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b'model weights missing', process.stderr)

    def test_invalid_predictions_rejected(self):
        process = self.run_worker('''def recognize(path, *, white_bottom):
    return {"pieces": {"e1": "elephant"}}
''')
        with self.assertRaises(ImageImportError):
            parse_recognition(process.stdout, 7)

    def test_missing_image_and_module_errors(self):
        for changes in [dict(path=str(self.root / 'missing.png')), dict(backend='missing_backend:recognize'),
                        dict(backend='bad;command'), dict(vision_path=str(self.root / 'missing'), backend='x:y')]:
            with self.subTest(changes=changes):
                process = self.run_worker(**changes)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(process.stdout)
