"""Actual worker/new recognizer/old response parser and C referee, without Qt."""

import recognition_test_bootstrap
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image
from image_import import ImageDraft, PositionMetadata, parse_recognition
from image_recognition_setup import find_recognition_root
from recognition_request import build_request

APP = Path(__file__).resolve().parents[1]
RECOGNITION = find_recognition_root(APP)
if RECOGNITION is None:
    raise RuntimeError('Install the stage-6/7 recognition package before running these tests')
sys.path.insert(0, str(RECOGNITION))
from lichess_2d.notation import parse_placement
from lichess_2d.theme_profiles import START, approve_profile, create_profile
from tests_lichess2d.fixtures import MIDDLE, render


def run_worker(path, *, profile=None, rectangle=None, backend='lichess_2d.adapter_2d:recognize', vision=None):
    request = build_request(path, request_id=71, white_bottom=False, backend=backend,
                            vision_path=vision or RECOGNITION, profile_path=profile, board_rect=rectangle)
    return subprocess.run([sys.executable, str(APP / 'image_recognition_worker.py'), '--request', json.dumps(request)],
                          capture_output=True, timeout=20)


class WorkerBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.path = cls.root / 'screenshot ü.png'
        image = Image.new('RGB', (900, 700), '#2b2b2b')
        image.paste(render(MIDDLE, cell=64, white_bottom=False), (117, 83))
        image.save(cls.path)
        cls.profile = create_profile(render(START), name='Bridge profile ü', output_dir=cls.root / 'profile ü', white_bottom=True)
        approve_profile(cls.profile.path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_real_profile_and_original_image_rectangle_reach_existing_parser(self):
        process = run_worker(self.path, profile=str(self.profile.path), rectangle=[117, 83, 512, 512])
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
        result = parse_recognition(process.stdout, 71)
        self.assertEqual({p.square: p.piece for p in result.squares}, parse_placement(MIDDLE))
        self.assertEqual(len(result.squares), 64)
        self.assertIn('Bridge profile ü', result.message)
        self.assertTrue(all(p.confidence is not None for p in result.squares))

    def test_builtin_requires_explicit_selection(self):
        result = run_worker(self.path, profile='builtin:cburnett', rectangle=[117, 83, 512, 512])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(parse_recognition(result.stdout, 71).status, 'ok')
        absent = run_worker(self.path, rectangle=[117, 83, 512, 512])
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn(b'Choose a matching theme profile', absent.stderr)

    def test_worker_discovers_separate_package_without_environment_flags(self):
        request = build_request(self.path, request_id=72, white_bottom=False,
                                backend='lichess_2d.adapter_2d:recognize', profile_path='builtin:cburnett',
                                board_rect=[117, 83, 512, 512])
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        process = subprocess.run([sys.executable, str(APP / 'image_recognition_worker.py'), '--request', json.dumps(request)],
                                 env=environment, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
        self.assertEqual(parse_recognition(process.stdout, 72).status, 'ok')

    def test_bad_profile_and_rectangle_do_not_fall_back_to_another_model(self):
        for profile, rect in ((str(self.root / 'missing.json'), [117, 83, 512, 512]),
                              ('builtin:cburnett', [800, 83, 512, 512])):
            with self.subTest(profile=profile):
                process = run_worker(self.path, profile=profile, rectangle=rect)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(process.stdout, b'')

    def test_legacy_callable_and_stdout_isolation_still_work(self):
        backend = self.root / 'legacy_backend.py'
        backend.write_text('''def recognize(path, *, white_bottom):
    print("legacy log")
    return {"request_id":999,"status":"unavailable","pieces":{"e1":"K"}}
''')
        process = run_worker(self.path, backend='legacy_backend:recognize', vision=self.root)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn(b'legacy log', process.stderr)
        parsed = parse_recognition(process.stdout, 71)
        self.assertEqual(parsed.status, 'ok')
        self.assertEqual(parsed.request_id, 71)

    def test_incompatible_backend_cannot_silently_ignore_profile_options(self):
        (self.root / 'old_signature.py').write_text('def recognize(path, *, white_bottom): return {"pieces":{}}')
        process = run_worker(self.path, profile='builtin:cburnett', backend='old_signature:recognize', vision=self.root)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b'does not support', process.stderr)

    def test_reviewed_position_from_worker_is_accepted_by_actual_referee(self):
        from tests_stage6.test_pgn_referee import referee_command
        process = run_worker(self.path, profile='builtin:cburnett', rectangle=[117, 83, 512, 512])
        self.assertEqual(process.returncode, 0, process.stderr)
        draft = ImageDraft()
        draft.apply(parse_recognition(process.stdout, 71))
        position = draft.position(PositionMetadata('w'), reviewed=True)
        expected = MIDDLE + ' w - - 0 1'
        self.assertEqual(position.fen, expected)
        referee = subprocess.run(referee_command(), input='position ' + expected + '\nfen\nquit\n',
                                  capture_output=True, text=True, timeout=20)
        self.assertEqual(referee.returncode, 0, referee.stderr)
        self.assertIn(expected, referee.stdout)
