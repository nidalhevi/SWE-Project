"""Connect the uploaded main branch's trained classifier to the stage-8 GUI.

No Qt or referee calls here. image_recognition_worker.py runs this function in
a separate Python process. Configure its import path to the updated vision/.
"""
from pathlib import Path
from image_import import ImageImportError, recognition_from_probabilities, SQUARES


def board_crop_corners(width, height):
    """Pixel-center corners of an image the USER confirms is exactly the 8x8 board.

    This bypasses the photo corner regressor. It does not improve the classifier
    or detect where a board is inside a larger screenshot.
    """
    if width < 16 or height < 16 or abs(width - height) / max(width, height) > .03:
        raise ImageImportError('Board-crop mode needs a square image of only the 8x8 board. '
                               'Exclude player panels, clocks, and outer margins.')
    return ((0., 0.), (float(width - 1), 0.),
            (float(width - 1), float(height - 1)), (0., float(height - 1)))


def _load_bgr(image_path):
    """Use the same EXIF orientation as the GUI preview, then RGB -> BGR."""
    import numpy as np
    from PIL import Image, ImageOps, UnidentifiedImageError

    path = Path(image_path)
    if not path.is_file():
        raise ImageImportError('Image file does not exist: ' + str(path))
    if path.suffix.lower() in ('.heic', '.heif'):
        raise ImageImportError('Convert HEIC/HEIF to JPEG or PNG for this Windows adapter')
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ImageImportError('Image exceeds 50 MiB')
    try:
        with Image.open(path) as original:
            if original.width * original.height > 60_000_000:
                raise ImageImportError('Image exceeds 60 megapixels')
            rgb = np.asarray(ImageOps.exif_transpose(original).convert('RGB'))
            return np.ascontiguousarray(rgb[:, :, ::-1])
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ImageImportError('Cannot read image: ' + str(error)) from error


def _get_classifier():
    # This API and its crop geometry come from the actual supplied classifier.
    # Keep the heavyweight imports inside the worker's call, outside the GUI.
    try:
        from chessvision.classifier import SquareClassifier
    except ModuleNotFoundError as error:
        if error.name in ('chessvision', 'chessvision.classifier'):
            raise ImageImportError('Set --vision-path to the updated folder containing chessvision/classifier.py') from error
        raise ImageImportError('Missing vision dependency: ' + str(error) +
                               '. Install the vision ML dependencies with the GUI Python.') from error
    return SquareClassifier()


def _classify(image_bgr, orientation, *, board_crop=False):
    classifier = _get_classifier()
    # probs() detects corners, uses warp_for_crops/grid_crops, runs the model,
    # and maps its 64 rows to a1..h8. Do not use the older square_crops helper.
    if board_crop:
        import numpy as np
        height, width = image_bgr.shape[:2]
        corners = np.asarray(board_crop_corners(width, height), dtype=np.float32)
        return classifier.probs(image_bgr, orientation=orientation, corners=corners)
    return classifier.probs(image_bgr, orientation=orientation)


def _format_predictions(probabilities, *, board_crop=False):
    result = recognition_from_probabilities(probabilities, min_confidence=0.5)
    pieces = list(result['pieces'].values())
    kings = (pieces.count('K'), pieces.count('k'))
    if kings != (1, 1):
        result['message'] = ('Unreliable reading: predictions do not contain exactly one king of each color. '
                             'Check the detected board/grid and classifier compatibility. '
                             'Raw predictions are shown for correction; validation has not passed.')
    elif board_crop:
        result['message'] = ('Board detection was bypassed using your exact board crop. '
                             'The photo-trained classifier may still misread screenshot icons. '
                             'Review every piece and all position details.')
    else:
        result['message'] = ('Photo model returned predictions; this is not a correctness check. '
                             'Review every piece and all position details.')
    return result


def recognize(image_path: str, *, white_bottom: bool) -> dict:
    """Return the pieces/confidence mapping required by image_recognition_worker.

    Model orientation is an integer: White bottom = 0, Black bottom = 2.
    bool False must not become orientation 1 (a quarter turn).
    There is no previous position here, so orientation is explicitly chosen.
    """
    if type(white_bottom) is not bool:
        raise ImageImportError('white_bottom must be True or False')
    image = _load_bgr(image_path)
    orientation = 0 if white_bottom else 2
    probabilities = _classify(image, orientation)
    return _format_predictions(probabilities)


