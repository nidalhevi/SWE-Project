"""Process fixtures only; these outputs make no image-recognition claim."""
import time


def options(path, *, white_bottom, profile_path, board_rect):
    assert profile_path == 'test-profile'
    assert board_rect == [1, 2, 128, 128]
    return {'pieces': {'e1': 'K', 'e8': 'k'}, 'message': 'Options reached the backend'}


def slow(path, *, white_bottom, profile_path=None, board_rect=None):
    time.sleep(2)
    return {'pieces': {'e1': 'K'}}
