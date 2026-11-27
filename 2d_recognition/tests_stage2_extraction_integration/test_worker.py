"""Run against the existing GUI worker in the separate chess_app directory."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from lichess_2d.board_locator_2d import BoardRect, extract_position, load_image

RECOGNITION_ROOT = Path(__file__).resolve().parents[1]


def gui_directory():
    for directory in RECOGNITION_ROOT.parents:
        if directory.name == '2d_recognition':
            return directory.parent / 'chess_app'
    if RECOGNITION_ROOT.name == '2d_recognition':
        return RECOGNITION_ROOT.parent / 'chess_app'
    raise RuntimeError('Install these tests under ChessProject/2d_recognition first')


class SeparateWorkerTests(unittest.TestCase):
    def test_extracted_board_reaches_existing_worker_and_actual_referee(self):
        app = gui_directory()
        sys.path.insert(0, str(app))
        from image_import import parse_recognition
        from tests_stage6.test_pgn_referee import referee_command
        from lichess_2d.notation import placement_of
        image_path = RECOGNITION_ROOT / 'examples_lichess2d/generated_with_panels.png'
        with tempfile.TemporaryDirectory() as directory:
            with load_image(image_path) as image:
                extraction = extract_position(image, rect=BoardRect(105, 80, 512, 512), white_bottom=True)
            path = Path(directory) / 'confirmed ü board.png'
            extraction.board.save(path)
            request = dict(path=str(path), request_id=82, white_bottom=True,
                           backend='lichess_2d.adapter:recognize', vision_path=str(RECOGNITION_ROOT))
            worker = subprocess.run([sys.executable, str(app / 'image_recognition_worker.py'),
                                     '--request', json.dumps(request)], capture_output=True, timeout=20)
            self.assertEqual(worker.returncode, 0, worker.stderr.decode(errors='replace'))
            parsed = parse_recognition(worker.stdout, 82)
            pieces = {cell.square: cell.piece for cell in parsed.squares}
            expected = '6k1/1p3p2/7p/p3r3/P2R4/7P/2N2PP1/2R4K'
            self.assertEqual(placement_of(pieces), expected)
            fen = expected + ' w - - 0 1'
            referee = subprocess.run(referee_command(), input='position ' + fen + '\nfen\nquit\n',
                                      capture_output=True, text=True, timeout=20)
            self.assertEqual(referee.returncode, 0, referee.stderr)
            self.assertIn(fen, referee.stdout)
