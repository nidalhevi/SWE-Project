"""A confirmed screenshot rectangle -> normalized board -> 64 named images.

This module has no Qt or classifier dependency. All rectangles refer to the
decoded original image AFTER EXIF orientation correction. Right/bottom bounds
are exclusive. Flipping changes square names, never the pixels in a crop.
"""
from dataclasses import dataclass
import math
from pathlib import Path
from PIL import Image, ImageOps

NORMALIZED_BOARD_SIZE = 512
SQUARE_SIZE = NORMALIZED_BOARD_SIZE // 8


class RecognitionError(ValueError):
    """Input problem that can be shown directly in the image review window."""


@dataclass(frozen=True)
class BoardRect:
    left: int
    top: int
    width: int
    height: int

    @property
    def box(self):
        return self.left, self.top, self.left + self.width, self.top + self.height

    def checked(self, image_size):
        if any(type(value) is not int for value in (self.left, self.top, self.width, self.height)):
            raise RecognitionError('Board rectangle coordinates must be integers')
        if min(self.left, self.top) < 0 or min(self.width, self.height) < 128:
            raise RecognitionError('Select a complete board at least 128 pixels wide and high')
        if self.left + self.width > image_size[0] or self.top + self.height > image_size[1]:
            raise RecognitionError('The selected board extends outside the image')
        # One-pixel edge rounding is acceptable. Perspective distortion is not.
        if abs(self.width - self.height) > max(2, round(max(self.width, self.height) * .01)):
            raise RecognitionError('Select only the square 8×8 playing board, without outside labels or panels')
        return self


@dataclass(frozen=True)
class PreviewMapping:
    """Fit an original image into a letterboxed preview, in logical pixels.

    Qt supplies widget width/height in logical pixels even on a HiDPI display.
    Using the same fitted rectangle for painting and clicks avoids mixing those
    values with original-image or device-pixel coordinates.
    """
    image_size: tuple[int, int]
    viewport_size: tuple[float, float]

    def __post_init__(self):
        values = (*self.image_size, *self.viewport_size)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise RecognitionError('Image and preview dimensions must be positive')

    @property
    def geometry(self):
        width, height = self.image_size
        view_width, view_height = self.viewport_size
        scale = min(view_width / width, view_height / height)
        return ((view_width - width * scale) / 2, (view_height - height * scale) / 2,
                width * scale, height * scale)

    def to_source(self, x, y):
        left, top, width, height = self.geometry
        return (min(self.image_size[0], max(0., (x - left) * self.image_size[0] / width)),
                min(self.image_size[1], max(0., (y - top) * self.image_size[1] / height)))

    def to_preview(self, x, y):
        left, top, width, height = self.geometry
        return left + x * width / self.image_size[0], top + y * height / self.image_size[1]


@dataclass(frozen=True)
class SquareCrop:
    square: str
    row: int
    column: int
    box: tuple[int, int, int, int]  # Coordinates in the normalized board.
    image: Image.Image


@dataclass(frozen=True)
class BoardExtraction:
    source_size: tuple[int, int]
    rectangle: BoardRect
    white_bottom: bool
    board: Image.Image
    squares: tuple[SquareCrop, ...]  # Visual order: top-left through bottom-right.

    @property
    def by_square(self):
        """Canonical-name lookup; images retain their original upright contents."""
        return {crop.square: crop.image for crop in self.squares}


def load_image(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
        raise RecognitionError('Choose a readable image smaller than 50 MiB')
    try:
        with Image.open(path) as image:
            if image.width * image.height > 60_000_000:
                raise RecognitionError('Image exceeds 60 megapixels')
            return ImageOps.exif_transpose(image).convert('RGB')
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise RecognitionError('Cannot decode this image; use PNG or JPEG') from error


def extract_board(image, rect=None):
    """Extract only the selected board, preserving its original resolution."""
    rect = (rect or BoardRect(0, 0, *image.size)).checked(image.size)
    return image.crop(rect.box).convert('RGB')


def _checked_board_size(board_size):
    if type(board_size) is not int or not 128 <= board_size <= 2048 or board_size % 8:
        raise RecognitionError('Normalized board size must be a multiple of 8 from 128 to 2048')


def normalize_board(image, rect=None, *, board_size=NORMALIZED_BOARD_SIZE):
    """Crop FIRST, then resize ONCE to an exact square (default 512×512)."""
    _checked_board_size(board_size)
    board = extract_board(image, rect)
    if board.size == (board_size, board_size):
        return board
    return board.resize((board_size, board_size), Image.Resampling.LANCZOS)


def square_name(row, column, white_bottom=True):
    if type(white_bottom) is not bool:
        raise RecognitionError('white_bottom must be True or False')
    if type(row) is not int or type(column) is not int or not (0 <= row < 8 and 0 <= column < 8):
        raise RecognitionError('Grid coordinates must be integers from 0 to 7')
    if white_bottom:
        return 'abcdefgh'[column] + str(8 - row)
    return 'hgfedcba'[column] + str(row + 1)


def split_normalized_board(board, *, white_bottom):
    """Return 64 independent cells with no further resizing or pixel rotation."""
    _checked_board_size(board.width)
    if board.width != board.height:
        raise RecognitionError('Normalize the board to a square before splitting it')
    size = board.width // 8
    cells = []
    for row in range(8):
        for column in range(8):
            box = (column * size, row * size, (column + 1) * size, (row + 1) * size)
            cells.append(SquareCrop(square_name(row, column, white_bottom), row, column,
                                    box, board.crop(box)))
    return tuple(cells)


def extract_position(image, *, rect=None, white_bottom, board_size=NORMALIZED_BOARD_SIZE):
    rect = (rect or BoardRect(0, 0, *image.size)).checked(image.size)
    board = normalize_board(image, rect, board_size=board_size)
    cells = split_normalized_board(board, white_bottom=white_bottom)
    return BoardExtraction(image.size, rect, white_bottom, board, cells)


def square_crops(board, white_bottom=True, size=SQUARE_SIZE):
    """Compatibility iterator used by the existing Cburnett classifier.

    Normalizing the whole board gives a single reproducible grid. The classifier
    keeps receiving (canonical square name, RGB image) pairs of the same size.
    """
    if type(size) is not int:
        raise RecognitionError('Square size must be an integer')
    normalized = normalize_board(board, board_size=size * 8)
    for cell in split_normalized_board(normalized, white_bottom=white_bottom):
        yield cell.square, cell.image


def grid_segments(rect):
    """18 source-coordinate lines: 9 vertical + 9 horizontal, including edges."""
    lines = []
    for index in range(9):
        x = rect.left + rect.width * index / 8
        y = rect.top + rect.height * index / 8
        lines.append((x, rect.top, x, rect.top + rect.height))
        lines.append((rect.left, y, rect.left + rect.width, y))
    return tuple(lines)
