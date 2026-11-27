"""Propose complete, axis-aligned 8x8 boards for explicit user review.

Detection uses continuous RGB boundary evidence, floating-point grid spacing,
multiple resolutions, and original-image refinement. No piece/theme model is
needed. A grid-fit score is a heuristic, never a probability or confirmation.
"""
from collections import Counter
from dataclasses import dataclass
import math
import numpy as np
from PIL import Image, ImageFilter
from .board_locator_2d import BoardRect, RecognitionError


@dataclass(frozen=True)
class BoardProposal:
    rectangle: BoardRect
    grid_fit: float


@dataclass(frozen=True)
class ProposalResult:
    request_id: int
    proposals: tuple[BoardProposal, ...]


# Work is bounded even when the source is a large desktop screenshot.
SEARCH_SIZES = (960, 1600)
MAX_AXIS_CANDIDATES = 100
MAX_GRID_CANDIDATES = 240
MAX_REFINEMENTS = 12
PARITY = np.indices((8, 8)).sum(axis=0) % 2
# Several small corner regions avoid most piece bodies and coordinate labels.
OFFSETS = np.array([(.13, .13), (.13, .87), (.87, .13), (.87, .87)])


def _line_edges(row):
    """Collapse an antialiased transition into one boundary, not extra colours."""
    strength = np.linalg.norm(np.diff(row.astype(np.float32), axis=0), axis=1)
    active = np.flatnonzero(strength >= 5.)
    if not active.size:
        return np.array([0., float(len(row))])
    # One weak pixel inside a transition must not split it into two edges.
    cuts = np.flatnonzero(np.diff(active) > 2) + 1
    groups = np.split(active, cuts)
    centers = [float(np.average(g + 1., weights=strength[g])) for g in groups]
    return np.r_[0., centers, float(len(row))]


def _axis_votes(rgb, minimum_pitch=4.):
    """Vote for grid intervals from similarly spaced boundary groups.

    Coordinates and pitch stay fractional until they are clustered for voting.
    Three intact cells are enough to seed a candidate; both-axis verification
    later checks the whole board. Pieces can interrupt the other scanlines.
    """
    height, width = rgb.shape[:2]
    votes = Counter()
    totals = {}
    for y in np.unique(np.linspace(0, height - 1, min(height, 120)).astype(int)):
        edges = _line_edges(rgb[y])
        lengths = np.diff(edges)
        seen = set()  # One scanline contributes at most one vote per interval.
        for i in range(len(lengths) - 2):
            sizes = lengths[i:i + 3]
            pitch = float(np.mean(sizes))
            if pitch < minimum_pitch or np.ptp(sizes) > max(1.5, pitch * .12):
                continue
            # Least-squares fit to four boundaries, rather than one run width.
            points = edges[i:i + 4]
            pitch = float(np.dot(points - points.mean(), [-1.5, -.5, .5, 1.5]) / 5.)
            start = float(points.mean() - 1.5 * pitch)
            for offset in range(6):
                left, side = start - offset * pitch, 8 * pitch
                if left < -2 or left + side > width + 2:
                    continue
                left = max(0., left)
                side = min(side, width - left)
                key = round(left / 2), round(side / 2)
                if key in seen:
                    continue
                seen.add(key)
                votes[key] += 1
                old = totals.get(key, (0., 0.))
                totals[key] = old[0] + left, old[1] + side
    return [(totals[key][0] / n, totals[key][1] / n, n)
            for key, n in votes.most_common(MAX_AXIS_CANDIDATES)]


def _cell_samples(rgb, left, top, width, height, rows=None, columns=None):
    rows = np.arange(8) if rows is None else np.asarray(rows)
    columns = np.arange(8) if columns is None else np.asarray(columns)
    yy = top + (rows[:, None, None] + OFFSETS[None, None, :, 0]) * height / 8
    xx = left + (columns[None, :, None] + OFFSETS[None, None, :, 1]) * width / 8
    yy, xx = np.broadcast_arrays(yy, xx)
    valid = (yy >= 0) & (yy < rgb.shape[0]) & (xx >= 0) & (xx < rgb.shape[1])
    pixels = rgb[np.clip(yy.astype(int), 0, rgb.shape[0]-1),
                 np.clip(xx.astype(int), 0, rgb.shape[1]-1)]
    return np.median(pixels, axis=2).astype(float), valid.all(axis=2)


def _appearance(rgb, left, top, width, height):
    samples, valid = _cell_samples(rgb, left, top, width, height)
    if not valid.all():
        return 0., np.zeros((2, 3)), 0.
    colors = np.array([np.median(samples[PARITY == p], axis=0) for p in (0, 1)])
    contrast = float(np.linalg.norm(colors[0] - colors[1]))
    if contrast < 10.:  # Reject near-uniform panels, without fixed colour bins.
        return 0., colors, contrast
    distances = np.linalg.norm(samples - colors[PARITY], axis=2)
    fit = float(np.mean(np.clip(1 - distances / max(8., min(65., contrast * .65)), 0, 1)))
    return fit, colors, contrast


