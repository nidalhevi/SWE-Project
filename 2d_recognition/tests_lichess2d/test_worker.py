"""Real subprocess -> real templates -> existing version-1 recognition parser."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from image_import import parse_recognition
from tests_lichess2d.fixtures import END, render
from lichess_2d.notation import parse_placement

RECOGNITION_ROOT = Path(__file__).resolve().parents[1]
APP = RECOGNITION_ROOT.parent / "chess_app"


class WorkerIntegrationTests(unittest.TestCase):
    def test_real_worker_recognizes_flipped_unicode_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'flipped ü board.png'
            render(END, white_bottom=False).save(path)
            request = dict(
                path=str(path),
                request_id=71,
                white_bottom=False,
                backend="lichess_2d.adapter:recognize",
                vision_path=str(RECOGNITION_ROOT),
            )
            result = subprocess.run([sys.executable, str(APP / 'image_recognition_worker.py'),
                                     '--request', json.dumps(request)], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            parsed = parse_recognition(result.stdout, 71)
            self.assertEqual({observation.square: observation.piece for observation in parsed.squares},
                             parse_placement(END))
            self.assertEqual(parsed.status, 'ok')

    def test_recognized_position_is_accepted_by_actual_referee(self):
        # Reuse the project's established WSL/native referee command selection.
        from tests_stage6.test_pgn_referee import referee_command
        from lichess_2d.recognizer import recognize_board
        from lichess_2d.notation import placement_of
        result = recognize_board(render(END), white_bottom=True)
        fen = placement_of(result['pieces']) + ' w - - 0 1'
        process = subprocess.run(referee_command(), input='position ' + fen + '\nfen\nquit\n',
                                 text=True, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn(fen, process.stdout)
