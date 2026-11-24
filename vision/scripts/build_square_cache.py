#!/usr/bin/env python3
"""Warp every ChessReD2K photo once and store the result, so classifier training never touches the 3072-px originals.

For each image we store 640x640 JPEGs (board.warp_for_crops) under <CHESSRED_DIR>/cache_squares/:
  <id>_pred.jpg        corners from our own detector (find_corners): what the classifier sees in real use
  <id>_gt.jpg          annotated corners                              (train split only)
  <id>_j1.jpg, _j2.jpg annotated corners moved by ~0.8% and ~1.5% of the board side (train split only)
The train split needs the jittered copies because the corner net was trained on those same photos and is
therefore more accurate on them than on new ones; without jitter the classifier would learn from crops that
are better aligned than anything it meets later.
index.json lists every file with its image id, split, orientation (board.grid_of_square) and game/move ids.

Usage: python3 vision/scripts/build_square_cache.py [--workers 8]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from multiprocessing import Pool

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chessvision.board import orientation_from_named, refine_by_warp, warp_for_crops  # noqa: E402
from chessvision.data.chessred import DEFAULT_DIR, ChessReD  # noqa: E402

OUT = os.path.join(DEFAULT_DIR, "cache_squares")
JITTER = {"j1": 0.008, "j2": 0.015}
_PRED = None


def _predictor():
    global _PRED
    if _PRED is None:
        import torch
        from chessvision.corner_net import CornerPredictor
        torch.set_num_threads(1)
        _PRED = CornerPredictor(dev=torch.device("cpu"))
    return _PRED


def _save(image, corners, named, name):
    cv2.imwrite(os.path.join(OUT, name), warp_for_crops(image, corners), [cv2.IMWRITE_JPEG_QUALITY, 95])
    return {"file": name, "orientation": orientation_from_named(corners, named)}


def process(job):
    """One photo -> its warps. Returns the index rows (empty if the file is unreadable)."""
    image_id, path, split, game_id, move_id, named = job
    image = cv2.imread(path)
    if image is None:
        return []
    named = np.array(named, dtype=np.float32)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    rows = [dict(_save(image, refine_by_warp(gray, _predictor()(image)), named, "%d_pred.jpg" % image_id), tag="pred")]
    if split == "train":
        rows.append(dict(_save(image, named, named, "%d_gt.jpg" % image_id), tag="gt"))
        side = float(np.mean(np.linalg.norm(named - np.roll(named, -1, axis=0), axis=1)))
        rng = np.random.default_rng(image_id)
        for tag, frac in JITTER.items():
            moved = named + rng.normal(0, frac * side, size=(4, 2)).astype(np.float32)
            rows.append(dict(_save(image, moved, named, "%d_%s.jpg" % (image_id, tag)), tag=tag))
    for r in rows:
        r.update(image_id=image_id, split=split, game_id=game_id, move_id=move_id)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    ds = ChessReD()
    jobs = []
    for split in ("train", "val", "test"):
        for s in ds.samples(split):
            jobs.append((s.image_id, s.path, split, s.game_id, s.move_id, s.corners.tolist()))
    index = []
    with Pool(args.workers) as pool:
        for n, rows in enumerate(pool.imap_unordered(process, jobs, chunksize=4), 1):
            index.extend(rows)
            if n % 200 == 0 or n == len(jobs):
                print("%d / %d photos" % (n, len(jobs)), flush=True)
    index.sort(key=lambda r: (r["image_id"], r["tag"]))
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump(index, f)
    print("wrote %d warps to %s" % (len(index), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
