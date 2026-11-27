"""Build a reproducible screenshot/FEN dataset without editing JSON by hand."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys


def _relative_or_absolute(path, root):
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:  # Windows paths on different drives.
        return str(Path(path).resolve())


def _write(path, document):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--init', action='store_true', help='Create a new empty dataset manifest')
    parser.add_argument('--name')
    parser.add_argument('--origin', choices=('real_screenshots', 'generated'), help='Explicit input provenance declaration')
    parser.add_argument('--split', choices=('validation', 'test'))
    parser.add_argument('--profile', help='Reviewed profile; omit for bundled Cburnett')
    parser.add_argument('--id', help='Unique case ID, e.g. middlegame-01')
    parser.add_argument('--image')
    parser.add_argument('--fen', help='Known FEN or piece-placement field copied from the source')
    parser.add_argument('--phase', choices=('opening', 'middlegame', 'endgame'))
    orientation = parser.add_mutually_exclusive_group()
    orientation.add_argument('--white-bottom', action='store_true')
    orientation.add_argument('--black-bottom', action='store_true')
    crop = parser.add_mutually_exclusive_group()
    crop.add_argument('--rect', nargs=4, type=int, metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'))
    crop.add_argument('--select', action='store_true')
    args = parser.parse_args(argv)
    try:
        manifest = Path(args.manifest).resolve()
        if args.init:
            if not (args.name and args.origin and args.split):
                parser.error('--init requires --name, --origin and --split')
            if manifest.exists():
                raise ValueError('Dataset already exists; choose a new manifest or add cases without --init')
            profile = None
            if args.profile:
                from lichess_2d.theme_profiles import load_profile
                profile = load_profile(args.profile).path
            manifest.parent.mkdir(parents=True, exist_ok=True)
            metadata = dict(name=args.name, origin=args.origin, split=args.split,
                            profile=_relative_or_absolute(profile, manifest.parent) if profile else None,
                            note='Provenance/split are declared by the author. Keep test screenshots separate from calibration/tuning.')
            _write(manifest, dict(version=1, dataset=metadata, cases=[]))
            print('Created dataset: ' + str(manifest))
            return 0
        if not (args.id and args.image and args.fen) or not (args.white_bottom or args.black_bottom):
            parser.error('Adding a case requires --id, --image, --fen and one orientation')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', args.id):
            raise ValueError('Use letters, digits, underscores and hyphens in the case ID')
        from lichess_2d.board_locator_2d import BoardRect, extract_position, load_image
        from lichess_2d.notation import parse_placement
        parse_placement(args.fen)
        document = json.loads(manifest.read_text(encoding='utf-8-sig'))
        if document.get('version') != 1 or not isinstance(document.get('cases'), list):
            raise ValueError('Initialize the dataset first')
        if any(case['id'] == args.id for case in document['cases']):
            raise ValueError('Case ID already exists; existing cases are never overwritten')
        source = Path(args.image).resolve()
        with load_image(source) as image:
            rect = BoardRect(*args.rect) if args.rect else None
            if args.select:
                from check_board_extraction_2d import select_rectangle
                rect = select_rectangle(source, image, args.white_bottom)
                if rect is None:
                    print('Selection cancelled; no case added.')
                    return 0
            extraction = extract_position(image, rect=rect, white_bottom=args.white_bottom)
        image_dir = manifest.parent / 'images'
        image_dir.mkdir(exist_ok=True)
        suffix = source.suffix.lower() or '.img'
        destination = image_dir / (args.id + suffix)
        if destination.exists():
            raise ValueError('Destination image already exists; choose a new case ID')
        selected = extraction.rectangle
        case = dict(id=args.id, image=destination.relative_to(manifest.parent).as_posix(), fen=args.fen,
                    white_bottom=args.white_bottom, rect=[selected.left, selected.top, selected.width, selected.height],
                    tags=dict(phase=args.phase) if args.phase else {},
                    recorded_file_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        shutil.copy2(source, destination)
        document['cases'].append(case)
        try:
            _write(manifest, document)
        except Exception:
            destination.unlink()
            raise
        print('Added ' + args.id + '; original screenshot copied into ' + str(image_dir))
        print('Cases now recorded: ' + str(len(document['cases'])))
        return 0
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
