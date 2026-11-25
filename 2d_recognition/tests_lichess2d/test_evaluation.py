import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from evaluate_lichess_2d import evaluate, main
from tests_lichess2d.fixtures import END, render


class EvaluationTests(unittest.TestCase):
    def test_missing_images_count_as_wrong_including_empty_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            render(END).save(path / 'good.png')
            manifest = path / 'manifest.json'
            manifest.write_text(json.dumps([
                dict(image='good.png', fen=END, white_bottom=True),
                dict(image='missing.png', fen=END, white_bottom=False)]))
            report = evaluate(manifest)
            self.assertEqual(report['totals']['boards'], 2)
            self.assertEqual(report['totals']['exact_boards'], 1)
            self.assertEqual(report['totals']['unknown'], 64)
            self.assertEqual(report['totals']['errors'], 1)
            self.assertEqual(report['metrics']['board_accuracy'], .5)
            self.assertEqual(report['metrics']['coverage'], .5)
            self.assertEqual(report['metrics']['accepted_accuracy'], 1)
            self.assertEqual(report['metrics']['square_accuracy'], .5)

    def test_orientation_must_be_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cases.json'
            path.write_text(json.dumps([dict(image='irrelevant.png', fen=END)]))
            with self.assertRaisesRegex(ValueError, 'white_bottom'):
                evaluate(path)

    def test_gate_rejects_wrong_orientation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            render(END).save(path / 'board.png')
            manifest = path / 'cases.json'
            manifest.write_text(json.dumps([dict(image='board.png', fen=END, white_bottom=False)]))
            with redirect_stdout(StringIO()):
                self.assertEqual(main(['--manifest', str(manifest), '--min-board-accuracy', '0.95']), 1)
