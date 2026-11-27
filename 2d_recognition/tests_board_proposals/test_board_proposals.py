"""Board localization regressions; no Qt, C referee or Stockfish required.

Run from the repository root:
    python -m unittest discover -s 2d_recognition/tests_board_proposals -v
Generated images exercise independent geometry/colour failure cases. They are
not evidence of accuracy on every website or screenshot theme.
"""
from io import BytesIO
from pathlib import Path
import json
import subprocess
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lichess_2d.board_proposals import (  # noqa: E402
    BoardProposal, parse_proposals, proposal_document, propose_boards,
)
from lichess_2d.board_locator_2d import BoardRect, RecognitionError  # noqa: E402


def checkerboard(side=512, *, n=8, colors=('#eeeed2', '#769656'), pieces=False):
    image = Image.new('RGB', (side, side))
    draw = ImageDraw.Draw(image)
    for r in range(n):
        for c in range(n):
            box = (round(c*side/n), round(r*side/n), round((c+1)*side/n)-1, round((r+1)*side/n)-1)
            draw.rectangle(box, fill=colors[(r+c) % 2])
            if pieces and (r in (0, 1, n-2, n-1) or (r+c) % 5 == 0):
                x, y, pitch = c*side/n, r*side/n, side/n
                draw.ellipse((x+.25*pitch, y+.16*pitch, x+.75*pitch, y+.84*pitch),
                             fill='#171717' if r < n/2 else '#eeeeee', outline='#555555')
    return image


def on_canvas(board, size=(900, 700), origin=(117, 83)):
    image = Image.new('RGB', size, '#252525')
    image.paste(board, origin)
    return image


