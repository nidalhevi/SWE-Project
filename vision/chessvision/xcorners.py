"""Board finder that uses only the checker pattern (added 2026-11-25).

The corner net (corner_net.py) was trained on one board and fails on others. This finder needs
no training. A chessboard has 49 points where four squares meet; around such a point the image
goes dark, light, dark, light, which no plain edge or flat patch does. The steps:
  1. score every pixel for that alternation (`xcorner_response`: the ChESS ring test of
     Bennett & Lasenby, 2014);
  2. keep the local maxima (`peaks`);
  3. fit a perspective lattice through them by RANSAC (`fit_lattice`);
  4. choose the 7x7 block of lattice points that is the inside of the board (`board_windows`).
The four outer corners are one lattice step outside that block. Works on any board whose squares
contrast; returns None when fewer than about a dozen inner corners can be seen.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import board as B

WORK_SIDE = 1000    # longest image side while searching, in pixels
RADII = (5.0, 9.0)  # ring radii of the corner test, in working pixels
MIN_POINTS = 12     # inner corners needed before a lattice or a board window is believed

Lattice = Tuple[np.ndarray, np.ndarray]  # (3x3 homography lattice -> image, (n, 2) integer coordinates)


# ---------------------------------------------------------------- points ----
def xcorner_response(gray: np.ndarray, r: float = 5.0) -> np.ndarray:
    """ChESS response: high where four alternating squares meet, negative on edges and flat areas.

    16 samples I[0..15] are taken on a ring of radius r around each pixel. Opposite samples are
    equal at a square corner and samples a quarter turn apart differ (sum term); on an edge
    opposite samples differ (difference term); on a stripe the ring mean differs from the centre
    (mean term). Precondition: gray is uint8 (h, w). Postcondition: float32 (h, w).
    """
    g = cv2.GaussianBlur(gray, (0, 0), 1.2).astype(np.float32)
    h, w = g.shape
    ring = []
    for k in range(16):
        a = 2 * np.pi * k / 16
        shift = np.float32([[1, 0, r * np.cos(a)], [0, 1, r * np.sin(a)]])
        ring.append(cv2.warpAffine(g, shift, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                   borderMode=cv2.BORDER_REPLICATE))
    samples = np.stack(ring)
    sum_term = sum(np.abs(samples[n] + samples[n + 8] - samples[n + 4] - samples[n + 12]) for n in range(4))
    diff_term = sum(np.abs(samples[n] - samples[n + 8]) for n in range(8))
    mean_term = np.abs(samples.mean(0) - cv2.blur(g, (5, 5)))
    return sum_term - diff_term - 16 * mean_term


def peaks(resp: np.ndarray, nms: int = 6, top: int = 220, rel: float = 0.12) -> np.ndarray:
    """The `top` strongest local maxima of resp as (n, 2) float32 (x, y) points.

    A maximum counts if it is the largest value within `nms` pixels and above `rel` times the
    global maximum.
    """
    dilated = cv2.dilate(resp, np.ones((2 * nms + 1, 2 * nms + 1), np.uint8))
    ys, xs = np.where((resp == dilated) & (resp > rel * resp.max()))
    order = np.argsort(-resp[ys, xs])[:top]
    return np.stack([xs[order], ys[order]], 1).astype(np.float32)


# --------------------------------------------------------------- lattice ----
def _assign(pts: np.ndarray, H: np.ndarray, tol: float, limit: int):
    """Lattice coordinates of every point under H, and which points sit on a lattice node."""
    w = cv2.perspectiveTransform(pts.reshape(-1, 1, 2), np.linalg.inv(H).astype(np.float32)).reshape(-1, 2)
    r = np.round(w)
    return r, (np.abs(w - r).max(1) < tol) & (np.abs(r).max(1) <= limit)


def _seed_lattice(pts: np.ndarray, i0: int, a: int, b: int):
    """Guess a lattice around pts[i0], taking its neighbours a and b as one step along each axis.

    Locally a perspective grid is close to an affine one, so the guess is only trusted within
    three steps. Returns (coordinates, inlier mask), or None if the two steps are too short,
    too unequal or too parallel to be the sides of one square.
    """
    v1, v2 = pts[a] - pts[i0], pts[b] - pts[i0]
    l1, l2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if min(l1, l2) < 8 or max(l1, l2) / min(l1, l2) > 2.5 or abs(v1 @ v2) / (l1 * l2) > 0.75:
        return None
    w = np.linalg.solve(np.stack([v1, v2], 1), (pts - pts[i0]).T).T
    r = np.round(w)
    return r, (np.abs(w - r).max(1) < 0.2) & (np.abs(r).max(1) <= 3)


_GROW = ((0.2, 5), (0.16, 9), (0.14, 10), (0.14, 10))  # (tolerance, reach in steps) per round


def _grow_lattice(pts: np.ndarray, r: np.ndarray, ok: np.ndarray) -> Optional[Lattice]:
    """Refit a homography on the inliers and reassign all points, reaching further each round."""
    H = None
    for tol, limit in _GROW:
        if ok.sum() < 8:
            return None
        H, _ = cv2.findHomography(r[ok].astype(np.float32), pts[ok], cv2.RANSAC, 3.0)
        if H is None:
            return None
        r, ok = _assign(pts, H, tol, limit)
    return H, np.unique(r[ok], axis=0)


def fit_lattice(pts: np.ndarray, iters: int = 500, seed: int = 0) -> Optional[Lattice]:
    """The perspective lattice that passes through the most points, or None.

    Precondition: pts is (n, 2) float32. Postcondition: the lattice unit is one board square
    and its axes are the board's (see coarsen and reduce_basis); the origin is arbitrary.
    The same seed always gives the same answer.
    """
    n = len(pts)
    if n < MIN_POINTS:
        return None
    rng = np.random.default_rng(seed)
    dist = np.linalg.norm(pts[:, None] - pts[None], axis=2)
    near = np.argsort(dist, axis=1)[:, 1:7]
    best: Optional[Lattice] = None
    for _ in range(iters):
        i0 = int(rng.integers(n))
        a, b = rng.choice(near[i0], 2, replace=False)
        start = _seed_lattice(pts, i0, a, b)
        grown = _grow_lattice(pts, *start) if start is not None else None
        if grown is not None and len(grown[1]) > (len(best[1]) if best is not None else 0):
            best = grown
    if best is None:
        return None
    H, lat = coarsen(*reduce_basis(*best))
    return reduce_basis(H, lat)


def _block_count(lat: np.ndarray) -> Tuple[float, int]:
    """Most lattice points inside any 7x7 block, and the bounding-box area (smaller is tidier)."""
    xs, ys = lat[:, 0].astype(int), lat[:, 1].astype(int)
    w, h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    grid = np.zeros((h + 12, w + 12), np.float32)
    grid[ys - ys.min() + 6, xs - xs.min() + 6] = 1
    return float(cv2.boxFilter(grid, -1, (7, 7), normalize=False).max()), int(w * h)


_UNIMODULAR = [np.array([[a, b], [c, d]], float) for a in range(-2, 3) for b in range(-2, 3)
               for c in range(-2, 3) for d in range(-2, 3) if abs(a * d - b * c) == 1]


def reduce_basis(H: np.ndarray, lat: np.ndarray) -> Lattice:
    """Describe the same lattice with the axes under which the points form a square block.

    RANSAC may pick a diagonal as one axis: the nodes are the same, but the board's interior is
    then a slanted parallelogram and no 7x7 window fits it. Every integer change of axes with
    determinant +-1 keeps the node set; the one that packs most points into a 7x7 block wins.
    """
    best_key, best_u = None, _UNIMODULAR[0]
    for u in _UNIMODULAR:
        count, area = _block_count(lat @ u.T)
        if best_key is None or (count, -area) > best_key:
            best_key, best_u = (count, -area), u
    change = np.eye(3)
    change[:2, :2] = np.linalg.inv(best_u)
    return H @ change, np.round(lat @ best_u.T)


def coarsen(H: np.ndarray, lat: np.ndarray) -> Lattice:
    """If the fitted step is a half, third or quarter of a square on one axis, rescale that axis.

    This happens when ornament between the squares adds evenly spaced extra points: the real
    corners then sit on every 2nd, 3rd or 4th line only. An axis is rescaled when at least 90%
    of the points share one remainder.
    """
    H, lat = H.copy(), lat.copy()
    for axis in (0, 1):
        for k in (4, 3, 2):
            res = np.mod(lat[:, axis], k)
            common = np.bincount(res.astype(int), minlength=k).argmax()
            if (res == common).mean() >= 0.9:
                lat = lat[res == common]
                lat[:, axis] = (lat[:, axis] - common) / k
                step = np.eye(3)
                step[axis, axis], step[axis, 2] = k, common
                H = H @ step
                break
    return H, lat


# ---------------------------------------------------------------- extent ----
def board_windows(H: np.ndarray, lat: np.ndarray, gray: np.ndarray, keep: int = 6) -> List[np.ndarray]:
    """Candidate boards as (4, 2) corner arrays in the pixels of `gray`, most convincing first.

    Every 7x7 window of lattice nodes is a candidate interior. Its score: points inside, minus
    half the points left outside (a real board has no square corners on its rim), plus four
    times the checker contrast of the 8x8 area it implies.
    """
    xs, ys = lat[:, 0].astype(int), lat[:, 1].astype(int)
    scored = []
    for x0 in range(xs.min() - 6, xs.max() + 1):
        for y0 in range(ys.min() - 6, ys.max() + 1):
            inside = int(((xs >= x0) & (xs <= x0 + 6) & (ys >= y0) & (ys <= y0 + 6)).sum())
            if inside < MIN_POINTS:
                continue
            cell = np.float32([[x0 - 1, y0 - 1], [x0 + 7, y0 - 1], [x0 + 7, y0 + 7], [x0 - 1, y0 + 7]])
            quad = cv2.perspectiveTransform(cell.reshape(-1, 1, 2), H.astype(np.float32)).reshape(-1, 2)
            if cv2.isContourConvex(quad):
                score = inside - 0.5 * (len(lat) - inside) + 4.0 * B._checker_score(gray, quad)
                scored.append((score, quad))
    scored.sort(key=lambda t: -t[0])
    return [quad for _, quad in scored[:keep]]


def _refine_if_better(gray: np.ndarray, corners: np.ndarray, edge: int = 20) -> np.ndarray:
    """Sub-pixel refinement (board.refine_corners), kept only if the checker contrast holds.

    Skipped when a corner is within `edge` pixels of the image border, where the refinement
    window would leave the image.
    """
    h, w = gray.shape
    if (corners[:, 0].min() <= edge or corners[:, 1].min() <= edge
            or corners[:, 0].max() >= w - edge or corners[:, 1].max() >= h - edge):
        return corners
    refined = B.refine_corners(gray, corners)
    if B._checker_score(gray, refined) >= B._checker_score(gray, corners) - 0.02:
        return refined
    return corners


def find_corners_pattern(image: np.ndarray, min_checker: float = 0.35) -> Optional[B.Corners]:
    """The four outer board corners, TL TR BR BL in image pixels, or None.

    Precondition: image is BGR or grayscale, any size. Postcondition: the returned
    quadrilateral shows an alternating 8x8 pattern with contrast at least `min_checker`
    (board._checker_score); None if no lattice of square corners is found or the best
    candidate does not look like a board.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, WORK_SIDE / max(gray.shape))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    # a corner between four squares answers at both ring sizes; fine ornament only at the small one
    resp = np.minimum(*(np.clip(xcorner_response(small, r), 0, None) for r in RADII))
    fit = fit_lattice(peaks(resp))
    if fit is None:
        return None
    candidates = board_windows(fit[0], fit[1], small)
    if not candidates:
        return None
    corners = _refine_if_better(gray, (candidates[0] / scale).astype(np.float32))
    if B._checker_score(gray, corners) < min_checker:
        return None
    return B.canonical_order(corners)
