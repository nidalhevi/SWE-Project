"""Evaluate existing team checkpoints on ChessReD2K, without Qt, a cache, or C.

Run with the same Windows Python/vision folder used by the GUI. Compare
annotated-corner and learned-corner inference to isolate detection errors.
This is evaluation only: no training and no checkpoint writes.
"""
import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sys
import time

LABELS = ('EMPTY', 'WP', 'WN', 'WB', 'WR', 'WQ', 'WK', 'BP', 'BN', 'BB', 'BR', 'BQ', 'BK')


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


@dataclass
class Accuracy:
    images: int = 0
    exact_boards: int = 0
    failed_images: int = 0
    # Last column records a failed prediction, so failures are not dropped.
    confusion: list = field(default_factory=lambda: [[0] * 14 for _ in range(13)])

    def add(self, truth, prediction):
        truth = list(truth)
        if len(truth) != 64 or any(type(label) is not int or not 0 <= label < 13 for label in truth):
            raise ValueError('Ground truth must contain 64 integer labels, 0..12')
        if prediction is not None:
            prediction = list(prediction)
            if len(prediction) != 64 or any(type(label) is not int or not 0 <= label < 13 for label in prediction):
                raise ValueError('Prediction must contain 64 integer labels, 0..12')
        self.images += 1
        self.failed_images += prediction is None
        self.exact_boards += prediction is not None and prediction == truth
        for index, label in enumerate(truth):
            self.confusion[label][13 if prediction is None else prediction[index]] += 1

    def summary(self):
        supports = [sum(row) for row in self.confusion]
        total = sum(supports)
        correct = sum(self.confusion[label][label] for label in range(13))
        occupied = sum(supports[1:])
        occupied_correct = sum(self.confusion[label][label] for label in range(1, 13))
        percent = lambda numerator, denominator: 100 * numerator / denominator if denominator else None
        return dict(
            images=self.images, failed_images=self.failed_images,
            square_accuracy_percent=percent(correct, total),
            occupied_square_accuracy_percent=percent(occupied_correct, occupied),
            empty_square_accuracy_percent=percent(self.confusion[0][0], supports[0]),
            fully_correct_boards_percent=percent(self.exact_boards, self.images),
            always_empty_baseline_percent=percent(supports[0], total),
            per_class_recall={LABELS[label]: dict(support=supports[label],
                                                accuracy_percent=percent(self.confusion[label][label], supports[label]))
                              for label in range(13)},
            confusion=self.confusion,
            confusion_columns=[*LABELS, 'NO_PREDICTION'],
        )


def options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vision-path', required=True, help='Updated vision folder containing chessvision/')
    parser.add_argument('--dataset-dir', required=True, help='Folder containing annotations.json and images/')
    parser.add_argument('--split', choices=('train', 'val', 'test'), default='test')
    parser.add_argument('--limit', type=int, default=20, help='Images to evaluate; 0 means the whole split')
    parser.add_argument('--mode', choices=('both', 'annotated', 'detected'), default='both')
    parser.add_argument('--square-weights', help='Optional classifier checkpoint; default is imported package checkpoint')
    parser.add_argument('--corner-weights', help='Optional corner checkpoint; default is imported package checkpoint')
    parser.add_argument('--threads', type=int, default=4, help='CPU Torch threads')
    parser.add_argument('--raw-warp', action='store_true', help='Skip JPEG-95 roundtrip; default matches cache preprocessing')
    parser.add_argument('--output', help='Optional JSON report path')
    parser.add_argument('--traceback', action='store_true', help='Show full traceback for setup/runtime errors')
    args = parser.parse_args(argv)
    if args.limit < 0 or args.threads < 1:
        parser.error('--limit must be >=0 and --threads >=1')
    return args


