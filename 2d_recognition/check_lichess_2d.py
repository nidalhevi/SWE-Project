"""Recognize one Cburnett board image without starting the GUI or referee."""
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    orientation = parser.add_mutually_exclusive_group(required=True)
    orientation.add_argument('--white-bottom', action='store_true')
    orientation.add_argument('--black-bottom', action='store_true')
    parser.add_argument('--rect', nargs=4, type=int, metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'),
                        help='Original image pixels after EXIF rotation; omit for an exactly cropped board')
    parser.add_argument('--output', help='Optional JSON output path')
    parser.add_argument('--profile', help='Reviewed profile folder or profile.json; omit for bundled Cburnett')
    parser.add_argument('--diagnostics', help='Optional directory for board crop and square contact sheet')
    args = parser.parse_args(argv)
    try:
        from lichess_2d.board_locator import BoardRect, load_image, extract_board, square_crops
        from lichess_2d.recognizer import recognize_board
        from lichess_2d.notation import placement_of
        from PIL import Image, ImageDraw
        rect = BoardRect(*args.rect) if args.rect else None
        with load_image(args.image) as image:
            result = recognize_board(image, white_bottom=args.white_bottom, rect=rect, profile=args.profile)
            result['placement'] = placement_of(result['pieces'])
            if args.diagnostics:
                directory = Path(args.diagnostics)
                directory.mkdir(parents=True, exist_ok=True)
                board = extract_board(image, rect)
                board.save(directory / '01_board.png')
                sheet = Image.new('RGB', (8 * 96, 8 * 92), '#dddddd')
                draw = ImageDraw.Draw(sheet)
                for i, (square, crop) in enumerate(square_crops(board, args.white_bottom)):
                    x, y = i % 8 * 96, i // 8 * 92
                    sheet.paste(crop, (x + 16, y))
                    piece = result['pieces'][square]
                    draw.text((x + 2, y + 65), f'{square}: {piece or "empty"}', fill='black')
                    draw.text((x + 2, y + 77), f'{result["confidence"][square]:.2f}', fill='black')
                sheet.save(directory / '02_squares.png')
                (directory / '03_predictions.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(result['message'])
        print('Piece placement: ' + (result['placement'] or '(incomplete; correct unknown squares first)'))
        print('This is not a complete FEN: side to move, castling, en passant and counters require review.')
        return 0
    except ImportError as error:
        print(f'Missing dependency: {error}. Install: python -m pip install numpy pillow', file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
