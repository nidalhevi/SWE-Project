"""Conservative pixel-template matching for the Cburnett piece set.

Templates have transparent backgrounds. Each candidate is composited over the
observed square background, so the same piece can match light, dark, and uniform
last-move highlights. Small scale and alignment variations absorb resampling.
Scores are match quality, NOT calibrated probabilities of chess correctness.
"""
from functools import lru_cache
from pathlib import Path
import numpy as np
from PIL import Image
from .board_locator import extract_board, square_crops

PIECES = 'PNBRQKpnbrqk'
SIZE = 64
ASSET_DIR = Path(__file__).parent / 'assets' / 'cburnett'


def _comparison_mask():
    mask = np.ones((SIZE, SIZE), dtype=bool)
    mask[:2] = mask[-2:] = False
    mask[:, :2] = mask[:, -2:] = False
    # Lichess can draw coordinates in the corners of edge squares.
    for rows in (slice(0, 11), slice(-11, None)):
        for cols in (slice(0, 11), slice(-11, None)):
            mask[rows, cols] = False
    return mask


MASK = _comparison_mask()


def _smooth(array):
    """Small separable Gaussian approximation for browser antialiasing changes."""
    padded = np.pad(array, ((1, 1), (0, 0), (0, 0)), mode='edge')
    array = (padded[:-2] + 2 * padded[1:-1] + padded[2:]) / 4
    padded = np.pad(array, ((0, 0), (1, 1), (0, 0)), mode='edge')
    return (padded[:, :-2] + 2 * padded[:, 1:-1] + padded[:, 2:]) / 4


