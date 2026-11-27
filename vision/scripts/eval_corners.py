#!/usr/bin/env python3
"""Pass V2 evaluation: board corner detection (board.find_corners) vs ChessReD2K corner annotations.
--method auto (default: pattern finder and learned regressor, the more board-like answer wins),
pattern, learned or classical.

Reports the fraction of images with mean corner error <= 2% of the board side (the spec's bar),
the median error, and how many images returned no detection. Writes debug overlays for the
worst cases to --debug-dir (grid in green = ours, red = annotation).
Usage: python3 vision/scripts/eval_corners.py [--split test] [--n 200] [--method auto] [--debug-dir /tmp/corners]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chessvision.board import corner_error, draw_grid, find_corners  # noqa: E402
from chessvision.data.chessred import ChessReD  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--method", default="auto", choices=("auto", "pattern", "learned", "classical"))
    ap.add_argument("--debug-dir", default=None)
    ap.add_argument("--worst", type=int, default=12)
    a = ap.parse_args()
    ds = ChessReD()
    if not ds.has_images():
        sys.exit("images not found under %s" % ds.root)
    ids = [i for i in ds.ids(a.split, "chessred2k") if ds.sample(i).corners is not None]
    rng = np.random.default_rng(a.seed)
    ids = list(rng.choice(ids, size=min(a.n, len(ids)), replace=False))
    errs, misses, rows = [], 0, []
    t0 = time.time()
    for k, i in enumerate(ids):
        s = ds.sample(int(i))
        img = cv2.imread(s.path)
        if img is None:
            print("unreadable", s.path, file=sys.stderr)
            continue
        pred = find_corners(img, a.method)
        if pred is None:
            misses += 1
            rows.append((9.99, s, None))
            continue
        e = corner_error(pred, s.corners)
        errs.append(e)
        rows.append((e, s, pred))
        if (k + 1) % 25 == 0:
            print("  %d/%d  ok<=2%%: %.1f%%  misses: %d" % (k + 1, len(ids), 100 * np.mean(np.array(errs) <= 0.02) * len(errs) / (k + 1), misses), flush=True)
    n = len(rows)
    errs_a = np.array(errs) if errs else np.array([9.99])
    print("method %s  images %d  detected %d  misses %d  time %.0fs" % (a.method, n, n - misses, misses, time.time() - t0))
    print("corner error <= 2%%: %.1f%% of all images   (<= 5%%: %.1f%%)" % (
        100 * (errs_a <= 0.02).sum() / n, 100 * (errs_a <= 0.05).sum() / n))
    print("median error of detections: %.2f%% of board side" % (100 * np.median(errs_a)))
    if a.debug_dir:
        os.makedirs(a.debug_dir, exist_ok=True)
        for e, s, pred in sorted(rows, key=lambda r: -r[0])[: a.worst]:
            img = cv2.imread(s.path)
            img = draw_grid(img, s.corners, (0, 0, 255))
            if pred is not None:
                img = draw_grid(img, pred, (0, 255, 0))
            small = cv2.resize(img, None, fx=0.33, fy=0.33)
            cv2.imwrite(os.path.join(a.debug_dir, "%s_%.3f.jpg" % (os.path.basename(s.path)[:-4], e)), small)
        print("overlays for the %d worst written to %s" % (a.worst, a.debug_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
