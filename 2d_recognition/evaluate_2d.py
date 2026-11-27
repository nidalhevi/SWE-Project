"""Evaluate known screenshot/FEN pairs, without Qt, the GUI or a chess engine.

Metrics include every listed case. Processing failures count as 64 unknown/wrong
squares; they are never dropped. A generated-fixture run cannot pass the real
held-out screenshot acceptance gate, regardless of its numerical accuracy.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
import argparse

LABELS = (None, *'PNBRQKpnbrqk')


def load_dataset(path):
    from lichess_2d.notation import parse_placement
    path = Path(path).resolve()
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(document, list):
        document = dict(version=1, dataset=dict(name=path.stem, origin='unspecified', split='unspecified'), cases=document)
    if (not isinstance(document, dict) or document.get('version') != 1
            or not isinstance(document.get('dataset'), dict) or not isinstance(document.get('cases'), list)
            or not document['cases']):
        raise ValueError('Use a version-1 dataset object with metadata and a nonempty cases list')
    ids = set()
    for index, case in enumerate(document['cases']):
        if not isinstance(case, dict) or not isinstance(case.get('image'), str) or not case['image'].strip():
            raise ValueError('Each case needs an image path')
        if type(case.get('white_bottom')) is not bool:
            raise ValueError('Each case needs an explicit white_bottom true/false value')
        if not isinstance(case.get('fen'), str):
            raise ValueError('Each case needs a known FEN placement')
        parse_placement(case['fen'])
        case.setdefault('id', f'case-{index + 1:04d}')
        if not isinstance(case['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', case['id']):
            raise ValueError('Case IDs must use letters, digits, underscores or hyphens')
        if case['id'] in ids:
            raise ValueError('Duplicate case ID: ' + case['id'])
        ids.add(case['id'])
    return path, document


def _ratio(n, d):
    return n / d if d else None


def score_predictions(truth, predictions):
    """Account for a complete board; unknown is wrong and is not accepted."""
    if len(truth) != 64:
        raise ValueError('Ground truth must describe all 64 squares')
    counts = Counter(squares=64, occupied=0, empty=0, correct=0, occupied_correct=0,
                     empty_correct=0, unknown=0, accepted=0, accepted_correct=0,
                     occupied_as_empty=0, empty_as_piece=0, occupied_as_wrong_piece=0)
    confusion = Counter()
    mismatches = []
    for square, target in truth.items():
        guess = predictions.get(square, '?')
        if guess not in (*LABELS, '?'):
            raise ValueError('Invalid prediction label')
        correct = guess == target
        kind = 'empty' if target is None else 'occupied'
        counts[kind] += 1
        counts['correct'] += int(correct)
        counts[kind + '_correct'] += int(correct)
        if guess == '?':
            counts['unknown'] += 1
        else:
            counts['accepted'] += 1
            counts['accepted_correct'] += int(correct)
        counts['occupied_as_empty'] += int(target is not None and guess is None)
        counts['empty_as_piece'] += int(target is None and guess not in (None, '?'))
        counts['occupied_as_wrong_piece'] += int(target is not None and guess not in (None, '?', target))
        confusion[(target or 'empty', guess or 'empty')] += 1
        if not correct:
            mismatches.append(dict(square=square, expected=target, predicted=guess))
    counts['exact_board'] = int(not mismatches)
    return counts, confusion, mismatches


def evaluate(manifest_path, *, profile=None, target=.95, min_images=20, diagnostics=None):
    from lichess_2d.board_locator_2d import BoardRect, load_image
    from lichess_2d.notation import parse_placement
    from lichess_2d.recognizer_2d import Recognizer2D, save_diagnostics
    if not 0 <= target <= 1 or type(min_images) is not int or min_images < 1:
        raise ValueError('Target must be in 0..1 and minimum image count must be positive')
    manifest, document = load_dataset(manifest_path)
    metadata = document['dataset']
    selected = profile if profile is not None else metadata.get('profile')
    profile_path = (manifest.parent / selected).resolve() if selected else None
    model = Recognizer2D(profile_path)
    calibration_hash = model.calibration_pixels_sha256
    totals, confusion = Counter(), Counter()
    results = []
    raw_hashes, normalized_hashes = defaultdict(list), defaultdict(list)
    leakage = []
    orientations, board_sizes, phases = set(), set(), set()
    piece_backgrounds = {code: Counter(light=0, dark=0) for code in 'PNBRQKpnbrqk'}
    diagnostic_root = Path(diagnostics).resolve() if diagnostics else None
    for case in document['cases']:
        truth = parse_placement(case['fen'])
        image_path = (manifest.parent / case['image']).resolve()
        prediction = {s: '?' for s in truth}
        error, result, source_size, selected_size, raw_hash = None, None, None, None, None
        try:
            if image_path.is_file():
                if image_path.stat().st_size > 50 * 1024 * 1024:
                    raise ValueError('Image exceeds the 50 MiB input limit')
                with image_path.open('rb') as source:
                    raw_hash = hashlib.file_digest(source, 'sha256').hexdigest()
                raw_hashes[raw_hash].append(case['id'])
                if case.get('recorded_file_sha256') and case['recorded_file_sha256'] != raw_hash:
                    raise ValueError('Screenshot changed after it was recorded in the dataset')
            rectangle = case.get('rect')
            if rectangle is not None and (not isinstance(rectangle, list) or len(rectangle) != 4):
                raise ValueError('rect must be [left, top, width, height]')
            rect = BoardRect(*rectangle) if rectangle is not None else None
            with load_image(image_path) as image:
                source_size = image.size
                result, extraction = model.predict(image, white_bottom=case['white_bottom'], rect=rect)
            selected_size = (extraction.rectangle.width, extraction.rectangle.height)
            prediction = result['pieces']
            normalized_hash = result['normalized_pixels_sha256']
            normalized_hashes[normalized_hash].append(case['id'])
            if calibration_hash is not None and normalized_hash == calibration_hash:
                leakage.append(case['id'])
            if diagnostic_root:
                save_diagnostics(result, extraction, diagnostic_root / case['id'], truth=truth)
        except (OSError, ValueError, KeyError, TypeError) as problem:
            error = str(problem)
            prediction = {s: '?' for s in truth}
            totals['processing_errors'] += 1
        counts, matrix, wrong = score_predictions(truth, prediction)
        totals.update(counts)
        confusion.update(matrix)
        orientations.add('white_bottom' if case['white_bottom'] else 'black_bottom')
        if selected_size:
            board_sizes.add(selected_size)
        tags = case.get('tags') or {}
        if isinstance(tags, dict) and tags.get('phase'):
            phases.add(str(tags['phase']))
        for square, code in truth.items():
            if code:
                kind = 'light' if ('abcdefgh'.index(square[0]) + int(square[1])) % 2 == 0 else 'dark'
                piece_backgrounds[code][kind] += 1
        for mismatch in wrong:
            detail = result['details'].get(mismatch['square']) if result else None
            mismatch['diagnostic'] = detail
        record = dict(id=case['id'], image=case['image'], file_sha256=raw_hash,
                      white_bottom=case['white_bottom'], fen=case['fen'], rect=case.get('rect'),
                      source_size=source_size, board_size=selected_size, tags=tags,
                      processing_error=error, counts=dict(counts), mismatches=wrong, predictions=prediction)
        if result:
            record['normalized_pixels_sha256'] = result['normalized_pixels_sha256']
        results.append(record)
        if diagnostic_root and error:
            case_dir = diagnostic_root / case['id']
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / 'error.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    totals['boards'] = len(results)
    totals['unique_image_files'] = len(raw_hashes)
    totals['unique_normalized_boards'] = len(normalized_hashes)
    totals.setdefault('processing_errors', 0)
    metrics = dict(board_accuracy=_ratio(totals['exact_board'], totals['boards']),
                   square_accuracy=_ratio(totals['correct'], totals['squares']),
                   occupied_square_accuracy=_ratio(totals['occupied_correct'], totals['occupied']),
                   empty_square_accuracy=_ratio(totals['empty_correct'], totals['empty']),
                   unknown_square_rate=_ratio(totals['unknown'], totals['squares']),
                   accuracy_among_accepted=_ratio(totals['accepted_correct'], totals['accepted']),
                   coverage=_ratio(totals['accepted'], totals['squares']),
                   always_empty_baseline=_ratio(totals['empty'], totals['squares']))
    duplicates = dict(files=[ids for ids in raw_hashes.values() if len(ids) > 1],
                       normalized_boards=[ids for ids in normalized_hashes.values() if len(ids) > 1])
    evidence_issues = []
    if metadata.get('origin') != 'real_screenshots':
        evidence_issues.append('Dataset is not declared to contain real screenshots')
    if metadata.get('split') != 'test':
        evidence_issues.append('Dataset is not declared to be the separate held-out test set')
    if len(raw_hashes) < min_images:
        evidence_issues.append(f'Need at least {min_images} distinct image files for this acceptance gate')
    if duplicates['files'] or duplicates['normalized_boards']:
        evidence_issues.append('Duplicate files or identical normalized boards would inflate the image count')
    if leakage:
        evidence_issues.append('Calibration reference appears in the evaluation set')
    warnings = []
    if len(orientations) < 2:
        warnings.append('Only one board orientation is represented')
    if len(board_sizes) < 2:
        warnings.append('Only one original board size is represented')
    if len(phases) < 3:
        warnings.append('Opening/middlegame/endgame coverage has not all been documented')
    missing_backgrounds = [code for code, counts in piece_backgrounds.items() if not counts['light'] or not counts['dark']]
    if missing_backgrounds:
        warnings.append('Piece types not observed on both square colors: ' + ', '.join(missing_backgrounds))
    if totals['processing_errors']:
        status = 'failed_processing'
    elif evidence_issues:
        status = 'insufficient_evidence'
    elif metrics['board_accuracy'] < target:
        status = 'target_not_met'
    else:
        status = 'target_met_on_declared_dataset'
    versions = {name: importlib.metadata.version(name) for name in ('numpy', 'Pillow')}
    return dict(version=1, dataset=metadata, manifest=str(manifest),
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(), engine=model.identity,
                python=sys.version.split()[0], libraries=versions, totals=dict(totals), metrics=metrics,
                acceptance=dict(target=target, minimum_images=min_images, status=status,
                                evidence_issues=evidence_issues, coverage_warnings=warnings,
                                provenance_note='Origin and split are supplied by the dataset author; not automatically verified'),
                audits=dict(duplicates=duplicates, calibration_reuse=leakage),
                coverage=dict(orientations=sorted(orientations), original_board_sizes=sorted(board_sizes),
                              phases=sorted(phases), piece_background_counts=piece_backgrounds),
                confusion_matrix={label or 'empty': {guess or 'empty': confusion[(label or 'empty', guess or 'empty')]
                                  for guess in (*LABELS, '?')} for label in LABELS}, cases=results)


def write_report(report, output):
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    with path.with_suffix('.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['id', 'image', 'exact_board', 'correct_squares', 'occupied_correct',
                         'occupied', 'empty_correct', 'empty', 'unknown', 'accepted', 'accepted_correct', 'error'])
        for case in report['cases']:
            counts = case['counts']
            writer.writerow([case['id'], case['image'], *(counts[key] for key in
                            ('exact_board', 'correct', 'occupied_correct', 'occupied', 'empty_correct',
                             'empty', 'unknown', 'accepted', 'accepted_correct')), case['processing_error']])
    counts = report['totals']
    lines = ['# Screenshot recognition evaluation', '',
             'Dataset: ' + str(report['dataset'].get('name', 'unnamed')), '',
             'Declared origin: ' + str(report['dataset'].get('origin', 'unspecified')),
             ' / split: ' + str(report['dataset'].get('split', 'unspecified')), '',
             f'Completely correct boards: **{counts["exact_board"]}/{counts["boards"]}**. '
             f'Distinct image files: **{counts["unique_image_files"]}**. '
             f'Processing failures: **{counts["processing_errors"]}**.', '',
             '| Metric | Result |', '| --- | --- |']
    for name, value in report['metrics'].items():
        lines.append('| ' + name + ' | ' + ('n/a' if value is None else f'{value:.2%}') + ' |')
    lines.extend(['', 'Acceptance status: **' + report['acceptance']['status'] + '**.', '',
                  f'Proposed target: {report["acceptance"]["target"]:.0%} exact boards; '
                  f'minimum distinct images: {report["acceptance"]["minimum_images"]}.', '',
                  report['acceptance']['provenance_note'], ''])
    for issue in report['acceptance']['evidence_issues'] + report['acceptance']['coverage_warnings']:
        lines.append('- ' + issue)
    lines.extend(['', 'Profile: ' + report['engine']['profile_name'], '',
                  'Engine version: ' + report['engine']['version'], '',
                  'Full image hashes, profile fingerprint, settings and per-square errors are in the JSON report.', ''])
    path.with_suffix('.md').write_text('\n'.join(lines), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--profile', help='Optional override of the profile recorded in the dataset')
    parser.add_argument('--output', required=True, help='JSON report; a CSV with the same stem is also saved')
    parser.add_argument('--diagnostics', help='Optional per-case images and detailed predictions')
    parser.add_argument('--target', type=float, default=.95)
    parser.add_argument('--min-images', type=int, default=20)
    parser.add_argument('--check-target', action='store_true', help='Exit 1 unless the real test-set gate passes')
    args = parser.parse_args(argv)
    try:
        profile = str(Path(args.profile).resolve()) if args.profile else None
        report = evaluate(args.manifest, profile=profile, target=args.target,
                          min_images=args.min_images, diagnostics=args.diagnostics)
        write_report(report, args.output)
        t = report['totals']
        print(f'Completely correct boards: {t["exact_board"]}/{t["boards"]}; distinct image files: {t["unique_image_files"]}')
        for key, value in report['metrics'].items():
            print(key + ': ' + ('n/a' if value is None else f'{value:.2%}'))
        print('Acceptance: ' + report['acceptance']['status'])
        for issue in report['acceptance']['evidence_issues'] + report['acceptance']['coverage_warnings']:
            print('  ' + issue)
        if t['processing_errors']:
            return 2
        return int(args.check_target and report['acceptance']['status'] != 'target_met_on_declared_dataset')
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
