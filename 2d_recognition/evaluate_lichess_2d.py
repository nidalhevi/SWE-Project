"""Measure screenshot recognition against a JSON manifest of known positions.

Example entry: {"image":"test.png", "fen":"4k3/8/8/8/8/8/8/4K3",
                "white_bottom":true, "rect":[10,20,512,512]}
Paths are relative to the manifest. Omit rect only for an exactly cropped board.
Use actual screenshots for acceptance; generated boards only test mechanics.
"""
import argparse
import json
from pathlib import Path
import sys


def evaluate(manifest_path):
    from lichess_2d.board_locator import BoardRect, load_image
    from lichess_2d.recognizer import recognize_board
    from lichess_2d.notation import parse_placement
    path = Path(manifest_path)
    cases = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(cases, list) or not cases:
        raise ValueError('Manifest must contain a nonempty JSON list')
    totals = dict(boards=len(cases), exact_boards=0, squares=0, correct=0,
                  occupied=0, occupied_correct=0, empty=0, empty_correct=0,
                  accepted=0, accepted_correct=0, unknown=0, errors=0)
    results = []
    for case in cases:
        truth = parse_placement(case['fen'])
        if type(case.get('white_bottom')) is not bool:
            raise ValueError('Each case must specify white_bottom as true or false')
        image_path = path.parent / case['image']
        error = None
        try:
            rect = BoardRect(*case['rect']) if 'rect' in case else None
            with load_image(image_path) as image:
                prediction = recognize_board(image, white_bottom=case['white_bottom'], rect=rect)['pieces']
        except (OSError, ValueError) as problem:
            prediction = {square: '?' for square in truth}
            totals['errors'] += 1
            error = str(problem)
        wrong = []
        for square, target in truth.items():
            guess = prediction[square]
            correct = guess == target
            occupied = target is not None
            totals['squares'] += 1
            totals['correct'] += int(correct)
            kind = 'occupied' if occupied else 'empty'
            totals[kind] += 1
            totals[kind + '_correct'] += int(correct)
            if guess == '?':
                totals['unknown'] += 1
            else:
                totals['accepted'] += 1
                totals['accepted_correct'] += int(correct)
            if not correct:
                wrong.append(dict(square=square, expected=target, predicted=guess))
        totals['exact_boards'] += int(not wrong)
        results.append(dict(image=case['image'], error=error, wrong=wrong))
    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None
    metrics = dict(board_accuracy=ratio(totals['exact_boards'], totals['boards']),
                   square_accuracy=ratio(totals['correct'], totals['squares']),
                   occupied_accuracy=ratio(totals['occupied_correct'], totals['occupied']),
                   empty_accuracy=ratio(totals['empty_correct'], totals['empty']),
                   coverage=ratio(totals['accepted'], totals['squares']),
                   accepted_accuracy=ratio(totals['accepted_correct'], totals['accepted']),
                   always_empty_baseline=ratio(totals['empty'], totals['squares']))
    return dict(manifest=str(path.resolve()), totals=totals, metrics=metrics, results=results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output')
    parser.add_argument('--min-board-accuracy', type=float, default=None,
                        help='Optional acceptance gate, e.g. 0.95; failure exits 1')
    args = parser.parse_args(argv)
    if args.min_board_accuracy is not None and not 0 <= args.min_board_accuracy <= 1:
        parser.error('--min-board-accuracy must be between 0 and 1')
    try:
        report = evaluate(args.manifest)
        if args.output:
            Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
        for name, value in report['metrics'].items():
            print(f'{name}: ' + (f'{value:.2%}' if value is not None else 'n/a'))
        counts = report['totals']
        print(f'Exact boards: {counts["exact_boards"]}/{counts["boards"]}; processing errors: {counts["errors"]}')
        if counts['errors']:
            return 2
        return int(args.min_board_accuracy is not None and report['metrics']['board_accuracy'] < args.min_board_accuracy)
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
