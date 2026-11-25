"""Stress a recorded dataset with JPEG and resampling; never inflate real counts.

Digital resampling is an approximation of scaling, not a browser/HiDPI capture.
Every derivative retains its source case, orientation and transformed rectangle.
Use evaluate_2d.py separately for held-out real-screenshot acceptance evidence.
"""
import argparse
from collections import Counter
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from PIL import Image
from evaluate_2d import load_dataset, score_predictions
from lichess_2d.board_locator_2d import BoardRect, load_image
from lichess_2d.board_proposals import propose_boards
from lichess_2d.notation import parse_placement
from lichess_2d.recognizer_2d import Recognizer2D

VARIANTS = ('original', 'jpeg95', 'jpeg80', 'jpeg60', 'scale075', 'scale125', 'scale150')


def transform(image, rect, variant):
    if variant not in VARIANTS:
        raise ValueError('Unknown stress variant')
    if variant.startswith('jpeg'):
        stream = BytesIO()
        image.save(stream, format='JPEG', quality=int(variant[4:]), subsampling=2)
        stream.seek(0)
        with Image.open(stream) as decoded:
            return decoded.convert('RGB'), rect
    if variant.startswith('scale'):
        factor = int(variant[5:]) / 100
        size = round(image.width * factor), round(image.height * factor)
        scaled = image.resize(size, Image.Resampling.LANCZOS)
        sx, sy = size[0] / image.width, size[1] / image.height
        left, top, right, bottom = rect.box
        box = round(left*sx), round(top*sy), round(right*sx), round(bottom*sy)
        return scaled, BoardRect(box[0], box[1], box[2]-box[0], box[3]-box[1]).checked(size)
    return image.copy(), rect


def evaluate_stress(manifest, *, profile=None, variants=VARIANTS, locate=False):
    path, document = load_dataset(manifest)
    selected = profile or document['dataset'].get('profile')
    if not selected:
        raise ValueError('Select a reviewed --profile or explicitly use --profile builtin:cburnett')
    profile_path = None if selected == 'builtin:cburnett' else (path.parent / selected).resolve()
    model = Recognizer2D(profile_path)
    calibration_hash = model.calibration_pixels_sha256
    groups, records = {v: Counter() for v in variants}, []
    originals = set()
    calibration_reuse = set()
    for case in document['cases']:
        source = (path.parent / case['image']).resolve()
        truth = parse_placement(case['fen'])
        error, image, rect = None, None, None
        try:
            with source.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if case.get('recorded_file_sha256') and digest != case['recorded_file_sha256']:
                raise ValueError('Screenshot changed after recording')
            originals.add(digest)
            image = load_image(source)
            rect = BoardRect(*case['rect']) if case.get('rect') else BoardRect(0, 0, *image.size)
            rect.checked(image.size)
        except (OSError, ValueError, KeyError, TypeError) as problem:
            error = str(problem)
        for variant in variants:
            record = dict(source_id=case['id'], variant=variant, processing_error=error)
            predictions = {s: '?' for s in truth}
            if not error:
                try:
                    changed, changed_rect = transform(image, rect, variant)
                    result, _ = model.predict(changed, white_bottom=case['white_bottom'], rect=changed_rect)
                    predictions = result['pieces']
                    if result['normalized_pixels_sha256'] == calibration_hash:
                        calibration_reuse.add(case['id'])
                    record['rect'] = [changed_rect.left, changed_rect.top, changed_rect.width, changed_rect.height]
                    record['overlay_squares'] = result['overlay_squares']
                    if locate:
                        proposals = propose_boards(changed)
                        record['board_proposals'] = [dict(rect=[p.rectangle.left, p.rectangle.top,
                                                               p.rectangle.width, p.rectangle.height],
                                                              grid_fit=p.grid_fit) for p in proposals]
                        record['proposal_within_3px'] = any(max(abs(a-b) for a,b in zip(p.rectangle.box, changed_rect.box)) <= 3
                                                            for p in proposals)
                    changed.close()
                except (OSError, ValueError, KeyError, TypeError) as problem:
                    record['processing_error'] = str(problem)
                    predictions = {s: '?' for s in truth}
            counts, _, wrong = score_predictions(truth, predictions)
            record.update(counts=dict(counts), mismatches=wrong)
            groups[variant].update(counts)
            groups[variant]['cases'] += 1
            groups[variant]['processing_errors'] += int(record['processing_error'] is not None)
            records.append(record)
        if image is not None:
            image.close()
    return dict(version=1, kind='derived_stress_test', source_manifest=str(path),
                source_origin=document['dataset'].get('origin'), source_case_count=len(document['cases']),
                distinct_source_files=len(originals), derived_case_count=len(records),
                calibration_reference_reused_by=sorted(calibration_reuse),
                evidence='Derived variants are correlated; these are not additional independent screenshots. '
                         'Digital resampling is not actual browser/display scaling.',
                engine=model.identity, groups={v: dict(n) for v,n in groups.items()}, cases=records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--profile')
    parser.add_argument('--output', required=True)
    parser.add_argument('--locate', action='store_true', help='Also measure proposals against recorded rectangles')
    parser.add_argument('--fail-on-wrong', action='store_true', help='Fail on an accepted incorrect prediction')
    parser.add_argument('--require-exact', action='store_true', help='Fail if ANY derived case needs corrections')
    args = parser.parse_args(argv)
    try:
        report = evaluate_stress(args.manifest, profile=args.profile, locate=args.locate)
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        print(f"{report['source_case_count']} source cases, {report['distinct_source_files']} distinct source files; "
              f"{report['derived_case_count']} correlated cases")
        failed = False
        for variant, group in report['groups'].items():
            wrong = group['accepted'] - group['accepted_correct']
            print(f"{variant}: exact {group['exact_board']}/{group['cases']}; "
                  f"unknown {group['unknown']}; accepted wrong {wrong}; errors {group['processing_errors']}")
            failed |= bool(group['processing_errors'] or (args.fail_on_wrong and wrong) or
                           (args.require_exact and group['exact_board'] != group['cases']))
        return int(failed)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