def recognize_board_crop(image_path: str, *, white_bottom: bool) -> dict:
    """Use only on a pre-cropped square digital board; skips learned corner detection.

    It retains the existing photo-trained classifier and does not claim to solve
    screenshot-domain accuracy. Use diagnose_image to see the actual input crops.
    """
    if type(white_bottom) is not bool:
        raise ImageImportError('white_bottom must be True or False')
    image = _load_bgr(image_path)
    height, width = image.shape[:2]
    board_crop_corners(width, height)  # Reject an invalid crop before loading ML.
    probabilities = _classify(image, 0 if white_bottom else 2, board_crop=True)
    return _format_predictions(probabilities, board_crop=True)


def _write_diagnostics(directory, image, corners, warped, crops, probabilities, mapping, *, source, board_crop):
    """Save actual model inputs, overlay, and per-square output for local inspection."""
    import json
    import numpy as np
    from PIL import Image, ImageDraw
    import chessvision.classifier as classifier_module
    from chessvision.board import draw_grid
    from chessvision.labels import NAMES

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    def rgb(bgr):
        return Image.fromarray(np.ascontiguousarray(bgr[:, :, ::-1]))

    rgb(draw_grid(image, corners)).save(directory / '01_detected_grid.png')
    rgb(warped).save(directory / '02_warped_model_input.png')
    crop_height, crop_width = crops.shape[1:3]
    sheet = Image.new('RGB', (8 * crop_width, 8 * (crop_height + 24)), '#ffffff')
    draw = ImageDraw.Draw(sheet)
    square_of_grid = np.argsort(mapping)
    for grid_index, crop in enumerate(crops):
        x, y = (grid_index % 8) * crop_width, (grid_index // 8) * (crop_height + 24)
        sheet.paste(rgb(crop), (x, y))
        square_index = int(square_of_grid[grid_index])
        row = probabilities[square_index]
        best = int(np.argmax(row))
        caption = f'{SQUARES[square_index]} {NAMES[best]} {float(row[best]):.2f}'
        draw.text((x + 2, y + crop_height + 3), caption, fill='#000000')
    sheet.save(directory / '03_square_crops.png')
    predictions = []
    for index, row in enumerate(probabilities):
        top = np.argsort(row)[::-1][:3]
        predictions.append(dict(square=SQUARES[index], raw_label=NAMES[int(top[0])],
                                top3=[dict(label=NAMES[int(label)], probability=float(row[label])) for label in top]))
    document = dict(
        source=str(Path(source).resolve()), mode='board-crop' if board_crop else 'automatic-detection',
        classifier_module=str(Path(classifier_module.__file__).resolve()),
        classifier_weights=str(Path(classifier_module.DEFAULT_WEIGHTS).resolve()),
        corners_pixels=np.asarray(corners).tolist(), square_order='a1 through h8, file first',
        label_order=list(NAMES), empty_predictions=sum(row['raw_label'] == 'EMPTY' for row in predictions),
        predictions=predictions,
    )
    (directory / '04_predictions.json').write_text(json.dumps(document, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def diagnose_image(image_path, *, white_bottom, directory, board_crop=False):
    """Same trained-model preprocessing, with visible geometry and crop outputs.

    This diagnostic runs once in the CLI. It does not create a model or alter
    class probabilities, and it does not upload the source photo anywhere.
    """
    import numpy as np
    from chessvision.board import find_corners, warp_for_crops, grid_crops, grid_of_square

    if type(white_bottom) is not bool:
        raise ImageImportError('white_bottom must be True or False')
    image = _load_bgr(image_path)
    height, width = image.shape[:2]
    corners = (np.asarray(board_crop_corners(width, height), dtype=np.float32) if board_crop
               else find_corners(image))
    if corners is None:
        raise ImageImportError('No board detected; use a clearer photo or an exact square board crop')
    warped = warp_for_crops(image, corners)
    crops = grid_crops(warped)
    classifier = _get_classifier()
    grid_probabilities = classifier.grid_probs(warped)
    mapping = grid_of_square(0 if white_bottom else 2)
    probabilities = grid_probabilities[mapping]
    result = _format_predictions(probabilities, board_crop=board_crop)
    _write_diagnostics(directory, image, corners, warped, crops, probabilities, mapping,
                       source=image_path, board_crop=board_crop)
    return result
