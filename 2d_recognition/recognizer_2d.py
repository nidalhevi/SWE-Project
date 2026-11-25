"""Run the stage-4 recognizer independently of the GUI and chess engines."""
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--profile', help='Reviewed profile folder/profile.json; omit for bundled Cburnett')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--white-bottom', action='store_true')
    group.add_argument('--black-bottom', action='store_true')
    crop = parser.add_mutually_exclusive_group()
    crop.add_argument('--rect', nargs=4, type=int, metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'))
    crop.add_argument('--select', action='store_true')
    parser.add_argument('--output', help='Prediction JSON path')
    parser.add_argument('--diagnostics', help='Directory for board, square sheet and per-square decisions')
    args = parser.parse_args(argv)
    try:
        from lichess_2d.board_locator_2d import BoardRect, load_image
        from lichess_2d.recognizer_2d import Recognizer2D, save_diagnostics
        recognizer = Recognizer2D(args.profile)
        with load_image(args.image) as image:
            rect = BoardRect(*args.rect) if args.rect else None
            if args.select:
                from check_board_extraction_2d import select_rectangle
                rect = select_rectangle(args.image, image, args.white_bottom)
                if rect is None:
                    print('Selection cancelled.')
                    return 0
            result, extraction = recognizer.predict(image, white_bottom=args.white_bottom, rect=rect)
            if args.diagnostics:
                save_diagnostics(result, extraction, args.diagnostics)
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
        print('Profile: ' + result['engine']['profile_name'])
        print(f'Unknown: {result["unknown_squares"]}/64; known empty: {result["known_empty_squares"]}/64')
        print('Placement: ' + (result['placement'] or '(incomplete; correct unknown squares)'))
        print('Template match quality is not a probability. No move-history metadata is inferred.')
        return 0
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
