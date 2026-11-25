"""Create and review a reusable theme profile from a standard starting position."""
import argparse
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', help='Clean standard starting-position screenshot')
    parser.add_argument('--name', help='Human-readable profile name')
    parser.add_argument('--output', help='New profile folder; never overwrites an existing profile')
    orientation = parser.add_mutually_exclusive_group()
    orientation.add_argument('--white-bottom', action='store_true')
    orientation.add_argument('--black-bottom', action='store_true')
    crop = parser.add_mutually_exclusive_group()
    crop.add_argument('--select', action='store_true', help='Select the board interactively')
    crop.add_argument('--rect', nargs=4, type=int, metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'))
    parser.add_argument('--review', action='store_true', help='Display the extracted masks/templates and accept or leave draft')
    parser.add_argument('--approve', help='Approve an existing draft AFTER inspecting its template_review.png')
    args = parser.parse_args(argv)
    try:
        from lichess_2d.theme_profiles import approve_profile, create_profile
        if args.approve:
            if any((args.image, args.name, args.output, args.select, args.rect, args.review)):
                parser.error('--approve is a separate action; provide only the draft profile folder')
            path = approve_profile(args.approve)
            print('Profile approved: ' + str(path))
            return 0
        if not (args.image and args.name and args.output) or not (args.white_bottom or args.black_bottom):
            parser.error('Creating a profile requires --image, --name, --output and one orientation')
        from lichess_2d.board_locator_2d import BoardRect, load_image
        qt_app = None
        if args.select or args.review:
            from PySide6.QtWidgets import QApplication
            qt_app = QApplication.instance() or QApplication([sys.argv[0]])
        with load_image(args.image) as image:
            rect = BoardRect(*args.rect) if args.rect else None
            if args.select:
                from check_board_extraction_2d import select_rectangle
                rect = select_rectangle(args.image, image, args.white_bottom)
                if rect is None:
                    print('Selection cancelled; no profile saved.')
                    return 0
            profile = create_profile(image, name=args.name, output_dir=args.output,
                                     white_bottom=args.white_bottom, rect=rect, source_name=Path(args.image).name)
        print('Draft profile saved: ' + str(profile.path))
        print('Inspect template_review.png: verify every piece, both masks, and light/dark compositing.')
        if args.review:
            from lichess_2d.profile_review import review_profile
            if review_profile(profile.path):
                print('Profile approved and ready for recognition.')
                return 0
        print('It remains inactive until reviewed. After inspection, approve with:')
        print('python calibrate_2d.py --approve "' + str(profile.path.parent) + '"')
        return 0
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
