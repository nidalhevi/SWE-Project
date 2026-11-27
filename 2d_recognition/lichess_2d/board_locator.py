"""Compatibility imports; the extraction implementation is board_locator_2d.py.

Keep existing classifier/adapter/CLI imports working while exposing the new
structured 512×512 board and 64-square extraction API.
"""
from .board_locator_2d import (
    BoardExtraction, BoardRect, NORMALIZED_BOARD_SIZE, PreviewMapping,
    RecognitionError, SQUARE_SIZE, SquareCrop, extract_board, extract_position,
    grid_segments, load_image, normalize_board, split_normalized_board,
    square_crops, square_name,
)
