from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image, ImageDraw
from lichess_2d.board_locator import BoardRect, extract_board, load_image, square_name
from lichess_2d.notation import parse_placement, placement_of
from lichess_2d.recognizer import classify_square, recognize_board
from tests_lichess2d.fixtures import START, MIDDLE, END, PROMOTIONS, render


class RecognitionTests(unittest.TestCase):
    def assert_board(self, image, placement, white_bottom=True, rect=None):
        result = recognize_board(image, white_bottom=white_bottom, rect=rect)
        self.assertEqual(result['pieces'], parse_placement(placement))
        self.assertEqual(placement_of(result['pieces']), placement)
        self.assertEqual(len(result['confidence']), 64)
        self.assertTrue(all(0 <= q <= 1 for q in result['confidence'].values()))
        return result

    def test_starting_position(self):
        self.assert_board(render(), START)

    def test_midgame_piece_colors_on_both_square_colors(self):
        self.assert_board(render(MIDDLE), MIDDLE)

    def test_endgame_sparse_board(self):
        self.assert_board(render(END), END)

    def test_promoted_pieces_are_not_limited_to_starting_counts(self):
        self.assert_board(render(PROMOTIONS), PROMOTIONS)

    def test_flipped_board_keeps_icons_upright(self):
        self.assert_board(render(MIDDLE, white_bottom=False), MIDDLE, False)

    def test_multiple_resolutions_and_fractional_cell_boundaries(self):
        for pixels in (256, 511, 777):
            with self.subTest(pixels=pixels):
                image = render(END, cell=100).resize((pixels, pixels), Image.Resampling.BICUBIC)
                self.assert_board(image, END)

    def test_jpeg_resampling(self):
        self.assert_board(render(MIDDLE, cell=53, jpeg=True), MIDDLE)

    def test_last_move_uniform_highlights(self):
        self.assert_board(render(MIDDLE, highlights=('f4', 'e3')), MIDDLE)

    def test_inside_board_coordinate_labels(self):
        self.assert_board(render(MIDDLE, cell=64, coordinates=True), MIDDLE)

    def test_explicit_crop_excludes_player_panels(self):
        board = render(END, cell=48)
        screenshot = Image.new('RGB', (900, 700), '#282828')
        screenshot.paste(board, (173, 85))
        self.assert_board(screenshot, END, rect=BoardRect(173, 85, 384, 384))

    def test_unsupported_shape_is_unknown_not_empty(self):
        tile = Image.new('RGB', (64, 64), '#f0d9b5')
        ImageDraw.Draw(tile).rectangle((10, 15, 50, 50), fill='#2856d4')
        self.assertEqual(classify_square(tile)[0], '?')

    def test_obscuring_arrow_is_unknown(self):
        board = render(END, cell=64)
        # a8 is empty; a thick opaque arrow must not be accepted as empty.
        tile = board.crop((0, 0, 64, 64))
        draw = ImageDraw.Draw(tile)
        draw.line((10, 53, 48, 13), fill='green', width=12)
        self.assertEqual(classify_square(tile)[0], '?')

    def test_random_texture_is_not_an_empty_square(self):
        tile = Image.fromarray(np.random.default_rng(2026).integers(0, 256, (64, 64, 3), dtype=np.uint8))
        self.assertEqual(classify_square(tile)[0], '?')


class GeometryAndInputTests(unittest.TestCase):
    def test_canonical_coordinates_both_orientations(self):
        self.assertEqual(square_name(0, 0, True), 'a8')
        self.assertEqual(square_name(7, 7, True), 'h1')
        self.assertEqual(square_name(0, 0, False), 'h1')
        self.assertEqual(square_name(7, 7, False), 'a8')
        self.assertEqual(len({square_name(r, c, False) for r in range(8) for c in range(8)}), 64)

    def test_full_screenshot_requires_crop(self):
        with self.assertRaisesRegex(ValueError, 'square'):
            extract_board(Image.new('RGB', (800, 600)))

    def test_invalid_rectangles_are_rejected(self):
        for rectangle in (BoardRect(-1, 0, 512, 512), BoardRect(0, 0, 64, 64),
                          BoardRect(1, 0, 512, 512), BoardRect(0, 0, 400, 500),
                          BoardRect(0., 0, 512, 512)):
            with self.subTest(rectangle=rectangle), self.assertRaises(ValueError):
                rectangle.checked((512, 512))

    def test_unicode_path_and_exif_orientation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Ekran Görüntüleri ü.png'
            image = Image.new('RGB', (200, 300), 'white')
            exif = image.getexif()
            exif[274] = 6
            image.save(path, exif=exif)
            self.assertEqual(load_image(path).size, (300, 200))

    def test_invalid_image_readable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.png'
            path.write_text('not an image')
            with self.assertRaisesRegex(ValueError, 'decode'):
                load_image(path)

    def test_unknown_placement_cannot_be_exported_as_complete(self):
        pieces = parse_placement(START)
        pieces['a1'] = '?'
        self.assertIsNone(placement_of(pieces))

    def test_fen_invalid_rank_lengths(self):
        for value in ('8/8', '88/8/8/8/8/8/8/8', '7/8/8/8/8/8/8/8', 'x7/8/8/8/8/8/8/8'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_placement(value)


if __name__ == '__main__':
    unittest.main()