def _grid_fit(rgb, left, top, side):
    """Compatibility helper: appearance alone is insufficient for acceptance."""
    return _appearance(rgb, left, top, side, side)[0]


def _iou(a, b):
    x, y, w, h = a
    xx, yy, ww, hh = b
    area = max(0., min(x+w, xx+ww)-max(x, xx)) * max(0., min(y+h, yy+hh)-max(y, yy))
    return area / max(1., w*h + ww*hh - area)


def _view_candidates(rgb, minimum_pitch):
    xs = _axis_votes(rgb, minimum_pitch)
    ys = _axis_votes(rgb.transpose(1, 0, 2), minimum_pitch)
    grids = []
    for x, width, vx in xs:
        for y, height, vy in ys:
            if abs(width - height) > max(3., max(width, height) * .025):
                continue
            grids.append((vx + vy, x, y, width, height))
    scored = []
    for votes, x, y, w, h in sorted(grids, reverse=True)[:MAX_GRID_CANDIDATES]:
        fit, _, _ = _appearance(rgb, x, y, w, h)
        if fit >= .72:
            scored.append((fit, votes, x, y, w, h))
    chosen = []
    for fit, votes, x, y, w, h in sorted(scored, reverse=True):
        rect = (x, y, w, h)
        if any(_iou(rect, other[1]) > .75 for other in chosen):
            continue
        chosen.append((fit, rect))
        if len(chosen) == MAX_REFINEMENTS:
            break
    return chosen


def _refine_axis(rgb, origin, cross_origin, length, cross_length, contrast):
    """Fit the seven internal boundaries using many original-image scanlines."""
    pitch = length / 8
    lo = max(0, int(math.floor(origin - pitch * .15 - 3)))
    hi = min(rgb.shape[1], int(math.ceil(origin + length + pitch * .15 + 3)))
    ys = cross_origin + (np.arange(8)[:, None] + np.array([.16, .28, .72, .84])) * cross_length / 8
    ys = np.clip(ys.astype(int).ravel(), 0, rgb.shape[0]-1)
    strip = rgb[ys, lo:hi].astype(np.float32)
    # A median across scanlines resists pieces, arrows and text on some squares.
    profile = np.median(np.linalg.norm(np.diff(strip, axis=1), axis=2), axis=0)
    if len(profile) < 3:
        return None
    # Sum a narrow neighbourhood to include a resampled boundary's full ramp.
    # The neighbourhood cannot exceed half a square on tiny inputs.
    radius = min(2, max(0, int(pitch / 8)))
    padded = np.pad(profile, (radius, radius))
    energy = sum(padded[i:i + len(profile)] for i in range(2 * radius + 1))
    positions, indices, qualities = [], [], []
    search = max(3., pitch * .09)
    for k in range(1, 8):
        predicted = origin + k * pitch
        a = max(0, int(math.floor(predicted - search)) - lo - 1)
        b = min(len(energy), int(math.ceil(predicted + search)) - lo)
        if a >= b:
            continue
        best = float(np.max(energy[a:b]))
        if best < max(5., contrast * .22):
            continue
        peaks = np.flatnonzero(energy[a:b] >= best * .98) + a
        peak = int(peaks[np.argmin(abs(peaks + lo + 1 - predicted))])
        # Refine to the centre of the raw edge ramp, not a smoothing plateau.
        low, high = max(0, peak-radius), min(len(profile), peak+radius+1)
        weights = profile[low:high]
        position = float(np.average(np.arange(low, high) + lo + 1, weights=weights))
        positions.append(position)
        indices.append(k)
        qualities.append(min(1., best / max(10., contrast * .65)))
    if len(indices) < 5:
        return None
    indices = np.asarray(indices, dtype=float)
    positions = np.asarray(positions)
    # Remove a piece/text peak that happened to land near one predicted line.
    slopes = [(positions[j]-positions[i])/(indices[j]-indices[i])
              for i in range(len(indices)) for j in range(i+1, len(indices))]
    fitted_pitch = float(np.median(slopes))
    fitted_origin = float(np.median(positions - indices * fitted_pitch))
    good = abs(positions - (fitted_origin + indices*fitted_pitch)) <= max(1.5, pitch*.025)
    if np.count_nonzero(good) < 5:
        return None
    ii, pp = indices[good], positions[good]
    fitted_pitch = float(np.dot(ii-ii.mean(), pp-pp.mean()) / np.sum((ii-ii.mean())**2))
    fitted_origin = float(pp.mean() - ii.mean()*fitted_pitch)
    quality = float(np.sum(np.asarray(qualities)[good]) / 7)
    return fitted_origin, 8*fitted_pitch, quality


