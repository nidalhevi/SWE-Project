"""Pixel and geometry assertions independent of the classifier and chess assets."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image, ImageChops, ImageDraw
from lichess_2d.board_locator_2d import (
    BoardRect, PreviewMapping, extract_board, extract_position, grid_segments,
    load_image, normalize_board, split_normalized_board, square_name,
)


def marked_board():
    board = Image.new('RGB', (512, 512))
    for row in range(8):
        for column in range(8):
            color = (20 + row * 25, 20 + column * 25, 80)
            tile = Image.new('RGB', (64, 64), color)
            # Asymmetric marks prove that no reflection/rotation was applied.
            ImageDraw.Draw(tile).rectangle((4, 5, 15, 10), fill='red')
            ImageDraw.Draw(tile).rectangle((35, 46, 58, 60), fill='blue')
            board.paste(tile, (column * 64, row * 64))
    return board


class ExtractionTests(unittest.TestCase):
    def test_crop_excludes_panels_and_retains_exact_edges(self):
        source = Image.new('RGB', (901, 733), 'magenta')
        board = marked_board()
        source.paste(board, (117, 83))
        crop = extract_board(source, BoardRect(117, 83, 512, 512))
        self.assertIsNone(ImageChops.difference(crop, board).getbbox())
        self.assertNotEqual(crop.getpixel((0, 0)), (255, 0, 255))

    def test_exactly_64_named_64_pixel_cells(self):
        result = extract_position(marked_board(), white_bottom=True)
        self.assertEqual(result.board.size, (512, 512))
        self.assertEqual(len(result.squares), 64)
        self.assertEqual(set(result.by_square), {f'{f}{r}' for f in 'abcdefgh' for r in range(1, 9)})
        self.assertTrue(all(cell.image.size == (64, 64) for cell in result.squares))
        self.assertEqual(result.squares[0].square, 'a8')
        self.assertEqual(result.squares[-1].square, 'h1')

    def test_normalization_for_odd_board_sizes(self):
        for size in (255, 511, 777, 1001):
            with self.subTest(size=size):
                image = marked_board().resize((size, size))
                result = extract_position(image, white_bottom=True)
                self.assertEqual(result.board.size, (512, 512))
                self.assertEqual(len(result.squares), 64)
                self.assertTrue(all(cell.image.size == (64, 64) for cell in result.squares))

    def test_cells_partition_board_without_gaps_or_overlap(self):
        result = extract_position(marked_board().resize((777, 777)), white_bottom=True)
        stitched = Image.new('RGB', (512, 512))
        coverage = Image.new('L', (512, 512), 0)
        for cell in result.squares:
            stitched.paste(cell.image, cell.box[:2])
            x1, y1, x2, y2 = cell.box
            for y in range(y1, y2):
                for x in range(x1, x2):
                    coverage.putpixel((x, y), coverage.getpixel((x, y)) + 1)
        self.assertEqual(coverage.getextrema(), (1, 1))
        self.assertIsNone(ImageChops.difference(stitched, result.board).getbbox())

    def test_flipped_names_reverse_but_image_pixels_stay_upright(self):
        source = marked_board()
        white = extract_position(source, white_bottom=True)
        black = extract_position(source, white_bottom=False)
        self.assertEqual(black.squares[0].square, 'h1')
        self.assertEqual(black.squares[-1].square, 'a8')
        for a, b in zip(white.squares, black.squares):
            self.assertEqual(a.image.tobytes(), b.image.tobytes())
            self.assertEqual(b.image.getpixel((6, 6)), (255, 0, 0))
            self.assertEqual(b.image.getpixel((40, 50)), (0, 0, 255))

    def test_square_names_are_bijective_in_both_orientations(self):
        for orientation in (True, False):
            self.assertEqual(len({square_name(r, c, orientation) for r in range(8) for c in range(8)}), 64)
        with self.assertRaises(ValueError):
            square_name(0, 0, 'black')

    def test_invalid_rectangles(self):
        for rectangle in (BoardRect(-1, 0, 512, 512), BoardRect(100, 0, 512, 512),
                          BoardRect(0, 0, 64, 64), BoardRect(0, 0, 512, 400),
                          BoardRect(False, 0, 512, 512)):
            with self.subTest(rectangle=rectangle), self.assertRaises(ValueError):
                extract_position(marked_board(), rect=rectangle, white_bottom=True)

    def test_invalid_normalized_dimensions(self):
        for size in (0, 127, 513, 4096, 512., True):
            with self.subTest(size=size), self.assertRaises(ValueError):
                normalize_board(marked_board(), board_size=size)
        with self.assertRaises(ValueError):
            split_normalized_board(Image.new('RGB', (512, 400)), white_bottom=True)

    def test_cells_are_independent_of_board_pixels(self):
        result = extract_position(marked_board(), white_bottom=True)
        original = result.board.getpixel((0, 0))
        result.by_square['a8'].putpixel((0, 0), (255, 255, 255))
        self.assertEqual(result.board.getpixel((0, 0)), original)

    def test_exif_correction_precedes_coordinate_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Ekran Görüntüsü.png'
            image = Image.new('RGB', (300, 200), 'white')
            exif = image.getexif()
            exif[274] = 6
            image.save(path, exif=exif)
            self.assertEqual(load_image(path).size, (200, 300))

    def test_legacy_import_is_same_rectangle_type(self):
        from lichess_2d.board_locator import BoardRect as LegacyRect
        self.assertIs(LegacyRect, BoardRect)


class PreviewTests(unittest.TestCase):
    def test_roundtrip_with_horizontal_and_vertical_letterboxing(self):
        for viewport in ((1000, 1000), (800, 200), (333, 777)):
            mapping = PreviewMapping((2000, 1200), viewport)
            for source in ((0, 0), (2000, 1200), (777, 444)):
                back = mapping.to_source(*mapping.to_preview(*source))
                self.assertAlmostEqual(back[0], source[0])
                self.assertAlmostEqual(back[1], source[1])

    def test_preview_padding_clamps_to_image(self):
        mapping = PreviewMapping((2000, 1000), (1000, 1000))
        self.assertEqual(mapping.geometry, (0, 250, 1000, 500))
        self.assertEqual(mapping.to_source(-20, 0), (0, 0))
        self.assertEqual(mapping.to_source(2000, 2000), (2000, 1000))

    def test_invalid_preview_dimensions(self):
        with self.assertRaises(ValueError):
            PreviewMapping((512, 512), (0, 600))

    def test_grid_uses_nine_lines_in_each_direction(self):
        lines = grid_segments(BoardRect(100, 80, 512, 512))
        self.assertEqual(len(lines), 18)
        self.assertEqual(lines[0], (100, 80, 100, 592))
        self.assertEqual(lines[-1], (100, 592, 612, 592))
        self.assertEqual(len({line[0] for line in lines[::2]}), 9)


class ExportTests(unittest.TestCase):
    def test_cli_saves_exactly_64_upright_images_with_flipped_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source ü.png'
            image = Image.new('RGB', (800, 700), 'magenta')
            board = marked_board()
            image.paste(board, (117, 83))
            image.save(source)
            output = root / 'output'
            cli = Path(__file__).resolve().parents[1] / 'check_board_extraction_2d.py'
            process = subprocess.run([sys.executable, str(cli), '--image', str(source),
                                      '--rect', '117', '83', '512', '512', '--black-bottom',
                                      '--output', str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(len(list((output / 'squares').glob('*.png'))), 64)
            with Image.open(output / 'squares/h1.png') as tile:
                self.assertEqual(tile.tobytes(), board.crop((0, 0, 64, 64)).tobytes())
            metadata = json.loads((output / 'extraction.json').read_text())
            self.assertEqual(metadata['normalized_size'], [512, 512])
            self.assertEqual(metadata['squares'][0]['square'], 'h1')
            self.assertTrue((output / 'contact_sheet.png').is_file())
            self.assertTrue((output / 'source_grid.png').is_file())
