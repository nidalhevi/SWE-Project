"""Named, reviewed icon profiles calibrated from a standard starting position.

One image cannot uniquely reveal the exact alpha of every antialiased edge.
We save a conservative foreground core for matching, a larger support mask,
and an approximate RGBA cutout for review. Recognition ignores uncertain edges
instead of treating the sampled board background as part of a piece.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from .board_locator_2d import extract_position, RecognitionError
from .notation import parse_placement

PIECES = 'PNBRQKpnbrqk'
START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR'
SETTINGS = dict(version=1, board_size=512, square_size=64, background_tolerance=18,
                core_erosion=1, ignored_corners=11, ignored_rim=2,
                mask_method='background-distance-conservative-core', color_mode='RGB',
                template_sizes=[62, 64, 66], shifts=[-1, 0, 1], support_dilation=2,
                foreground_weight=.65, outside_weight=.35, max_match_error=.105, min_match_margin=.018)


def comparison_mask():
    mask = np.ones((64, 64), dtype=bool)
    mask[:2] = mask[-2:] = False
    mask[:, :2] = mask[:, -2:] = False
    for rows in (slice(0, 11), slice(-11, None)):
        for cols in (slice(0, 11), slice(-11, None)):
            mask[rows, cols] = False
    return mask


def _code_name(code):
    return ('w' if code.isupper() else 'b') + code.upper()


def _light(square):
    return ('abcdefgh'.index(square[0]) + int(square[1])) % 2 == 0


def _mask_image(mask):
    return Image.fromarray(mask.astype(np.uint8) * 255)


def _rim_color(pixels):
    rim = np.concatenate((pixels[:3].reshape(-1, 3), pixels[-3:].reshape(-1, 3),
                          pixels[:, :3].reshape(-1, 3), pixels[:, -3:].reshape(-1, 3)))
    return np.median(rim, axis=0)


def _recover_rgba(raw, background, support, core, palette):
    """Approximate mixed boundary colors against observed opaque icon colors."""
    pixels = np.asarray(raw, dtype=np.float32) / 255
    bg = background / 255
    colors = palette / 255
    vectors = colors - bg
    denom = np.sum(vectors * vectors, axis=1).clip(.001)
    delta = pixels.reshape(-1, 3)[:, None, :] - bg
    alpha = np.clip(np.sum(delta * vectors[None], axis=2) / denom[None], 0, 1)
    predicted = bg + alpha[:, :, None] * vectors[None]
    errors = np.sum((predicted - pixels.reshape(-1, 1, 3)) ** 2, axis=2)
    best = np.argmin(errors, axis=1)
    selected_alpha = alpha[np.arange(4096), best].reshape(64, 64)
    selected_colors = colors[best].reshape(64, 64, 3)
    selected_alpha[~support] = 0
    selected_alpha[core] = 1
    selected_colors[core] = pixels[core]
    rgba = np.dstack((selected_colors, selected_alpha))
    return Image.fromarray(np.uint8(np.clip(rgba * 255, 0, 255)))


@dataclass
class ProfileTemplate:
    raw: Image.Image
    support: Image.Image
    core: Image.Image
    rgba: Image.Image


@dataclass
class ThemeProfile:
    path: Path
    metadata: dict
    templates: dict[str, ProfileTemplate]
    backgrounds: dict[str, Image.Image]

    @property
    def name(self):
        return self.metadata['name']


def _manifest_path(path):
    path = Path(path).resolve()
    return path / 'profile.json' if path.is_dir() else path


def _write_manifest(path, document):
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def load_profile(path, *, require_reviewed=True):
    manifest = _manifest_path(path)
    if not manifest.is_file() or manifest.stat().st_size > 512 * 1024:
        raise RecognitionError('Choose a readable profile.json smaller than 512 KiB')
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if (not isinstance(data, dict) or data.get('version') != 1
            or data.get('preprocessing') != SETTINGS or set(data.get('pieces', {})) != set(PIECES)):
        raise RecognitionError('Unsupported or incomplete theme profile')
    if not isinstance(data.get('name'), str) or not data['name'].strip():
        raise RecognitionError('Profile needs a name')
    if type(data.get('reviewed')) is not bool:
        raise RecognitionError('Profile review status is missing')
    if require_reviewed and not data['reviewed']:
        raise RecognitionError('Profile is a draft. Review its templates and masks before approving it.')
    root = manifest.parent
    artifacts = data.get('artifacts', {})
    if not isinstance(artifacts, dict) or not artifacts:
        raise RecognitionError('Profile artifact hashes are missing')
    for relative, digest in artifacts.items():
        file = (root / relative).resolve()
        if not file.is_relative_to(root) or not file.is_file() or file.stat().st_size > 4 * 1024 * 1024:
            raise RecognitionError('Missing or invalid profile artifact: ' + relative)
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise RecognitionError('Profile artifact changed after calibration: ' + relative)

    def read_image(relative, mode):
        if relative not in artifacts:
            raise RecognitionError('Untracked profile image: ' + str(relative))
        with Image.open(root / relative) as image:
            if image.size != (64, 64):
                raise RecognitionError('Profile images must be 64×64 pixels')
            return image.convert(mode)

    templates = {}
    for code, record in data['pieces'].items():
        template = ProfileTemplate(read_image(record['raw'], 'RGB'), read_image(record['support'], 'L'),
                                   read_image(record['core'], 'L'), read_image(record['rgba'], 'RGBA'))
        core, support = np.asarray(template.core) > 127, np.asarray(template.support) > 127
        if core.sum() < 30 or (core & ~support).any():
            raise RecognitionError('Empty or inconsistent foreground mask for ' + code)
        templates[code] = template
    backgrounds = {kind: read_image(data['backgrounds'][kind]['image'], 'RGB') for kind in ('light', 'dark')}
    return ThemeProfile(manifest, data, templates, backgrounds)


def approve_profile(path):
    """Call only after the user has inspected the concrete review images."""
    profile = load_profile(path, require_reviewed=False)
    profile.metadata['reviewed'] = True
    profile.metadata['reviewed_at'] = datetime.now(timezone.utc).isoformat()
    _write_manifest(profile.path, profile.metadata)
    return profile.path


def _make_review(root, records, backgrounds):
    width, row_height = 560, 88
    sheet = Image.new('RGB', (width, 36 + 12 * row_height), '#dddddd')
    draw = ImageDraw.Draw(sheet)
    for x, text in ((10, 'Code / square'), (120, 'Raw sample'), (215, 'Support mask'),
                    (315, 'Core mask'), (410, 'On light'), (490, 'On dark')):
        draw.text((x, 10), text, fill='black')
    for row, code in enumerate(PIECES):
        y = 36 + row * row_height
        record = records[code]
        draw.text((10, y + 24), code + ' / ' + record['sample_square'], fill='black')
        for x, key in ((120, 'raw'), (215, 'support'), (315, 'core')):
            with Image.open(root / record[key]) as image:
                sheet.paste(image.convert('RGB'), (x, y))
        with Image.open(root / record['rgba']) as rgba:
            for x, kind in ((410, 'light'), (490, 'dark')):
                tile = Image.new('RGBA', (64, 64), tuple(backgrounds[kind]['color']) + (255,))
                tile.alpha_composite(rgba.convert('RGBA'))
                sheet.paste(tile.convert('RGB'), (x, y))
    sheet.save(root / 'template_review.png')


def create_profile(image, *, name, output_dir, white_bottom, rect=None, source_name=None):
    name = name.strip()
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        raise RecognitionError('Use a profile name of 1..80 printable characters')
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise RecognitionError('Choose a new output folder; existing profiles are never overwritten')
    extraction = extract_position(image, rect=rect, white_bottom=white_bottom)
    cells, truth, valid = extraction.by_square, parse_placement(START), comparison_mask()
    empty_groups = {kind: [np.asarray(cells[s], dtype=np.float32) for s, p in truth.items()
                          if p is None and ('light' if _light(s) else 'dark') == kind]
                    for kind in ('light', 'dark')}
    backgrounds = {}
    for kind, crops in empty_groups.items():
        color = np.median(np.concatenate([crop[valid] for crop in crops]), axis=0)
        for crop in crops:
            residual = np.sqrt(np.mean((crop[valid] - color) ** 2))
            if residual > 10:
                raise RecognitionError('Expected empty ' + kind + ' squares are not uniform. '
                                       'Use a clean standard starting position without highlights or arrows.')
        empty_squares = [s for s, p in truth.items() if p is None
                         and ('light' if _light(s) else 'dark') == kind]
        backgrounds[kind] = dict(color=[int(round(v)) for v in color], image=f'backgrounds/{kind}.png',
                                 model_image=f'backgrounds/{kind}_model.png', sample_square=empty_squares[0],
                                 examples=empty_squares)
    candidates = {code: [] for code in PIECES}
    palette_pixels = []
    for square, code in truth.items():
        if code is None:
            continue
        raw = cells[square]
        pixels = np.asarray(raw, dtype=np.float32)
        background = np.array(backgrounds['light' if _light(square) else 'dark']['color'], dtype=np.float32)
        if np.max(np.abs(_rim_color(pixels) - background)) > 15:
            raise RecognitionError('Unexpected background on ' + square + '; check crop alignment and remove highlights')
        support = (np.max(np.abs(pixels - background), axis=2) > SETTINGS['background_tolerance']) & valid
        core = np.asarray(_mask_image(support).filter(ImageFilter.MinFilter(3))) > 127
        if not .035 < support.mean() < .75 or core.sum() < 30:
            raise RecognitionError('No reliable piece foreground on ' + square + '; check the starting position and grid')
        candidates[code].append((square, raw, support, core, background))
        palette_pixels.append(pixels[core])
    all_colors = np.concatenate(palette_pixels)
    quantized = np.uint8(np.clip(np.round(all_colors / 16) * 16, 0, 255))
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    palette = colors[np.argsort(counts)[-24:]].astype(np.float32)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.profile-draft-', dir=destination.parent))
    try:
        (staging / 'backgrounds').mkdir()
        (staging / 'templates').mkdir()
        (staging / 'samples').mkdir()
        extraction.board.save(staging / 'reference_board.png')
        for kind, record in backgrounds.items():
            cells[record['sample_square']].save(staging / record['image'])
            Image.new('RGB', (64, 64), tuple(record['color'])).save(staging / record['model_image'])
        records = {}
        for code, examples in candidates.items():
            for square, raw, support, core, bg in examples:
                raw.save(staging / 'samples' / (square + '.png'))
            square, raw, support, core, bg = max(examples, key=lambda example: example[3].sum())
            stem = 'templates/' + _code_name(code)
            record = dict(raw=stem + '_raw.png', support=stem + '_support.png',
                          core=stem + '_core.png', rgba=stem + '.png', sample_square=square,
                          examples=[s for s, *_ in examples], foreground_fraction=float(support.mean()))
            raw.save(staging / record['raw'])
            _mask_image(support).save(staging / record['support'])
            _mask_image(core).save(staging / record['core'])
            _recover_rgba(raw, bg, support, core, palette).save(staging / record['rgba'])
            records[code] = record
        _make_review(staging, records, backgrounds)
        artifacts = {str(p.relative_to(staging)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(staging.rglob('*.png'))}
        document = dict(version=1, name=name, reviewed=False, created_at=datetime.now(timezone.utc).isoformat(),
                        preprocessing=SETTINGS, reference=dict(source_name=source_name, white_bottom=white_bottom,
                        source_size=extraction.source_size, rectangle=dict(left=extraction.rectangle.left,
                        top=extraction.rectangle.top, width=extraction.rectangle.width, height=extraction.rectangle.height),
                        original_square_size=[extraction.rectangle.width / 8, extraction.rectangle.height / 8]),
                        pieces=records, backgrounds=backgrounds, artifacts=artifacts,
                        edge_note='RGBA edges are estimates; matching uses opaque core and excludes uncertain boundaries.')
        _write_manifest(staging / 'profile.json', document)
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return load_profile(destination, require_reviewed=False)
