"""Board geometry (pass V2): photo -> 4 board corners -> top-down warp -> 64 square crops.

`find_corners` uses the learned regressor (corner_net.py) when its weights are present and
falls back to the classical detector below otherwise. Both end with `refine_corners`.

The classical detector has three stages:
  1. edges + Hough lines, split into two orientation families (the board's two line directions);
  2. intersections of the two families = candidate lattice points;
  3. RANSAC: pick 2 lines from each family, map their 4 intersections to a unit cell,
     and count how many other intersections land on integer lattice coordinates.
     The best cell's lattice gives the board's 9x9 line grid; its extreme lines are the corners.
It returns None when no convincing lattice is found; callers fall back to manual corners.
Corner order is always TL, TR, BR, BL *as seen in the photo*. Which corner is a1 is decided by
the caller through `white_bottom` in square_crops (orientation is never guessed here).
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

Corners = np.ndarray  # (4, 2) float32, TL TR BR BL in image pixels


# ---------------------------------------------------------------- lines ----
def _detect_lines(gray: np.ndarray) -> np.ndarray:
    """Hough lines as (rho, theta) rows on a blurred, edge-detected image."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 60, 160, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=int(0.12 * min(gray.shape)))
    if lines is None:
        return np.zeros((0, 2), dtype=np.float64)
    return lines[:, 0, :].astype(np.float64)


