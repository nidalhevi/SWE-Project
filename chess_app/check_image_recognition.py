"""Smoke-test the actual trained model with one image, without Qt or the C binary."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--vision-path', default=str(Path(__file__).resolve().parent.parent / 'vision'))
    orientation = parser.add_mutually_exclusive_group(required=True)
    orientation.add_argument('--white-bottom', action='store_true')
    orientation.add_argument('--black-bottom', action='store_true')
    parser.add_argument('--output', help='Optional JSON predictions output; this is not a complete FEN or PGN')
    parser.add_argument('--board-crop', action='store_true', help='Input is already exactly the square 8x8 board; bypass detection')
    parser.add_argument('--diagnostics', help='Save detected grid, warped input, square crops, and predictions into this folder')
    args = parser.parse_args()
    root = Path(args.vision_path).resolve()
    required = [root / 'chessvision/classifier.py', root / 'weights/square_net.pt', root / 'weights/corner_net.pt']
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print('ERROR: updated vision code/weights missing:\n' + '\n'.join(missing), file=sys.stderr)
        return 1
    sys.path.insert(0, str(root))
    try:
        from chessvision_adapter import recognize, recognize_board_crop, diagnose_image
        from image_import import ImageDraft, parse_recognition
        print('Loading trained models and recognizing the image...', flush=True)
        if args.diagnostics:
            predictions = diagnose_image(args.image, white_bottom=args.white_bottom,
                                         directory=args.diagnostics, board_crop=args.board_crop)
        else:
            predict = recognize_board_crop if args.board_crop else recognize
            predictions = predict(args.image, white_bottom=args.white_bottom)
        document = dict(version=1, request_id=1, status='ok', **predictions)
        encoded = json.dumps(document, allow_nan=False).encode('utf-8')
        result = parse_recognition(encoded, 1)
        draft = ImageDraft()
        draft.apply(result)
        print(f'Inference completed: {len(result.squares)} square records (accuracy not validated)')
        print(f'Unknown squares: {len(draft.unknown_squares)}; low confidence: {len(draft.uncertain_squares)}')
        if not draft.unknown_squares:
            print('Piece-placement field (review required): ' + draft.preview().fen.split()[0])
        else:
            print('Unknown squares: ' + ' '.join(draft.unknown_squares))
        print('This checks the connection, not whether every prediction is correct.')
        print(predictions.get('message', ''))
        if args.diagnostics:
            print('Diagnostics saved to: ' + str(Path(args.diagnostics).resolve()))
        if args.output:
            Path(args.output).write_bytes(encoded + b'\n')
        return 0
    except Exception as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
