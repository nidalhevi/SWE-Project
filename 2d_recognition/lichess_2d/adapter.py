"""Stage-8 worker entry point. Keep the established backend signature."""
import os
from .board_locator import load_image
from .recognizer import recognize_board


def recognize(image_path, *, white_bottom):
    """Input must contain exactly the 8×8 board; the GUI crop dialog prepares it."""
    profile = os.environ.get('CHESS_2D_PROFILE') or None
    with load_image(image_path) as image:
        return recognize_board(image, white_bottom=white_bottom, profile=profile)
