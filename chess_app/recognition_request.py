"""Validated version-1 recognition requests; no Qt or classifier dependency."""
from pathlib import Path


def validate_request(request):
    if not isinstance(request, dict):
        raise ValueError('Recognition request must be a JSON object')
    if type(request.get('request_id')) is not int or request['request_id'] < 0:
        raise ValueError('request_id must be a nonnegative integer')
    if type(request.get('white_bottom')) is not bool:
        raise ValueError('white_bottom must be true or false')
    if not isinstance(request.get('path'), str) or not request['path'].strip():
        raise ValueError('Image path must be a nonempty string')
    profile = request.get('profile_path')
    if profile is not None and (not isinstance(profile, str) or not profile.strip()):
        raise ValueError('profile_path must be a nonempty string or null')
    rect = request.get('board_rect')
    if rect is not None:
        if (not isinstance(rect, list) or len(rect) != 4 or any(type(v) is not int for v in rect)
                or min(rect[:2]) < 0 or min(rect[2:]) <= 0):
            raise ValueError('board_rect must be [left, top, width, height] in original-image pixels')
    return request


def build_request(image_path, *, request_id, white_bottom=True, backend=None,
                  vision_path=None, profile_path=None, board_rect=None):
    request = dict(path=str(image_path), request_id=request_id, white_bottom=white_bottom,
                   backend=backend, vision_path=str(vision_path) if vision_path is not None else None)
    if profile_path is not None:
        if not isinstance(profile_path, (str, Path)):
            raise ValueError('profile_path must be a path or explicit builtin token')
        request['profile_path'] = str(profile_path)
    if board_rect is not None:
        if not isinstance(board_rect, (tuple, list)):
            raise ValueError('board_rect must be a four-element list or tuple')
        request['board_rect'] = list(board_rect)
    return validate_request(request)
