"""Select/extract a board and save 64 labeled square images; no classification."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


def select_rectangle(path, image, white_bottom):
    """Optional Qt selector; --rect mode works without Qt."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImageReader, QPixmap
    from PySide6.QtWidgets import QApplication, QDialog
    from lichess_2d.crop_dialog import BoardCropDialog
    app = QApplication.instance() or QApplication([sys.argv[0]])
    reader = QImageReader(str(Path(path).resolve()))
    reader.setAutoTransform(True)
    # Keep the full image's aspect ratio. EXIF transpose may swap its dimensions,
    # so let Qt transform first and then fit the resulting preview pixmap.
    preview = reader.read()
    if preview.isNull():
        raise ValueError('Qt cannot read the screenshot: ' + reader.errorString())
    pixmap = QPixmap.fromImage(preview).scaled(QSize(1400, 1400), Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
    dialog = BoardCropDialog(pixmap, image.size, white_bottom=white_bottom)
    return dialog.rectangle if dialog.exec() == QDialog.DialogCode.Accepted else None


def save_extraction(image, extraction, output):
    from PIL import Image, ImageDraw
    from lichess_2d.board_locator_2d import grid_segments
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    square_dir = directory / 'squares'
    square_dir.mkdir(exist_ok=True)
    extraction.board.save(directory / 'board.png')
    cell_size = extraction.board.width // 8
    sheet = Image.new('RGB', (8 * (cell_size + 8), 8 * (cell_size + 22)), '#dedede')
    draw = ImageDraw.Draw(sheet)
    metadata = dict(source_size=extraction.source_size, rectangle=asdict(extraction.rectangle),
                    white_bottom=extraction.white_bottom, normalized_size=extraction.board.size,
                    square_size=[cell_size, cell_size], square_order='visual row-major; pixels never rotated',
                    squares=[])
    for cell in extraction.squares:
        filename = 'squares/' + cell.square + '.png'
        cell.image.save(directory / filename)
        x, y = cell.column * (cell_size + 8), cell.row * (cell_size + 22)
        sheet.paste(cell.image, (x + 4, y))
        draw.text((x + 4, y + cell_size + 3), cell.square, fill='black')
        metadata['squares'].append(dict(square=cell.square, row=cell.row, column=cell.column,
                                        normalized_box=cell.box, path=filename))
    sheet.save(directory / 'contact_sheet.png')
    preview = image.copy()
    preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    scale_x, scale_y = preview.width / image.width, preview.height / image.height
    draw = ImageDraw.Draw(preview)
    for x1, y1, x2, y2 in grid_segments(extraction.rectangle):
        draw.line((x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y), fill='#ffb300', width=2)
    rect = extraction.rectangle
    for cell in extraction.squares:
        x = (rect.left + cell.column * rect.width / 8) * scale_x + 3
        y = (rect.top + cell.row * rect.height / 8) * scale_y + 3
        draw.text((x, y), cell.square, fill='#ffcf50', stroke_width=1, stroke_fill='#222222')
    preview.save(directory / 'source_grid.png')
    (directory / 'extraction.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', required=True)
    orientation = parser.add_mutually_exclusive_group(required=True)
    orientation.add_argument('--white-bottom', action='store_true')
    orientation.add_argument('--black-bottom', action='store_true')
    crop = parser.add_mutually_exclusive_group()
    crop.add_argument('--rect', type=int, nargs=4, metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'))
    crop.add_argument('--select', action='store_true', help='Open the interactive board/grid selector')
    args = parser.parse_args(argv)
    try:
        from lichess_2d.board_locator_2d import BoardRect, extract_position, load_image
        with load_image(args.image) as image:
            rect = BoardRect(*args.rect) if args.rect else None
            if args.select:
                rect = select_rectangle(args.image, image, args.white_bottom)
                if rect is None:
                    print('Selection cancelled; no extraction was saved.')
                    return 0
            extraction = extract_position(image, rect=rect, white_bottom=args.white_bottom)
            save_extraction(image, extraction, args.output)
        print('Saved 512×512 board and exactly 64 upright 64×64 square images.')
        print('Inspect source_grid.png and contact_sheet.png in: ' + str(Path(args.output).resolve()))
        return 0
    except ImportError as error:
        print('Missing dependency: ' + str(error) + '. Install pillow; --select also requires PySide6.', file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