def _split_families(lines: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Split lines into the board's two directions.

    Under perspective each family fans out by up to ~35 degrees, so clustering by angle
    alone can cut one fan in two and starve the other. Instead the strongest line seeds
    family A; a line joins B when its angle differs from the seed by 45..135 degrees.
    """
    if len(lines) < 4:
        return lines, lines[:0]
    seed = lines[0, 1]
    d = np.abs((lines[:, 1] - seed + np.pi / 2) % np.pi - np.pi / 2)  # angle distance in [0, pi/2]
    is_b = d > np.pi / 4
    return lines[~is_b], lines[is_b]


def _dedupe(lines: np.ndarray, rho_tol: float, theta_tol: float = np.deg2rad(2.5)) -> np.ndarray:
    """Merge near-duplicate Hough lines (same rho and theta within tolerance)."""
    keep: List[np.ndarray] = []
    for ln in lines[np.argsort(lines[:, 0])]:
        if not any(abs(ln[0] - k[0]) < rho_tol and abs(ln[1] - k[1]) < theta_tol for k in keep):
            keep.append(ln)
    return np.array(keep) if keep else lines[:0]


def _intersections(fam_a: np.ndarray, fam_b: np.ndarray) -> np.ndarray:
    """All intersections between two line families, as (n, 2) points."""
    pts = []
    for ra, ta in fam_a:
        for rb, tb in fam_b:
            A = np.array([[np.cos(ta), np.sin(ta)], [np.cos(tb), np.sin(tb)]])
            if abs(np.linalg.det(A)) < 1e-6:
                continue
            pts.append(np.linalg.solve(A, np.array([ra, rb])))
    return np.array(pts) if pts else np.zeros((0, 2))


# --------------------------------------------------------------- lattice ----
def _lattice_fit(pts: np.ndarray, quad: np.ndarray, tol: float = 0.08):
    """Homography from `quad` (4 pts, TL TR BR BL) to the unit cell; returns (inlier count, H, lattice coords)."""
    dst = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    w = cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float32), H).reshape(-1, 2)
    r = np.round(w)
    ok = (np.abs(w - r).max(axis=1) < tol) & (np.abs(r).max(axis=1) <= 12)
    lat = np.unique(r[ok], axis=0) if ok.any() else r[:0]
    return len(lat), H, lat


def _quad_from_lines(la: Sequence, lb: Sequence) -> Optional[np.ndarray]:
    """Corners of the cell bounded by two lines of family A and two of family B."""
    pts = _intersections(np.array(la), np.array(lb))
    if len(pts) != 4:
        return None
    c = pts.mean(axis=0)
    order = np.argsort(np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0]))
    return pts[order]  # counter-clockwise in image coords == TL, TR, BR, BL for a convex cell


def find_corners_classical(image: np.ndarray, iters: int = 400, seed: int = 0,
                 max_side: int = 1000, max_lines: int = 24, min_points: int = 12,
                 min_checker: float = 0.35) -> Optional[Corners]:
    """Detect the 4 outer corners of the 8x8 board. Returns (4,2) float32 or None.

    Precondition: `image` is BGR or grayscale, any size. Postcondition: corners are in the
    original image's pixel coordinates, ordered TL, TR, BR, BL as they appear in the photo.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, max_side / max(gray.shape))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    lines = _detect_lines(small)
    fam_a, fam_b = _split_families(lines)
    rho_tol = 0.012 * max(small.shape)
    fam_a, fam_b = _dedupe(fam_a, rho_tol), _dedupe(fam_b, rho_tol)
    fam_a, fam_b = fam_a[:max_lines], fam_b[:max_lines]  # HoughLines is sorted by votes: keep the strongest
    if len(fam_a) < 3 or len(fam_b) < 3:
        return None
    pts = _intersections(fam_a, fam_b)
    rng = np.random.default_rng(seed)
    best = (0, None, None)
    for _ in range(iters):
        ia, ib = _neighbour_pair(len(fam_a), rng), _neighbour_pair(len(fam_b), rng)
        quad = _quad_from_lines(fam_a[ia], fam_b[ib])
        if quad is None or cv2.contourArea(quad.astype(np.float32)) < 25:
            continue
        n, H, lat = _lattice_fit(pts, quad)
        if n > best[0]:
            best = (n, H, lat)
    n, H, lat = best
    if H is None or n < min_points:
        return None
    H, lat = _refine(pts, H)
    ext = _board_extent(H, lat, small)
    if ext is None or ext[0] < min_checker:
        return None
    return refine_corners(gray, (ext[1] / scale).astype(np.float32))


def _neighbour_pair(n: int, rng: np.random.Generator) -> np.ndarray:
    """Two line indices close in rho order (lines are sorted by rho after _dedupe), so the
    sampled cell is usually one or two real squares wide instead of a random stripe."""
    i = int(rng.integers(n - 1))
    j = min(n - 1, i + int(rng.integers(1, 3)))
    return np.array([i, j])


def _refine(pts: np.ndarray, H: np.ndarray, tol: float = 0.08):
    """Re-estimate the lattice homography from all inlier intersections (least squares),
    then recount: this recovers lattice points the 4-point sample placed just outside `tol`."""
    w = cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float32), H).reshape(-1, 2)
    r = np.round(w)
    ok = (np.abs(w - r).max(axis=1) < tol) & (np.abs(r).max(axis=1) <= 12)
    if ok.sum() >= 8:
        H2, _ = cv2.findHomography(pts[ok].astype(np.float32), r[ok].astype(np.float32), 0)
        if H2 is not None:
            H = H2
            w = cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float32), H).reshape(-1, 2)
            r = np.round(w)
            ok = (np.abs(w - r).max(axis=1) < tol) & (np.abs(r).max(axis=1) <= 12)
    lat = np.unique(r[ok], axis=0) if ok.any() else r[:0]
    return H, lat


_CHECKER = np.fromfunction(lambda r, c: 1.0 - 2.0 * ((r + c) % 2), (8, 8))