def _continues_outside(rgb, rect, colors, contrast):
    """Reject an internal 8x8 window of a larger repeating checkerboard."""
    x, y, w, h = rect
    tolerance = max(8., min(45., contrast * .35))
    for rows, columns in ((range(8), [-1]), (range(8), [8]), ([-1], range(8)), ([8], range(8))):
        samples, valid = _cell_samples(rgb, x, y, w, h, rows, columns)
        parity = (np.array(list(rows))[:, None] + np.array(list(columns))[None, :]) % 2
        matches = (np.linalg.norm(samples - colors[parity], axis=2) <= tolerance) & valid
        if np.count_nonzero(valid) >= 6 and np.count_nonzero(matches) >= 6:
            return True
    return False


def _refine_candidate(rgb, rect):
    x, y, w, h = rect
    _, _, contrast = _appearance(rgb, x, y, w, h)
    if contrast < 10.:
        return None
    horizontal = _refine_axis(rgb, x, y, w, h, contrast)
    vertical = _refine_axis(rgb.transpose(1, 0, 2), y, x, h, w, contrast)
    if horizontal is None or vertical is None:
        return None
    x, w, gx = horizontal
    y, h, gy = vertical
    # Independent spacing estimates permit pixel rounding, not stretched boards.
    if abs(w - h) > max(2., max(w, h)*.01):
        return None
    x, y, w, h = round(x), round(y), round(w), round(h)
    # Boundary fitting may overshoot an image edge by a fraction of a pixel.
    if x < -1 or y < -1 or x+w > rgb.shape[1]+1 or y+h > rgb.shape[0]+1:
        return None
    x, y = max(0, x), max(0, y)
    w, h = min(w, rgb.shape[1]-x), min(h, rgb.shape[0]-y)
    if min(w, h) < 128:
        return None
    fit, colors, contrast = _appearance(rgb, x, y, w, h)
    if fit < .76 or _continues_outside(rgb, (x, y, w, h), colors, contrast):
        return None
    score = .65 * fit + .35 * min(gx, gy)
    if score < .78:
        return None
    return BoardProposal(BoardRect(x, y, w, h).checked((rgb.shape[1], rgb.shape[0])), float(score))


def propose_boards(image, *, limit=3):
    if type(limit) is not int or not 1 <= limit <= 5:
        raise RecognitionError('Proposal limit must be an integer from 1 to 5')
    if min(image.size) < 128 or image.width * image.height > 60_000_000:
        return ()
    source = image.convert('RGB')
    original = np.asarray(source)
    candidates = []
    previous_size = None
    for bound in SEARCH_SIZES:
        scale = min(1., bound / max(source.size))
        size = (max(1, round(source.width*scale)), max(1, round(source.height*scale)))
        if size == previous_size:
            continue
        previous_size = size
        small = source.resize(size, Image.Resampling.LANCZOS).filter(ImageFilter.MedianFilter(3))
        rgb = np.asarray(small)
        if min(size) < 28:
            continue
        # This minimum is in source pixels; it no longer depends on UI panels.
        minimum_pitch = max(3.5, 128 * scale / 8 * .9)
        for fit, (x, y, w, h) in _view_candidates(rgb, minimum_pitch):
            sx, sy = source.width/size[0], source.height/size[1]
            rect = (x*sx, y*sy, w*sx, h*sy)
            candidates.append(rect)
    verified = []
    for rect in candidates:
        if any(_iou(rect, (p.rectangle.left, p.rectangle.top, p.rectangle.width, p.rectangle.height)) > .85
               for p in verified):
            continue
        proposal = _refine_candidate(original, rect)
        if proposal is not None:
            verified.append(proposal)
    result = []
    for proposal in sorted(verified, key=lambda p: (-p.grid_fit, p.rectangle.top, p.rectangle.left)):
        rect = proposal.rectangle
        if any(_iou((rect.left, rect.top, rect.width, rect.height),
                    (p.rectangle.left, p.rectangle.top, p.rectangle.width, p.rectangle.height)) > .6 for p in result):
            continue
        result.append(proposal)
        if len(result) == limit:
            break
    return tuple(result)


def proposal_document(proposals, request_id):
    return dict(version=1, request_id=request_id, proposals=[
        dict(rect=[p.rectangle.left, p.rectangle.top, p.rectangle.width, p.rectangle.height],
             grid_fit=p.grid_fit) for p in proposals])


def parse_proposals(raw, request_id, image_size):
    """Validate process output before placing any rectangle in the editor."""
    import json
    try:
        data = json.loads(raw)
        if (not isinstance(data, dict) or data.get('version') != 1
                or type(data.get('request_id')) is not int or data['request_id'] != request_id
                or not isinstance(data.get('proposals'), list) or len(data['proposals']) > 5):
            raise ValueError('Invalid or stale board proposals')
        proposals = []
        for item in data['proposals']:
            rect = BoardRect(*item['rect']).checked(image_size)
            score = item['grid_fit']
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError('Invalid grid-fit score')
            proposals.append(BoardProposal(rect, score))
        return ProposalResult(request_id, tuple(proposals))
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise RecognitionError('Invalid board proposal response: ' + str(error)) from error