@lru_cache(maxsize=1)
def template_bank():
    """Read bundled PNGs once per worker; no runtime downloads or SVG library."""
    images, alphas, owners = [], [], []
    for code in PIECES:
        name = ('w' if code.isupper() else 'b') + code.upper() + '.png'
        with Image.open(ASSET_DIR / name) as image:
            rgba = image.convert('RGBA')
        for size in (62, 64, 66):
            tile = rgba.resize((size, size), Image.Resampling.LANCZOS)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    canvas = Image.new('RGBA', (SIZE, SIZE))
                    # alpha_composite clips safely; it does not wrap edges like roll.
                    canvas.alpha_composite(tile, ((SIZE - size) // 2 + dx, (SIZE - size) // 2 + dy))
                    values = np.asarray(canvas, dtype=np.float32) / 255
                    alpha = values[:, :, 3:4]
                    images.append(_smooth(values[:, :, :3] * alpha)[MASK])
                    alphas.append(_smooth(alpha)[MASK])
                    owners.append(code)
    return np.stack(images), np.stack(alphas), tuple(owners)


def _profile_bank(profile):
    """Foreground/core and definite-background weights for calibrated icons.

    No sampled board pixels enter the foreground term. A dilated support mask
    excludes antialiased boundaries from both terms.
    """
    from PIL import ImageFilter
    settings = profile.metadata['preprocessing']
    images, cores, outsides, owners = [], [], [], []
    for code in PIECES:
        template = profile.templates[code]
        raw = np.array(template.raw.convert('RGBA'))
        raw[:, :, 3] = np.asarray(template.core)
        isolated = Image.fromarray(raw)
        for size in settings['template_sizes']:
            icon = isolated.resize((size, size), Image.Resampling.LANCZOS)
            support = template.support.resize((size, size), Image.Resampling.NEAREST)
            for dx in settings['shifts']:
                for dy in settings['shifts']:
                    offset = ((64 - size) // 2 + dx, (64 - size) // 2 + dy)
                    canvas = Image.new('RGBA', (64, 64))
                    canvas.alpha_composite(icon, offset)
                    silhouette = Image.new('L', (64, 64))
                    silhouette.paste(support, offset)
                    expanded = np.asarray(silhouette.filter(ImageFilter.MaxFilter(2 * settings['support_dilation'] + 1))) > 0
                    array = np.asarray(canvas, dtype=np.float32) / 255
                    core = (array[:, :, 3] > .99) & MASK
                    outside = ~expanded & MASK
                    if core.sum() < 10 or outside.sum() < 10:
                        raise ValueError('Profile has an unusable foreground mask for ' + code)
                    images.append(array[:, :, :3][MASK])
                    cores.append(core[MASK].astype(np.float32) / core.sum())
                    outsides.append(outside[MASK].astype(np.float32) / outside.sum())
                    owners.append(code)
    return np.stack(images), np.stack(cores), np.stack(outsides), tuple(owners)


def classify_square(crop, *, profile=None, bank=None):
    """Return accepted label/unknown, match quality, and diagnostic measurements."""
    observed = np.asarray(crop.convert('RGB'), dtype=np.float32) / 255
    # Piece artwork leaves the outside rim clear. A median rejects the small
    # coordinate letters; uniform highlights are treated as background colors.
    rim = np.concatenate((observed[:3].reshape(-1, 3), observed[-3:].reshape(-1, 3),
                          observed[:, :3].reshape(-1, 3), observed[:, -3:].reshape(-1, 3)))
    background = np.median(rim, axis=0)
    pixels = observed[MASK]
    delta = pixels - background
    empty_error = float(np.sqrt(np.mean(delta * delta)))
    foreground = float(np.mean(np.max(np.abs(delta), axis=1) > .16))
    # Declare empty only when there is strong evidence of an empty square.
    # A failed piece match must never silently turn into an empty-square label.
    if empty_error < .025 and foreground < .006:
        return None, .98, dict(label=None, error=empty_error, margin=None, foreground=foreground)
    if profile is None:
        rgb, alpha, owners = template_bank()
        expected = rgb + background * (1 - alpha)
        pixels = _smooth(observed)[MASK]
        errors = np.sqrt(np.mean((expected - pixels[None, :, :]) ** 2, axis=(1, 2)))
    else:
        rgb, core_weights, outside_weights, owners = bank if bank is not None else _profile_bank(profile)
        foreground_error = np.mean((rgb - pixels[None]) ** 2, axis=2)
        background_error = np.mean((pixels - background) ** 2, axis=1)
        settings = profile.metadata['preprocessing']
        errors = np.sqrt(settings['foreground_weight'] * np.sum(foreground_error * core_weights, axis=1)
                         + settings['outside_weight'] * np.sum(background_error[None] * outside_weights, axis=1))
    scores = {code: float(np.min(errors[[i for i, owner in enumerate(owners) if owner == code]]))
              for code in PIECES}
    ranked = sorted(scores, key=scores.get)
    best, second = ranked[:2]
    error, margin = scores[best], scores[second] - scores[best]
    # Global fit rejects unsupported themes and substantial overlaid arrows.
    # The gap rejects ambiguous nearest-neighbor assignments.
    max_error = profile.metadata['preprocessing']['max_match_error'] if profile is not None else .105
    min_margin = profile.metadata['preprocessing']['min_match_margin'] if profile is not None else .018
    accepted = error < max_error and margin > min_margin
    quality = float(min(.99, max(0, 1 - error / .20), margin / .06)) if accepted else 0.0
    return best if accepted else '?', quality, dict(
        label=best, error=error, margin=margin, foreground=foreground,
        candidates=[dict(piece=code, error=scores[code]) for code in ranked[:3]])


def recognize_board(image, *, white_bottom, rect=None, profile=None):
    if profile is not None:
        from .theme_profiles import load_profile
        profile = load_profile(profile)
    bank = _profile_bank(profile) if profile is not None else None
    board = extract_board(image, rect)
    pieces, confidence, details = {}, {}, {}
    for square, crop in square_crops(board, white_bottom):
        piece, quality, detail = classify_square(crop, profile=profile, bank=bank)
        pieces[square], confidence[square], details[square] = piece, quality, detail
    unknown = sum(piece == '?' for piece in pieces.values())
    kings_ok = list(pieces.values()).count('K') == list(pieces.values()).count('k') == 1
    profile_name = profile.name if profile is not None else 'Bundled Cburnett'
    message = f'{profile_name}: template matching complete; {unknown} unknown squares. '
    if not kings_ok:
        message += 'The draft does not contain exactly one recognized king of each color. '
    message += 'Review the pieces and enter position details. Match scores are not probabilities.'
    return dict(pieces=pieces, confidence=confidence, message=message, details=details)
