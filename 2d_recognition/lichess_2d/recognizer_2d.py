"""Inspectable square recognition for offline evaluation before GUI adoption.

None = positive evidence of an empty square. '?' = unresolved foreground.
All error/quality values describe template matching, never probabilities.
The existing stage-3 GUI adapter is intentionally not changed by this module.
"""
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from .board_locator_2d import RecognitionError, extract_position
from .notation import placement_of
from .recognizer import MASK, PIECES, _profile_bank, _smooth, template_bank
from .theme_profiles import load_profile
from .overlay_guard import OverlayGuard

ENGINE_VERSION = 'square-matching-v2-overlay-review'


@dataclass(frozen=True)
class RecognitionSettings:
    empty_max_rmse: float = .018
    foreground_contrast: float = .10
    max_empty_foreground_fraction: float = .001
    max_template_error: float = .105
    min_piece_margin: float = .018

    def __post_init__(self):
        for name, value in asdict(self).items():
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise RecognitionError(name + ' must be finite and between 0 and 1')
        if min(self.empty_max_rmse, self.foreground_contrast, self.max_template_error) == 0:
            raise RecognitionError('Error and contrast thresholds must be greater than zero')


@dataclass(frozen=True)
class SquarePrediction:
    piece: str | None
    decision: str
    reason: str
    match_quality: float
    foreground_fraction: float
    empty_rmse: float
    background_rgb: tuple[int, int, int]
    best_piece: str | None = None
    best_error: float | None = None
    second_piece: str | None = None
    second_error: float | None = None
    margin: float | None = None
    alignment: dict | None = None
    overlay_pixels: int = 0


