#!/usr/bin/env python3
"""Evaluate the square classifier on the ChessReD2K test games (3 games the training never saw).

A. Squares: accuracy per square and per board, on warps made from our own detected corners.
B. Moves:   the decoder consumes the classifier's probabilities on the real photo sequences.
            teacher-forced = the true previous position is given for every photo;
            free-running   = the pipeline runs alone from the start position, errors compound.
            Orientation is tested both given (from the annotations) and worked out per photo.
C. Speed:   whole pipeline per photo from the original file (corner net, refinement, 64 crops, classifier).
Usage: python3 vision/scripts/eval_classifier.py [--split test] [--time-photos 30]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chessvision.board import grid_of_square  # noqa: E402
from chessvision.classifier import SquareClassifier, best_orientation  # noqa: E402
from chessvision.data.chessred import DEFAULT_DIR, ChessReD  # noqa: E402
from chessvision.decoder import apply_changes, decode_move, move_changes  # noqa: E402
from chessvision.engine import START_FEN, EngineClient  # noqa: E402
from chessvision.labels import NAMES, placement_from_fen  # noqa: E402
from chessvision.pipeline import GameDecoder  # noqa: E402

CACHE = os.path.join(DEFAULT_DIR, "cache_squares")


def load_games(ds, split):
    """{game_id: [row, ...] sorted by move}, each row with its grid probabilities still to come."""
    rows = [r for r in json.load(open(os.path.join(CACHE, "index.json"))) if r["split"] == split and r["tag"] == "pred"]
    games = collections.defaultdict(list)
    for r in rows:
        r["labels"] = ds.sample(r["image_id"]).labels
        games[r["game_id"]].append(r)
    return {g: sorted(v, key=lambda r: r["move_id"]) for g, v in games.items()}


def true_move(engine, labels):
    """The legal move that turns the engine's position into `labels`, or None if the board is unchanged."""
    board = placement_from_fen(engine.fen())
    if list(labels) == board:
        return None
    for uci in engine.moves():
        if apply_changes(board, move_changes(board, uci)) == list(labels):
            return uci
    raise ValueError("no legal move explains the annotated position")


def squares_report(games):
    wrong, confusion = [], collections.Counter()
    for rows in games.values():
        for r in rows:
            pred = r["grid"][grid_of_square(r["orientation"])].argmax(1)
            truth = np.array(r["labels"])
            wrong.append(int((pred != truth).sum()))
            confusion.update((NAMES[t], NAMES[p]) for t, p in zip(truth, pred) if t != p)
    wrong = np.array(wrong)
    print("A. squares  (%d photos)" % len(wrong))
    print("   square accuracy        %.2f%%" % (100 * (1 - wrong.sum() / (64.0 * len(wrong)))))
    print("   boards fully correct   %.1f%%" % (100 * (wrong == 0).mean()))
    print("   wrong squares / board  mean %.2f  median %d  95th pct %d  max %d"
          % (wrong.mean(), np.median(wrong), np.percentile(wrong, 95), wrong.max()))
    print("   top confusions (truth -> predicted): "
          + ", ".join("%s->%s %d" % (t, p, n) for (t, p), n in confusion.most_common(6)))


def teacher_forced(games, engine):
    n = ok_given = ok_auto = orient_ok = 0
    for rows in games.values():
        engine.position(START_FEN)
        for r in rows:
            truth = true_move(engine, r["labels"])
            fen, legal = engine.fen(), engine.moves()
            k, _ = best_orientation(r["grid"], placement_from_fen(fen))
            orient_ok += k == r["orientation"]
            ok_given += decode_move(fen, r["grid"][grid_of_square(r["orientation"])], legal)[0].uci == truth
            ok_auto += decode_move(fen, r["grid"][grid_of_square(k)], legal)[0].uci == truth
            n += 1
            if truth is not None:
                engine.move(truth)
    print("B. moves, teacher-forced  (%d photos)" % n)
    print("   orientation given      %.2f%% of moves right" % (100.0 * ok_given / n))
    print("   orientation auto       %.2f%% of moves right, orientation itself right on %.2f%%"
          % (100.0 * ok_auto / n, 100.0 * orient_ok / n))


def free_running(games, engine):
    print("   free-running, orientation auto:")
    for g, rows in sorted(games.items()):
        engine.position(START_FEN)
        truth = []
        for r in rows:
            m = true_move(engine, r["labels"])
            if m is not None:
                truth.append(m)
                engine.move(m)
        engine.position(START_FEN)
        dec = GameDecoder(engine)
        for r in rows:
            k, _ = best_orientation(r["grid"], placement_from_fen(engine.fen()))
            dec.feed(r["grid"][grid_of_square(k)])
        res = dec.finish()
        same = sum(a == b for a, b in zip(res.ucis, truth))
        first = next((i for i, (a, b) in enumerate(zip(res.ucis, truth)) if a != b), None)
        print("     game %3d: %d / %d plies right, %d recovered, %s" % (g, same, len(truth), sum(p.recovered for p in res.plies),
              "whole game exact" if res.ucis == truth else "first error at ply %s" % (first if first is not None else len(res.ucis))))


def timing(ds, clf, split, n):
    from chessvision.board import find_corners
    times = []
    for s in list(ds.samples(split))[:n + 1]:
        image = cv2.imread(s.path)
        t0 = time.time()
        clf.probs(image, 0, find_corners(image))
        times.append(time.time() - t0)
    times = times[1:]  # the first call pays for model warm-up
    print("C. speed  %.0f ms per photo (median of %d, %s, file reading excluded)"
          % (1000 * np.median(times), len(times), clf.dev))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--time-photos", type=int, default=30)
    args = ap.parse_args()
    ds, clf = ChessReD(), SquareClassifier()
    games = load_games(ds, args.split)
    for rows in games.values():
        for r in rows:
            r["grid"] = clf.grid_probs(cv2.imread(os.path.join(CACHE, r["file"])))
    squares_report(games)
    with EngineClient() as engine:
        teacher_forced(games, engine)
        free_running(games, engine)
    if args.time_photos:
        timing(ds, clf, args.split, args.time_photos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
