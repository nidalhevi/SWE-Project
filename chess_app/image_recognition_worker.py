"""One-shot recognition adapter, launched as a separate Python process.

The optional callable receives (image_path, *, white_bottom=bool).
It returns a dict with pieces/confidence in canonical square coordinates.
It must explicitly use None for known empty squares; missing squares are unknown.
No classifier is fabricated when the optional backend is absent.
"""
import argparse
from contextlib import redirect_stdout
import importlib
import json
from pathlib import Path
import re
import sys


def recognize(request):
    result = {'version': 1, 'request_id': request['request_id']}
    path = Path(request['path'])
    if not path.is_file():
        raise ValueError('Image file does not exist')
    backend = request.get('backend')
    if not backend:
        return dict(result, status='unavailable', pieces={}, confidence={}, message=
                    'No piece recognizer is configured. Enter the pieces manually, or configure your team’s recognition adapter.')
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*', backend):
        raise ValueError('Recognizer must have the form module:function')
    vision_path = request.get('vision_path')
    if vision_path:
        directory = Path(vision_path).resolve()
        if not directory.is_dir():
            raise ValueError('Vision import folder does not exist')
        sys.path.insert(0, str(directory))
    module, function = backend.split(':')
    with redirect_stdout(sys.stderr):
        predict = getattr(importlib.import_module(module), function)
        predictions = predict(str(path.resolve()), white_bottom=request['white_bottom'])
    if not isinstance(predictions, dict):
        raise ValueError('Recognizer must return a pieces/confidence mapping')
    # Backend cannot replace the worker's version, request ID, or status.
    return dict(result, status='ok', pieces=predictions.get('pieces', {}),
                confidence=predictions.get('confidence', {}), message=predictions.get('message', ''))


def main():
    # Windows worker logs and the GUI decoder use the same encoding.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    arguments = parser.parse_args()
    try:
        result = recognize(json.loads(arguments.request))
        print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)
        return 0
    except Exception as error:
        print(f'Recognition failed: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