def _checker_score(gray: np.ndarray, corners: np.ndarray) -> float:
    """How board-like the quadrilateral is: contrast of the alternating light/dark cell pattern.

    The 8x8 cell means are correlated with a checkerboard sign pattern and normalised by the
    cells' spread, so a wooden table (no alternation) scores near 0 and a board scores near 1.
    """
    dst = np.array([[0, 0], [63, 0], [63, 63], [0, 63]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    small = cv2.warpPerspective(gray, H, (64, 64)).astype(np.float64)
    cells = small.reshape(8, 8, 8, 8).mean(axis=(1, 3))
    spread = cells.std()
    if spread < 1e-6:
        return 0.0
    return float(abs(((cells - cells.mean()) * _CHECKER).mean()) / spread)


def _board_extent(H: np.ndarray, lat: np.ndarray, gray: np.ndarray) -> Optional[Tuple[float, np.ndarray]]:
    """Choose the lattice window that looks most like a chessboard in `gray`.

    The lattice unit is not always one square: when every other grid line of a family is
    missed (pieces, perspective compression, merged lines) the unit on that axis is two or
    even four squares. So windows of 8, 4 and 2 lattice units per axis are all tried, at every
    integer offset within the observed lattice plus one unit of slack, and the window with
    the highest checker contrast wins. Returns (checker score, corners TL TR BR BL).
    """
    xs, ys = lat[:, 0].astype(int), lat[:, 1].astype(int)
    Hinv = np.linalg.inv(H).astype(np.float32)
    best, bcorners = (-1.0, -1), None
    for sx in (8, 4, 2):
        for sy in (8, 4, 2):
            for x0 in range(min(xs.min(), xs.max() - sx) - 1, max(xs.min(), xs.max() - sx) + 2):
                for y0 in range(min(ys.min(), ys.max() - sy) - 1, max(ys.min(), ys.max() - sy) + 2):
                    n = int(((xs >= x0) & (xs <= x0 + sx) & (ys >= y0) & (ys <= y0 + sy)).sum())
                    if n < 6:
                        continue
                    cell = np.array([[x0, y0], [x0 + sx, y0], [x0 + sx, y0 + sy], [x0, y0 + sy]], dtype=np.float32)
                    img = cv2.perspectiveTransform(cell.reshape(-1, 1, 2), Hinv).reshape(-1, 2)
                    if not _inside(img, gray.shape) or cv2.contourArea(img.astype(np.float32)) < 0.02 * gray.size:
                        continue
                    key = (_checker_score(gray, img), n)
                    if key > best:
                        best, bcorners = key, img
    if bcorners is None:
        return None
    c = bcorners.mean(axis=0)
    order = np.argsort(np.arctan2(bcorners[:, 1] - c[1], bcorners[:, 0] - c[0]))
    img = bcorners[order]
    k = int(np.argmin(img.sum(axis=1)))  # start at the top-left corner (smallest x+y)
    return best[0], np.roll(img, -k, axis=0)


def refine_corners(gray: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Sub-pixel refinement: the 49 inner grid corners are saddle points, which cornerSubPix
    locks onto; a RANSAC homography from the refined points rejects those that drifted
    (occluded by pieces) and re-derives the four outer corners. Falls back to the input."""
    src = np.array([[0, 0], [8, 0], [8, 8], [0, 8]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(src, corners.astype(np.float32))
    grid = np.array([[x, y] for y in range(1, 8) for x in range(1, 8)], dtype=np.float32)
    pts = cv2.perspectiveTransform(grid.reshape(-1, 1, 2), H).reshape(-1, 2)
    side = np.linalg.norm(corners[1] - corners[0]) / 8.0
    win = int(max(3, min(15, side * 0.25)))
    refined = pts.copy().reshape(-1, 1, 2)
    cv2.cornerSubPix(gray, refined, (win, win), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.01))
    refined = refined.reshape(-1, 2)
    moved = np.linalg.norm(refined - pts, axis=1)
    keep = moved < 0.6 * side
    if keep.sum() < 12:
        return corners
    H2, mask = cv2.findHomography(grid[keep], refined[keep], cv2.RANSAC, 0.08 * side)
    if H2 is None or mask.sum() < 12:
        return corners
    return cv2.perspectiveTransform(src.reshape(-1, 1, 2), H2).reshape(-1, 2).astype(np.float32)


def _inside(pts: np.ndarray, shape, slack: float = 0.05) -> bool:
    h, w = shape[:2]
    return bool((pts[:, 0] > -slack * w).all() and (pts[:, 0] < (1 + slack) * w).all()
                and (pts[:, 1] > -slack * h).all() and (pts[:, 1] < (1 + slack) * h).all())


# ------------------------------------------------------------------ warp ----
def warp_topdown(image: np.ndarray, corners: Corners, size: int = 1024,
                 margin: float = 0.0) -> np.ndarray:
    """Perspective-warp the board to a size x size top-down view (optionally with a border margin
    expressed as a fraction of the board, so tall pieces on the back rank stay visible)."""
    m = margin * size
    dst = np.array([[m, m], [size - 1 - m, m], [size - 1 - m, size - 1 - m], [m, size - 1 - m]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(np.asarray(corners, dtype=np.float32), dst)
    return cv2.warpPerspective(image, H, (size, size))


def square_crops(warped: np.ndarray, white_bottom: bool = True, top_extra: float = 0.5,
                 out_size: Tuple[int, int] = (64, 96)) -> List[np.ndarray]:
    """64 crops indexed a1 = 0 ... h8 = 63 (the engine's convention) from a top-down board image.

    Each crop covers its square plus `top_extra` squares above it (pieces are tall and lean
    'up' in the warped image). `white_bottom` says which side of the photo holds rank 1.
    """
    size = warped.shape[0]
    s = size / 8.0
    crops: List[np.ndarray] = []
    for sq in range(64):
        f, r = sq & 7, sq >> 3
        col, row = (f, 7 - r) if white_bottom else (7 - f, r)
        x0, x1 = int(col * s), int((col + 1) * s)
        y1 = int((row + 1) * s)
        y0 = max(0, int(row * s - top_extra * s))
        crops.append(cv2.resize(warped[y0:y1, x0:x1], out_size, interpolation=cv2.INTER_AREA))
    return crops


def draw_grid(image: np.ndarray, corners: Corners, color=(0, 255, 0)) -> np.ndarray:
    """Debug overlay: the 9x9 line grid implied by `corners`, drawn on a copy of the image."""
    out = image.copy()
    src = np.array([[0, 0], [8, 0], [8, 8], [0, 8]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(src, np.asarray(corners, dtype=np.float32))
    for i in range(9):
        seg = np.array([[[i, 0]], [[i, 8]], [[0, i]], [[8, i]]], dtype=np.float32)
        p = cv2.perspectiveTransform(seg, H).reshape(-1, 2).astype(int)
        cv2.line(out, tuple(p[0]), tuple(p[1]), color, 2)
        cv2.line(out, tuple(p[2]), tuple(p[3]), color, 2)
    return out


def corner_error(pred: Corners, truth: Corners) -> float:
    """Mean corner distance as a fraction of the true board's mean side length (order-aligned)."""
    pred, truth = np.asarray(pred, float), np.asarray(truth, float)
    side = np.mean([np.linalg.norm(truth[i] - truth[(i + 1) % 4]) for i in range(4)])
    best = min(np.mean(np.linalg.norm(np.roll(pred, k, axis=0) - truth, axis=1)) for k in range(4))
    return float(best / side)


def refine_by_warp(gray: np.ndarray, corners: np.ndarray, size: int = 1024, margin: float = 0.12,
                   band: float = 0.25, rounds: int = 3) -> np.ndarray:
    """Refine corners that are already roughly right (a few % of the board side).

    The board is warped top-down with a margin, so its grid lines are nearly axis-aligned and
    evenly spaced. Lines are found with a Hough transform restricted to near-vertical and
    near-horizontal angles on the Canny edge map: a grid line spans the whole board and wins
    the vote, a piece outline is short and loses. The seven inner lines per axis are matched
    to their expected positions; a quadratic through them extrapolates the two outer lines
    (the printed border just outside the grid would mislead a direct search), and the four
    intersections map back to the image. Falls back to the input when too few lines are found.
    """
    c = np.asarray(corners, dtype=np.float32)
    for _ in range(rounds):
        m = margin * size
        dst = np.array([[m, m], [size - m, m], [size - m, size - m], [m, size - m]], dtype=np.float32)
        H = cv2.getPerspectiveTransform(c, dst)
        top = cv2.warpPerspective(gray, H, (size, size))
        s8 = (size - 2 * m) / 8.0
        edges = cv2.Canny(cv2.GaussianBlur(top, (5, 5), 0), 50, 150)
        xs = _line_positions(_axis_lines(edges, vertical=True), m, s8, band)
        ys = _line_positions(_axis_lines(edges, vertical=False), m, s8, band)
        if xs is None or ys is None:
            return c
        quad = np.array([[xs[0], ys[0]], [xs[1], ys[0]], [xs[1], ys[1]], [xs[0], ys[1]]], dtype=np.float32)
        c2 = cv2.perspectiveTransform(quad.reshape(-1, 1, 2), np.linalg.inv(H).astype(np.float32)).reshape(-1, 2)
        if not _plausible_update(c, c2):
            return c  # the fit ran off the board (or across the horizon): keep the last good corners
        c = c2.astype(np.float32)
    return c.astype(np.float32)


def _plausible_update(old: np.ndarray, new: np.ndarray) -> bool:
    """A refinement step may only move corners a little and must keep a convex quadrilateral."""
    if not cv2.isContourConvex(new.astype(np.float32)):
        return False
    a0, a1 = cv2.contourArea(old.astype(np.float32)), cv2.contourArea(new.astype(np.float32))
    if a1 < 0.7 * a0 or a1 > 1.4 * a0:
        return False
    side = np.sqrt(a0)
    return bool(np.linalg.norm(new - old, axis=1).max() < 0.35 * side)


def _axis_lines(edges: np.ndarray, vertical: bool, tilt: float = np.deg2rad(4)) -> List[Tuple[float, int]]:
    """Hough lines within `tilt` of the axis, as (position at the image centre, votes), sorted by votes."""
    size = edges.shape[0]
    thr = int(0.25 * size)
    if vertical:
        parts = [cv2.HoughLines(edges, 1, np.pi / 360, thr, min_theta=0, max_theta=tilt),
                 cv2.HoughLines(edges, 1, np.pi / 360, thr, min_theta=np.pi - tilt, max_theta=np.pi)]
    else:
        parts = [cv2.HoughLines(edges, 1, np.pi / 360, thr, min_theta=np.pi / 2 - tilt, max_theta=np.pi / 2 + tilt)]
    out = []
    for part in parts:
        if part is None:
            continue
        for rank, (rho, th) in enumerate(part[:, 0, :]):
            mid = size / 2.0
            if vertical:
                pos = (rho - mid * np.sin(th)) / np.cos(th) if abs(np.cos(th)) > 1e-6 else None
            else:
                pos = (rho - mid * np.cos(th)) / np.sin(th) if abs(np.sin(th)) > 1e-6 else None
            if pos is not None:
                out.append((float(pos), len(part) - rank))  # HoughLines is sorted by votes
    return sorted(out, key=lambda t: -t[1])


def _line_positions(lines: List[Tuple[float, int]], m: float, s8: float, band: float):
    """Match the strongest line in each band (k = 0..8) and fit a line through them.

    Inner bands are symmetric. The outer bands (k = 0, 8) only extend a little outward: the
    printed border runs a fraction of a square outside the grid and would otherwise win.
    A weighted linear fit (votes as weights) over the matched lines gives lines 0 and 8; in the
    ablation on ChessReD2K this beat quadratic fits and inner-only extrapolation.
    """
    ks, pos, wts = [], [], []
    for k in range(9):
        e = m + k * s8
        if k == 0:
            lo, hi = e - 0.08 * s8, e + band * s8
        elif k == 8:
            lo, hi = e - band * s8, e + 0.08 * s8
        else:
            lo, hi = e - band * s8, e + band * s8
        cands = [(p, v) for p, v in lines if lo < p < hi]
        if not cands:
            continue
        ks.append(k); pos.append(cands[0][0]); wts.append(cands[0][1])
    if len(ks) < 4:
        return None
    coef = np.polyfit(np.array(ks, float), np.array(pos, float), 1, w=np.sqrt(np.array(wts, float)))
    return float(np.polyval(coef, 0.0)), float(np.polyval(coef, 8.0))


# -------------------------------------------------------------- dispatch ----
_PREDICTOR = None


def find_corners(image: np.ndarray, method: str = "auto") -> Optional[Corners]:
    """Board corners TL, TR, BR, BL in image pixels, or None.

    method: "auto" = learned regressor if its weights exist, else classical;
            "learned" or "classical" force one. The learned path always returns corners
            (a regressor has no reject), so callers judge plausibility downstream.
    """
    global _PREDICTOR
    if method in ("auto", "learned"):
        try:
            if _PREDICTOR is None:
                from .corner_net import CornerPredictor  # torch is optional at import time
                _PREDICTOR = CornerPredictor()
            gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            return refine_by_warp(gray, _PREDICTOR(image))
        except (ImportError, FileNotFoundError):
            if method == "learned":
                raise
    return find_corners_classical(image)
