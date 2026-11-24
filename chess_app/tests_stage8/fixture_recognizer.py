"""Deterministic test adapter. It does not recognize images."""
import time
from models import PositionSnapshot, STARTING_FEN
from image_import import SQUARES


def recognize(path, *, white_bottom):
    pieces = PositionSnapshot(STARTING_FEN).pieces
    return {'pieces': {square: pieces.get(square) for square in SQUARES},
            'confidence': {'e2': .65}, 'message': 'Test fixture output — review required.'}


def slow(path, *, white_bottom):
    time.sleep(120)  # Fault fixture: the client must cancel/timeout without waiting.
    return recognize(path, white_bottom=white_bottom)


def broken(path, *, white_bottom):
    raise RuntimeError('Fixture model failed')


def oversized(path, *, white_bottom):
    return {'pieces': {}, 'message': 'x' * 300000}
