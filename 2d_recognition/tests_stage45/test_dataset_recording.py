from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from record_eval_case_2d import main
from tests_lichess2d.fixtures import render, MIDDLE


class DatasetRecordingTests(unittest.TestCase):
    def test_recording_copies_original_image_and_preserves_fen_and_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'Screenshot ü.png'
            render(MIDDLE, cell=64).save(source)
            manifest = root / 'dataset/cases.json'
            with redirect_stdout(StringIO()):
                self.assertEqual(main(['--manifest', str(manifest), '--init', '--name', 'Generated fixture',
                                       '--origin', 'generated', '--split', 'validation']), 0)
                self.assertEqual(main(['--manifest', str(manifest), '--id', 'middle-01', '--image', str(source),
                                       '--fen', MIDDLE, '--white-bottom', '--rect', '0', '0', '512', '512']), 0)
            case = json.loads(manifest.read_text())['cases'][0]
            self.assertEqual(case['fen'], MIDDLE)
            self.assertEqual(case['rect'], [0, 0, 512, 512])
            self.assertEqual((manifest.parent / case['image']).read_bytes(), source.read_bytes())

    def test_duplicate_case_id_cannot_replace_recorded_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.png'
            render(MIDDLE, cell=64).save(source)
            manifest = root / 'dataset/cases.json'
            with redirect_stdout(StringIO()):
                main(['--manifest', str(manifest), '--init', '--name', 'Generated fixture',
                      '--origin', 'generated', '--split', 'validation'])
                arguments = ['--manifest', str(manifest), '--id', 'x', '--image', str(source),
                             '--fen', MIDDLE, '--white-bottom']
                self.assertEqual(main(arguments), 0)
                before = manifest.read_bytes()
                with redirect_stderr(StringIO()):
                    self.assertEqual(main(arguments), 2)
                self.assertEqual(manifest.read_bytes(), before)
