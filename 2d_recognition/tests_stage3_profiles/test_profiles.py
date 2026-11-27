"""Generated fixtures test calibration mechanics; they are not browser benchmarks."""
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from lichess_2d.board_locator_2d import square_name
from lichess_2d.notation import parse_placement
from lichess_2d.recognizer import recognize_board
from lichess_2d.theme_profiles import START, PIECES, approve_profile, create_profile, load_profile
from tests_lichess2d.fixtures import render, MIDDLE


def letter_board(placement, *, white_bottom=True, highlights=()):
    """An independent icon theme, drawn as colored letters rather than Cburnett."""
    pieces = parse_placement(placement)
    board = Image.new('RGB', (512, 512))
    font = ImageFont.load_default(size=42)
    for row in range(8):
        for col in range(8):
            square = square_name(row, col, white_bottom)
            color = '#e1d4b0' if (row + col) % 2 == 0 else '#8f7662'
            if square in highlights:
                color = '#b6bd54'
            tile = Image.new('RGB', (64, 64), color)
            code = pieces[square]
            if code:
                draw = ImageDraw.Draw(tile)
                box = draw.textbbox((0, 0), code.upper(), font=font, stroke_width=1)
                x = (64 - box[2] + box[0]) // 2
                draw.text((x, 2), code.upper(), font=font, fill='#fafafa' if code.isupper() else '#162434',
                          stroke_width=1, stroke_fill='#202020')
            board.paste(tile, (col * 64, row * 64))
    return board


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.profile = create_profile(render(START, cell=80), name='My Lichess',
                                     output_dir=cls.root / 'lichess', white_bottom=True)
        approve_profile(cls.profile.path)
        cls.letter_profile = create_profile(letter_board(START), name='Colored letters',
                                            output_dir=cls.root / 'letters', white_bottom=True)
        approve_profile(cls.letter_profile.path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_profile_contains_all_types_backgrounds_and_reference_scale(self):
        profile = load_profile(self.profile.path)
        self.assertEqual(set(profile.templates), set(PIECES))
        self.assertEqual(set(profile.backgrounds), {'light', 'dark'})
        self.assertEqual(profile.metadata['reference']['original_square_size'], [80., 80.])
        self.assertEqual(profile.metadata['preprocessing']['square_size'], 64)
        self.assertTrue((profile.path.parent / 'template_review.png').is_file())
        self.assertEqual(len(list((profile.path.parent / 'samples').glob('*.png'))), 32)

    def test_core_masks_exclude_sampled_board_background(self):
        profile = load_profile(self.profile.path)
        for code, template in profile.templates.items():
            core = np.asarray(template.core) > 127
            support = np.asarray(template.support) > 127
            self.assertGreater(core.sum(), 30)
            self.assertFalse((core & ~support).any())
            self.assertLess(core.sum(), support.sum())
            self.assertEqual(np.asarray(template.rgba)[0, 0, 3], 0)

    def test_all_types_transfer_between_square_colors(self):
        for placement in ('PNBRQK2/pnbrqk2/8/8/8/8/8/8', '1PNBRQK1/1pnbrqk1/8/8/8/8/8/8'):
            with self.subTest(placement=placement):
                result = recognize_board(render(placement), white_bottom=True, profile=self.profile.path)
                self.assertEqual(result['pieces'], parse_placement(placement))

    def test_uniform_highlights_do_not_become_part_of_pieces(self):
        placement = '1PNBRQK1/1pnbrqk1/8/8/8/8/8/8'
        occupied = [s for s, p in parse_placement(placement).items() if p]
        result = recognize_board(render(placement, highlights=occupied), white_bottom=True, profile=self.profile.path)
        self.assertEqual(result['pieces'], parse_placement(placement))

    def test_new_theme_uses_its_own_learned_icons(self):
        result = recognize_board(letter_board(MIDDLE), white_bottom=True, profile=self.letter_profile.path)
        self.assertEqual(result['pieces'], parse_placement(MIDDLE))

    def test_flipped_calibration_and_flipped_recognition(self):
        path = self.root / 'flipped'
        profile = create_profile(render(START, white_bottom=False), name='Flipped calibration',
                                 output_dir=path, white_bottom=False)
        approve_profile(profile.path)
        result = recognize_board(render(MIDDLE, white_bottom=False), white_bottom=False, profile=profile.path)
        self.assertEqual(result['pieces'], parse_placement(MIDDLE))

    def test_draft_cannot_be_used_for_recognition(self):
        profile = create_profile(render(START), name='Unreviewed', output_dir=self.root / 'unreviewed', white_bottom=True)
        with self.assertRaisesRegex(ValueError, 'draft'):
            recognize_board(render(MIDDLE), white_bottom=True, profile=profile.path)
        self.assertFalse(load_profile(profile.path, require_reviewed=False).metadata['reviewed'])

    def test_changed_templates_invalidate_review(self):
        import shutil
        path = self.root / 'tampered'
        shutil.copytree(self.profile.path.parent, path)
        artifact = path / 'templates/wQ_core.png'
        artifact.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed after calibration'):
            load_profile(path)

    def test_existing_profile_is_never_overwritten(self):
        old = self.profile.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'never overwritten'):
            create_profile(render(START), name='Overwrite', output_dir=self.profile.path.parent, white_bottom=True)
        self.assertEqual(self.profile.path.read_bytes(), old)

    def test_non_starting_or_highlighted_reference_is_rejected(self):
        for index, image in enumerate((render(MIDDLE), render(START, highlights=('e4',)),
                                        render(START, highlights=('d1',)))):
            with self.subTest(index=index), self.assertRaises(ValueError):
                create_profile(image, name='Bad reference', output_dir=self.root / f'bad-{index}', white_bottom=True)

    def test_unknown_preprocessing_version_is_rejected(self):
        import shutil
        path = self.root / 'wrong-version'
        shutil.copytree(self.profile.path.parent, path)
        data = json.loads((path / 'profile.json').read_text())
        data['preprocessing']['version'] = 99
        (path / 'profile.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            load_profile(path)

    def test_cli_creates_draft_then_separate_explicit_approval(self):
        from calibrate_2d import main
        image = self.root / 'starting ü.png'
        render(START).save(image)
        output = self.root / 'cli-profile'
        with redirect_stdout(StringIO()):
            self.assertEqual(main(['--image', str(image), '--name', 'Unicode profile ü',
                                   '--white-bottom', '--output', str(output)]), 0)
            self.assertFalse(load_profile(output, require_reviewed=False).metadata['reviewed'])
            self.assertEqual(main(['--approve', str(output)]), 0)
        self.assertTrue(load_profile(output).metadata['reviewed'])


class ProfileWorkerTests(unittest.TestCase):
    def test_existing_worker_receives_profile_without_global_environment_mutation(self):
        root = Path(__file__).resolve().parents[1]
        parent = root if root.name == '2d_recognition' else root.parent
        if parent.name != '2d_recognition':
            raise RuntimeError('Install under ChessProject/2d_recognition before running worker integration')
        app = parent.parent / 'chess_app'
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            profile = create_profile(letter_board(START), name='Worker letters', output_dir=base / 'profile ü', white_bottom=True)
            approve_profile(profile.path)
            image = base / 'midgame.png'
            letter_board(MIDDLE).save(image)
            env = os.environ.copy()
            env['CHESS_2D_PROFILE'] = str(profile.path)
            before = os.environ.get('CHESS_2D_PROFILE')
            request = dict(path=str(image), request_id=103, white_bottom=True,
                           backend='lichess_2d.adapter:recognize', vision_path=str(root))
            worker = subprocess.run([sys.executable, str(app / 'image_recognition_worker.py'),
                                     '--request', json.dumps(request)], env=env, capture_output=True, timeout=20)
            self.assertEqual(worker.returncode, 0, worker.stderr.decode(errors='replace'))
            result = json.loads(worker.stdout)
            self.assertEqual(result['request_id'], 103)
            self.assertEqual(result['pieces'], parse_placement(MIDDLE))
            self.assertIn('Worker letters', result['message'])
            self.assertEqual(os.environ.get('CHESS_2D_PROFILE'), before)
