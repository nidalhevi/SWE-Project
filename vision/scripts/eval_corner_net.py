#!/usr/bin/env python3
"""Evaluate the learned corner regressor on the ChessReD2K test split (full-resolution images),
with and without the sub-pixel refinement, against the spec's bar (<= 2% of board side).
Usage: python3 vision/scripts/eval_corner_net.py [--split test] [--n 0 (= all)]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chessvision.board import corner_error, refine_by_warp, refine_corners  # noqa: E402
from chessvision.corner_net import CornerPredictor  # noqa: E402
from chessvision.data.chessred import ChessReD  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--weights", default=None)
    a = ap.parse_args()
    ds = ChessReD()
    pred = CornerPredictor(a.weights)
    ids = ds.ids(a.split, "chessred2k")
    if a.n:
        ids = ids[: a.n]
    raw, ref, wrp, t_net, t_ref = [], [], [], 0.0, 0.0
    for i in ids:
        s = ds.sample(i)
        img = cv2.imread(s.path)
        t0 = time.time(); c = pred(img); t_net += time.time() - t0
        t0 = time.time(); r = refine_corners(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), c); t_ref += time.time() - t0
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        t0 = time.time(); wq = refine_by_warp(g, c); t_ref += time.time() - t0
        raw.append(corner_error(c, s.corners)); ref.append(corner_error(r, s.corners)); wrp.append(corner_error(wq, s.corners))
    raw_a, ref_a, wrp_a = np.array(raw), np.array(ref), np.array(wrp)
    print("split %s, images %d" % (a.split, len(ids)))
    print("%-22s %10s %10s %10s" % ("", "<=2%", "<=5%", "median"))
    for name, e in (("regressor", raw_a), ("regressor+subpix", ref_a), ("regressor+warp-refine", wrp_a)):
        print("%-22s %9.1f%% %9.1f%% %9.2f%%" % (name, 100 * (e <= .02).mean(), 100 * (e <= .05).mean(), 100 * np.median(e)))
    print("time per image: net %.0f ms, refine %.0f ms" % (1000 * t_net / len(ids), 1000 * t_ref / len(ids)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