class BoardProposalTests(unittest.TestCase):
    def assert_detected(self, image, expected, tolerance=2):
        proposals = propose_boards(image)
        found = any(max(abs(a-b) for a, b in zip(
            (p.rectangle.left, p.rectangle.top, p.rectangle.width, p.rectangle.height), expected)) <= tolerance
                    for p in proposals)
        self.assertTrue(found, (expected, proposals))
        for p in proposals:
            p.rectangle.checked(image.size)
            self.assertTrue(0 <= p.grid_fit <= 1)
        return proposals

    def test_clean_board_at_image_edges(self):
        self.assert_detected(checkerboard(), (0, 0, 512, 512))

    def test_minimum_size_board(self):
        self.assert_detected(checkerboard(128), (0, 0, 128, 128))

    def test_unchanged_board_inside_large_desktop(self):
        self.assert_detected(on_canvas(checkerboard(), (3840, 2160)), (117, 83, 512, 512))

    def test_small_board_inside_large_desktop(self):
        self.assert_detected(on_canvas(checkerboard(200), (1920, 1080)), (117, 83, 200, 200))

    def test_fractional_cell_pitch_gets_original_boundaries(self):
        self.assert_detected(on_canvas(checkerboard(517)), (117, 83, 517, 517), tolerance=1)

    def test_fixed_quantization_bin_does_not_merge_board_colors(self):
        self.assert_detected(checkerboard(colors=('#808080', '#9f9f9f')), (0, 0, 512, 512))

    def test_low_contrast_and_colored_boards(self):
        for colors in (('#a0a0a0', '#aeaeae'), ('#cb8cb8', '#738fb7'), ('#f0d9b5', '#b58863')):
            with self.subTest(colors=colors):
                self.assert_detected(checkerboard(colors=colors), (0, 0, 512, 512))

    def test_piece_like_foreground_and_coordinates(self):
        b = checkerboard(517, pieces=True)
        draw = ImageDraw.Draw(b)
        for i in range(8):
            draw.text((2, round(i*517/8)+2), str(8-i), fill='#503020')
            draw.text((round((i+1)*517/8)-10, 504), 'abcdefgh'[i], fill='#503020')
        self.assert_detected(on_canvas(b), (117, 83, 517, 517))

    def test_jpeg_and_browser_resampling(self):
        b = checkerboard(512, pieces=True).resize((517, 517), Image.Resampling.LANCZOS)
        image = on_canvas(b)
        stream = BytesIO()
        image.save(stream, format='JPEG', quality=72)
        stream.seek(0)
        with Image.open(stream) as jpeg:
            self.assert_detected(jpeg, (117, 83, 517, 517), tolerance=3)

    def test_highlights_and_arrow_on_some_squares(self):
        b = checkerboard(pieces=True)
        draw = ImageDraw.Draw(b)
        draw.rectangle((192, 192, 255, 255), fill='#cdd26a')
        draw.rectangle((192, 256, 255, 319), fill='#aaa23a')
        draw.line((96, 352, 280, 152), fill='#00af24', width=9)
        self.assert_detected(on_canvas(b), (117, 83, 512, 512))

    def test_two_separate_boards(self):
        b = checkerboard(320, pieces=True)
        image = on_canvas(b, (750, 390), (15, 30))
        image.paste(b.transpose(Image.Transpose.ROTATE_180), (390, 30))
        p = self.assert_detected(image, (15, 30, 320, 320))
        self.assert_detected(image, (390, 30, 320, 320))
        self.assertEqual(len(p), 2)
        self.assertEqual(len(propose_boards(image, limit=1)), 1)

    def test_reject_internal_crop_of_larger_checkerboards(self):
        for n in (9, 10, 12):
            with self.subTest(n=n):
                self.assertEqual(propose_boards(checkerboard(n*64, n=n)), ())

    def test_reject_incomplete_board(self):
        self.assertEqual(propose_boards(checkerboard().crop((0, 0, 512, 480))), ())

    def test_reject_blank_striped_and_noisy_panels(self):
        striped = Image.new('RGB', (900, 600), '#eeeeee')
        draw = ImageDraw.Draw(striped)
        for i in range(8):
            draw.rectangle((10, i*70+5, 850, i*70+20), fill='#444444')
        noise = Image.fromarray(np.random.default_rng(42).integers(0, 256, (400, 600, 3), dtype=np.uint8))
        for image in (striped, noise, Image.new('RGB', (512, 512), '#808080')):
            self.assertEqual(propose_boards(image), ())

    def test_reject_unsupported_dimensions_and_limits(self):
        self.assertEqual(propose_boards(checkerboard(120)), ())
        # Avoid allocating a 60-million-pixel image just to test the size guard.
        class Oversized:
            size = (10000, 10000)
            width, height = size
        self.assertEqual(propose_boards(Oversized()), ())
        for limit in (True, 0, 6, 1.5):
            with self.assertRaises(RecognitionError):
                propose_boards(checkerboard(128), limit=limit)

    def test_existing_generated_fixture_geometry(self):
        folder = ROOT.parent / 'chess_app/tests_stage2d8/fixtures'
        cases = json.loads((folder/'cases.json').read_text())['cases']
        for case in cases:
            with self.subTest(case=case['id']), Image.open(folder/case['image']) as image:
                self.assert_detected(image, case['rect'], tolerance=3)

    def test_protocol_roundtrip_and_stale_request_rejection(self):
        document = proposal_document((BoardProposal(BoardRect(10, 20, 256, 256), .9),), 7)
        parsed = parse_proposals(json.dumps(document), 7, (600, 600))
        self.assertEqual(parsed.proposals[0].rectangle, BoardRect(10, 20, 256, 256))
        with self.assertRaises(RecognitionError):
            parse_proposals(json.dumps(document), 8, (600, 600))

    def test_actual_worker_process(self):
        path = ROOT.parent/'chess_app/tests_stage2d8/fixtures/middle-panels.png'
        result = subprocess.run([sys.executable, str(ROOT/'lichess_2d/proposal_worker.py'), '--request',
                                 json.dumps(dict(request_id=13, path=str(path)))],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = parse_proposals(result.stdout, 13, (818, 738))
        self.assertTrue(parsed.proposals)


if __name__ == '__main__':
    unittest.main()