def evaluate(args):
    root, dataset_root = Path(args.vision_path).resolve(), Path(args.dataset_dir).resolve()
    if not (root / 'chessvision/classifier.py').is_file():
        raise FileNotFoundError('Updated classifier.py is missing under --vision-path')
    if not (dataset_root / 'annotations.json').is_file():
        raise FileNotFoundError('annotations.json is missing under --dataset-dir; weights do not include the dataset')
    sys.path.insert(0, str(root))
    import cv2
    import numpy as np
    import torch
    import torchvision
    import chessvision.classifier as classifier_module
    import chessvision.corner_net as corner_module
    from chessvision.board import warp_for_crops, grid_of_square, orientation_from_named, refine_by_warp, corner_error
    from chessvision.data.chessred import ChessReD
    from chessvision.labels import placement_to_fen

    torch.set_num_threads(args.threads)
    square_weights = Path(args.square_weights or classifier_module.DEFAULT_WEIGHTS).resolve()
    corner_weights = Path(args.corner_weights or corner_module.DEFAULT_WEIGHTS).resolve()
    modes = ('annotated', 'detected') if args.mode == 'both' else (args.mode,)
    for path in [square_weights] + ([corner_weights] if 'detected' in modes else []):
        if not path.is_file():
            raise FileNotFoundError('Checkpoint missing: ' + str(path))
    model = classifier_module.SquareClassifier(weights=str(square_weights), dev=torch.device('cpu'))
    detector = (corner_module.CornerPredictor(weights=str(corner_weights), dev=torch.device('cpu'))
                if 'detected' in modes else None)
    dataset = ChessReD(str(dataset_root))
    all_ids = dataset.ids(args.split, 'chessred2k')
    ids = all_ids[:args.limit] if args.limit else all_ids
    if not ids:
        raise ValueError('Selected ChessReD2K split contains no images')
    # Fail early for missing files; do not silently score a different subset.
    for image_id in ids:
        sample = dataset.sample(image_id)
        if sample.corners is None or not Path(sample.path).is_file():
            raise FileNotFoundError(f'Dataset image/corner annotation missing for image {image_id}: {sample.path}')
        if sample.labels.count(6) != 1 or sample.labels.count(12) != 1:
            raise ValueError(f'Unexpected ground-truth king labels for image {image_id}; verify dataset/category mapping')
    report = dict(
        split=args.split, available_images=len(all_ids), evaluated_images=len(ids),
        dataset=str(dataset_root), classifier_module=str(Path(classifier_module.__file__).resolve()),
        square_weights=str(square_weights), square_sha256=sha256(square_weights),
        corner_weights=str(corner_weights) if detector is not None else None,
        corner_sha256=sha256(corner_weights) if detector is not None else None,
        device='cpu', threads=args.threads,
        versions=dict(torch=torch.__version__, torchvision=torchvision.__version__, numpy=np.__version__, opencv=cv2.__version__),
        jpeg_quality=None if args.raw_warp else 95,
        orientation='From dataset corner annotations; no previous-game inference or GUI orientation assumption',
        raw_argmax=True, examples=[],
    )
    metrics = {mode: Accuracy() for mode in modes}
    corner_errors = []
    print('Classifier:', report['square_weights'], flush=True)
    print('SHA256:', report['square_sha256'], flush=True)
    print(f'Evaluating {len(ids)} of {len(all_ids)} {args.split} images on CPU; no training.', flush=True)
    start = time.perf_counter()
    for index, image_id in enumerate(ids):
        sample = dataset.sample(image_id)
        # Unicode-safe Windows file read; original evaluation also uses OpenCV.
        image = cv2.imdecode(np.frombuffer(Path(sample.path).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Cannot decode dataset image: ' + sample.path)
        if image.shape[1] != sample.width or image.shape[0] != sample.height:
            raise ValueError(f'Image {image_id} dimensions differ from annotations; use original dataset images, not resized copies')
        example = dict(image_id=image_id, path=sample.path, truth_placement=placement_to_fen(sample.labels), modes={})
        for mode in modes:
            if mode == 'annotated':
                corners = sample.corners
            else:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                corners = refine_by_warp(gray, detector(image))
                if corners is not None and np.isfinite(corners).all():
                    corner_errors.append(float(corner_error(corners, sample.corners)))
            if corners is None or not np.isfinite(corners).all():
                metrics[mode].add(sample.labels, None)
                example['modes'][mode] = dict(failed=True)
                continue
            orientation = orientation_from_named(corners, sample.corners)
            warped = warp_for_crops(image, corners)
            if not args.raw_warp:
                ok, encoded = cv2.imencode('.jpg', warped, [cv2.IMWRITE_JPEG_QUALITY, 95])
                if not ok:
                    raise RuntimeError('Could not reproduce cache JPEG encoding')
                warped = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            probabilities = model.grid_probs(warped)[grid_of_square(orientation)]
            if probabilities.shape != (64, 13) or not np.isfinite(probabilities).all():
                raise ValueError('Model returned malformed probabilities')
            predicted = probabilities.argmax(1).tolist()
            metrics[mode].add(sample.labels, predicted)
            example['modes'][mode] = dict(
                orientation=int(orientation), corners_pixels=np.asarray(corners).tolist(),
                predicted_placement=placement_to_fen(predicted),
                wrong_squares=['abcdefgh'[square % 8] + str(square // 8 + 1)
                               for square, (truth, guess) in enumerate(zip(sample.labels, predicted)) if truth != guess],
            )
        # Keep a few examples plus early failing cases for GUI comparisons.
        if len(report['examples']) < 10:
            report['examples'].append(example)
        if (index + 1) % 10 == 0 or index + 1 == len(ids):
            print(f'  Evaluated {index + 1}/{len(ids)}', flush=True)
    report['seconds'] = time.perf_counter() - start
    report['results'] = {mode: value.summary() for mode, value in metrics.items()}
    if corner_errors:
        values = np.asarray(corner_errors)
        report['corner_detection'] = dict(
            median_error_percent_of_board_side=float(np.median(values) * 100),
            within_2_percent=float(np.mean(values <= .02) * 100),
            within_5_percent=float(np.mean(values <= .05) * 100),
        )
    print('\nAccuracy results (raw class predictions, no GUI threshold):', flush=True)
    display = lambda value: 'n/a' if value is None else f'{value:.2f}%'
    for mode, result in report['results'].items():
        print(f'{mode} corners: squares {display(result["square_accuracy_percent"])}, '
              f'occupied {display(result["occupied_square_accuracy_percent"])}, '
              f'fully correct boards {display(result["fully_correct_boards_percent"])}')
        print(f'  Images {result["images"]}; failed {result["failed_images"]}; '
              f'always-EMPTY baseline {display(result["always_empty_baseline_percent"])}')
    print('Evaluation finished. Compare the metrics; successful execution is not an accuracy guarantee.')
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print('Report:', path.resolve())
    return report


def main(argv=None):
    args = options(argv)
    try:
        evaluate(args)
        return 0
    except Exception as error:
        if args.traceback:
            import traceback
            traceback.print_exc()
        else:
            print('ERROR:', str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
