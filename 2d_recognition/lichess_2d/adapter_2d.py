"""Stage-4 recognizer through the existing image worker contract.

The profile is always explicit. None is unconfigured, not a builtin fallback.
Only the user's explicit builtin:cburnett selection uses the bundled artwork.
"""
from .board_locator_2d import BoardRect, RecognitionError, load_image
from .recognizer_2d import Recognizer2D

BUILTIN = 'builtin:cburnett'


def recognize(image_path, *, white_bottom, profile_path=None, board_rect=None):
    if profile_path is None:
        raise RecognitionError('Choose a matching theme profile, calibrate a profile, or use manual correction.')
    if board_rect is not None:
        if (not isinstance(board_rect, (tuple, list)) or len(board_rect) != 4
                or any(type(v) is not int for v in board_rect)):
            raise RecognitionError('board_rect must contain four original-image pixel coordinates')
        rect = BoardRect(*board_rect)
    else:
        rect = None
    model = Recognizer2D(None if profile_path == BUILTIN else profile_path)
    with load_image(image_path) as image:
        result, _ = model.predict(image, white_bottom=white_bottom, rect=rect)
    pieces = result['pieces']
    name = result['engine']['profile_name']
    message = (f'{name}: {sum(p not in (None, "?") for p in pieces.values())} pieces, '
               f'{result["known_empty_squares"]} empty, {result["unknown_squares"]} unknown. '
               'Review the board and position details. Match quality is not a probability.')
    if result['unknown_squares'] or list(pieces.values()).count('K') != 1 or list(pieces.values()).count('k') != 1:
        message += ' Check the profile and crop; calibration or manual correction is available.'
    if result['overlay_squares']:
        message += (' Possible colored overlays on ' + ', '.join(sorted(result['overlay_squares'])) +
                    ': left unknown. Prefer an image without arrows, or correct these squares manually.')
    return dict(pieces=pieces, confidence=result['match_quality'], message=message)
