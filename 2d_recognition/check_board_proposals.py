"""Print board suggestions without opening Qt or running piece recognition.

Examples (from the repository root):
  python 2d_recognition/check_board_proposals.py --image screenshot.png
  python 2d_recognition/check_board_proposals.py --image screenshot.png --expect 117 83 568 568
The second form exits with status 1 when the expected board is not suggested.
All coordinates refer to the EXIF-corrected original image, not a preview.
"""
import argparse
import json
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--limit', type=int, choices=range(1, 6), default=3)
    parser.add_argument('--expect', type=int, nargs=4, action='append',
                        metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'))
    parser.add_argument('--tolerance', type=int, default=3)
    args = parser.parse_args(argv)
    if args.tolerance < 0:
        parser.error('--tolerance must be nonnegative')
    try:
        from lichess_2d.board_locator_2d import load_image
        from lichess_2d.board_proposals import propose_boards, proposal_document
        started = time.perf_counter()
        with load_image(args.image) as image:
            proposals = propose_boards(image, limit=args.limit)
        document = proposal_document(proposals, request_id=0)
        document['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        document['image'] = args.image
        if args.expect:
            document['expected_boards'] = [dict(rect=expected, found=any(
                max(abs(a-b) for a, b in zip(p['rect'], expected)) <= args.tolerance
                for p in document['proposals'])) for expected in args.expect]
        print(json.dumps(document, indent=2, allow_nan=False))
        return 0 if not args.expect or all(e['found'] for e in document['expected_boards']) else 1
    except (ImportError, OSError, ValueError) as error:
        print('Board search failed: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
