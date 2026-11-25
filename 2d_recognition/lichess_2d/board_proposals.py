"""Bounded checkerboard proposals. A fit score is not a probability or consent.

Look for repeated alternating flat runs, then test both axes against 64 cells.
The user must confirm the grid. Piece art, orientation and FEN are not inferred.
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


def _axis_votes(pixels):
    """Estimate whole-board intervals from three equal alternating color runs."""
    height, width = pixels.shape
    votes = Counter()
    for y in range(0, height, max(1, height // 150)):
        row = pixels[y]
        edges = np.r_[0, np.flatnonzero(row[1:] != row[:-1]) + 1, width]
        lengths = np.diff(edges)
        for i in range(len(lengths) - 2):
            sizes = lengths[i:i + 3]
            size = int(round(float(np.median(sizes))))
            if size < 16 or max(sizes) - min(sizes) > max(2, size * .12):
                continue
            a, b, c = (int(row[edges[i + j]]) for j in range(3))
            if a != c or a == b:
                continue
            for offset in range(6):
                left, side = int(edges[i] - offset * size), 8 * size
                if 0 <= left and left + side <= width:
                    votes[left, side] += 1
    return votes.most_common(100)


def _grid_fit(rgb, left, top, side):
    # Four corner-adjacent probes per cell generally avoid the icon itself.
    samples = []
    for row in range(8):
        for column in range(8):
            points = [rgb[min(rgb.shape[0]-1, int(top + (row + fy) * side / 8)),
                          min(rgb.shape[1]-1, int(left + (column + fx) * side / 8))]
                      for fy in (.12, .88) for fx in (.12, .88)]
            samples.append(np.median(points, axis=0))
    samples = np.array(samples, dtype=float)
    parity = np.array([(r + c) % 2 for r in range(8) for c in range(8)])
    colors = np.array([np.median(samples[parity == p], axis=0) for p in (0, 1)])
    contrast = np.linalg.norm(colors[0] - colors[1])
    if contrast < 28:
        return 0.
    distances = np.linalg.norm(samples - colors[parity], axis=1)
    return float(np.mean(np.clip(1 - distances / min(65, contrast * .65), 0, 1)))


def propose_boards(image, *, limit=3):
    if type(limit) is not int or not 1 <= limit <= 5:
        raise RecognitionError('Proposal limit must be an integer from 1 to 5')
    if min(image.size) < 128 or image.width * image.height > 60_000_000:
        return ()
    # Bound work independently of a screenshot's original resolution.
    scale = min(1., 960 / max(image.size))
    small = image.convert('RGB').resize((round(image.width * scale), round(image.height * scale)),
                                       Image.Resampling.LANCZOS).filter(ImageFilter.MedianFilter(3))
    rgb = np.asarray(small, dtype=np.int32)
    bins = rgb // 32
    labels = bins[:, :, 0] * 64 + bins[:, :, 1] * 8 + bins[:, :, 2]
    xs, ys = _axis_votes(labels), _axis_votes(labels.T)
    candidates = {}
    for (left, sx), vx in xs:
        for (top, sy), vy in ys:
            if abs(sx - sy) > 2:
                continue
            side = round((sx + sy) / 2)
            if left + side > small.width or top + side > small.height:
                continue
            key = left, top, side
            candidates[key] = vx + vy
    accepted = []
    for (left, top, side), votes in sorted(candidates.items(), key=lambda pair: -pair[1])[:240]:
        fit = _grid_fit(rgb, left, top, side)
        if fit >= .80:
            accepted.append((fit, votes, left, top, side))
    result = []
    for fit, votes, left, top, side in sorted(accepted, reverse=True):
        xscale, yscale = image.width / small.width, image.height / small.height
        x, y = round(left * xscale), round(top * yscale)
        size = min(round(side * (xscale + yscale) / 2), image.width - x, image.height - y)
        rect = BoardRect(x, y, size, size)
        if size < 128:
            continue
        # Suppress tiny shifts around the same proposal; retain separate boards.
        if any(max(0, min(x+size, p.rectangle.left+p.rectangle.width)-max(x,p.rectangle.left)) *
               max(0, min(y+size, p.rectangle.top+p.rectangle.height)-max(y,p.rectangle.top)) >
               .8 * min(size**2, p.rectangle.width**2) for p in result):
            continue
        result.append(BoardProposal(rect.checked(image.size), fit))
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