class Recognizer2D:
    """Compile templates once and reuse them across a screenshot collection."""
    def __init__(self, profile=None, *, settings=None):
        self.profile = load_profile(profile) if profile is not None else None
        if settings is None and self.profile is not None:
            stored = self.profile.metadata['preprocessing']
            settings = RecognitionSettings(max_template_error=stored['max_match_error'],
                                           min_piece_margin=stored['min_match_margin'])
        self.settings = settings or RecognitionSettings()
        self.bank = _profile_bank(self.profile) if self.profile is not None else template_bank()
        self.overlay_guard = OverlayGuard(self.profile)
        stored = self.profile.metadata['preprocessing'] if self.profile is not None else {}
        sizes, shifts = stored.get('template_sizes', [62, 64, 66]), stored.get('shifts', [-1, 0, 1])
        self.variants = [dict(template_size=size, dx=dx, dy=dy)
                         for code in PIECES for size in sizes for dx in shifts for dy in shifts]
        self.profile_fingerprint = (hashlib.sha256(self.profile.path.read_bytes()).hexdigest()
                                    if self.profile is not None else None)

    @property
    def identity(self):
        dependency_names = ('recognizer.py', 'theme_profiles.py', 'board_locator_2d.py', 'overlay_guard.py')
        dependencies = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                        for name in dependency_names}
        return dict(version=ENGINE_VERSION, code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    dependency_sha256=dependencies,
                    profile_name=self.profile.name if self.profile else 'Bundled Cburnett',
                    profile_sha256=self.profile_fingerprint, settings=asdict(self.settings),
                    score_meaning='Match quality and normalized pixel error; not probabilities')

    @property
    def calibration_pixels_sha256(self):
        if self.profile is None:
            return None
        with Image.open(self.profile.path.parent / 'reference_board.png') as image:
            return hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()

    def predict_square(self, crop):
        if crop.size != (64, 64):
            raise RecognitionError('Square recognition requires a normalized 64×64 crop')
        observed = np.asarray(crop.convert('RGB'), dtype=np.float32) / 255
        rim = np.concatenate((observed[:3].reshape(-1, 3), observed[-3:].reshape(-1, 3),
                              observed[:, :3].reshape(-1, 3), observed[:, -3:].reshape(-1, 3)))
        background = np.median(rim, axis=0)
        pixels = observed[MASK]
        delta = pixels - background
        empty_rmse = float(np.sqrt(np.mean(delta * delta)))
        foreground = float(np.mean(np.max(np.abs(delta), axis=1) >= self.settings.foreground_contrast))
        background_rgb = tuple(int(round(float(v) * 255)) for v in background)
        overlay_pixels = self.overlay_guard.inspect(observed, background)
        # Empty is a separate positive decision. A failed template comparison
        # can NEVER reach this return statement and become "empty".
        if (empty_rmse <= self.settings.empty_max_rmse
                and foreground <= self.settings.max_empty_foreground_fraction):
            if overlay_pixels:
                return SquarePrediction('?', 'unknown', 'possible_overlay', 0., foreground,
                                        empty_rmse, background_rgb, overlay_pixels=overlay_pixels)
            quality = max(0., 1 - empty_rmse / self.settings.empty_max_rmse)
            return SquarePrediction(None, 'empty', 'uniform_background', quality, foreground,
                                    empty_rmse, background_rgb)
        if self.profile is None:
            rgb, alpha, owners = self.bank
            expected = rgb + background * (1 - alpha)
            errors = np.sqrt(np.mean((expected - _smooth(observed)[MASK][None]) ** 2, axis=(1, 2)))
        else:
            rgb, core, outside, owners = self.bank
            foreground_errors = np.mean((rgb - pixels[None]) ** 2, axis=2)
            background_errors = np.mean(delta * delta, axis=1)
            stored = self.profile.metadata['preprocessing']
            errors = np.sqrt(stored['foreground_weight'] * np.sum(foreground_errors * core, axis=1)
                             + stored['outside_weight'] * np.sum(background_errors[None] * outside, axis=1))
        # Compete distinct piece labels, not two augmentations of the same icon.
        winning_indices = {code: min((i for i, owner in enumerate(owners) if owner == code),
                                    key=lambda i: errors[i]) for code in PIECES}
        ordered = sorted(PIECES, key=lambda code: errors[winning_indices[code]])
        best, second = ordered[:2]
        index = winning_indices[best]
        best_error, second_error = float(errors[index]), float(errors[winning_indices[second]])
        margin = second_error - best_error
        if best_error >= self.settings.max_template_error:
            label, decision, reason = '?', 'unknown', 'poor_template_match'
        elif margin <= self.settings.min_piece_margin:
            label, decision, reason = '?', 'unknown', 'ambiguous_piece_match'
        else:
            label, decision, reason = best, 'piece', 'accepted_template_match'
        if overlay_pixels and decision == 'piece':
            label, decision, reason = '?', 'unknown', 'possible_overlay'
        quality = (min(.99, max(0., 1 - best_error / self.settings.max_template_error), margin / .06)
                   if decision == 'piece' else 0.)
        return SquarePrediction(label, decision, reason, float(quality), foreground, empty_rmse,
                                background_rgb, best, best_error, second, second_error, margin,
                                self.variants[index], overlay_pixels)

    def predict(self, image, *, white_bottom, rect=None):
        extraction = extract_position(image, rect=rect, white_bottom=white_bottom)
        predictions = {cell.square: self.predict_square(cell.image) for cell in extraction.squares}
        pieces = {square: prediction.piece for square, prediction in predictions.items()}
        result = dict(pieces=pieces, match_quality={s: p.match_quality for s, p in predictions.items()},
                      details={s: asdict(p) for s, p in predictions.items()},
                      placement=placement_of(pieces), engine=self.identity,
                      unknown_squares=sum(p == '?' for p in pieces.values()),
                      known_empty_squares=sum(p is None for p in pieces.values()),
                      overlay_squares=[s for s, p in predictions.items() if p.overlay_pixels],
                      normalized_pixels_sha256=hashlib.sha256(extraction.board.tobytes()).hexdigest())
        return result, extraction


def save_diagnostics(result, extraction, output_dir, *, truth=None):
    """Save the actual normalized input and prediction/truth comparison sheet."""
    import json
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    extraction.board.save(directory / 'board.png')
    sheet = Image.new('RGB', (8 * 100, 8 * 116), '#dddddd')
    draw = ImageDraw.Draw(sheet)
    for cell in extraction.squares:
        square = cell.square
        detail = result['details'][square]
        label = result['pieces'][square]
        x, y = cell.column * 100, cell.row * 116
        sheet.paste(cell.image, (x + 18, y))
        color = '#a65e00' if label == '?' else '#215f22'
        if truth is not None and label != '?' and label != truth[square]:
            color = '#b00020'
        draw.text((x + 2, y + 66), f'{square}: {label or "empty"}', fill=color)
        if truth is not None:
            draw.text((x + 2, y + 78), f'truth: {truth[square] or "empty"}', fill='black')
        if detail['best_error'] is not None:
            draw.text((x + 2, y + 90), f'err {detail["best_error"]:.3f}', fill='black')
            draw.text((x + 2, y + 102), f'gap {detail["margin"]:.3f}', fill='black')
    sheet.save(directory / 'square_sheet.png')
    (directory / 'predictions.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
