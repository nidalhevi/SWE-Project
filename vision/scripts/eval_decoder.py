#!/usr/bin/env python3
"""Pass V1 evaluation: decoder accuracy vs number of wrong squares per observation.

Games come from python-chess (random legal moves), observations from
chessvision.synthetic.observe. Two numbers per noise level:
  ply top-1   : decode each ply from the *true* previous position (teacher forced)
  games exact : decode_game follows its own choices; fraction of games reproduced exactly
Usage: python3 vision/scripts/eval_decoder.py --games 200 [--plies 80] [--levels 0,1,3,5,8] [--seed 1]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import chess  # noqa: E402  (python-chess, the game generator / oracle)

from chessvision.decoder import decode_move  # noqa: E402
from chessvision.engine import EngineClient  # noqa: E402
from chessvision.pipeline import decode_game  # noqa: E402
from chessvision.synthetic import observe  # noqa: E402


def board_labels(b: chess.Board):
    out = [0] * 64
    for sq, pc in b.piece_map().items():
        out[sq] = pc.piece_type if pc.color == chess.WHITE else pc.piece_type + 6
    return out


def random_game(rng: np.random.Generator, max_plies: int):
    """List of (prev_fen, uci, labels_after) for one random game."""
    b = chess.Board()
    plies = []
    for _ in range(max_plies):
        legal = list(b.legal_moves)
        if not legal or b.is_game_over():
            break
        m = legal[int(rng.integers(len(legal)))]
        prev = b.fen()
        b.push(m)
        plies.append((prev, m.uci(), board_labels(b)))
    return plies


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--plies", type=int, default=80)
    ap.add_argument("--levels", default="0,1,3,5,8")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--bin", default=None)
    a = ap.parse_args()
    levels = [int(x) for x in a.levels.split(",")]
    rng = np.random.default_rng(a.seed)
    games = [random_game(rng, a.plies) for _ in range(a.games)]
    n_plies = sum(len(g) for g in games)
    print("games %d, plies %d, mean length %.1f" % (len(games), n_plies, n_plies / max(1, len(games))))
    print("%-14s %10s %12s %9s" % ("wrong squares", "ply top-1", "games exact", "secs"))
    with EngineClient(a.bin) as eng:
        for k in levels:
            t0 = time.time()
            hit = 0
            exact = 0
            for g in games:
                obs = [observe(lab, k, rng) for (_, _, lab) in g]
                for (prev, uci, _), o in zip(g, obs):
                    eng.position(prev)
                    if decode_move(prev, o, eng.moves())[0].uci == uci:
                        hit += 1
                res = decode_game(iter(obs), eng)
                exact += int(res.ucis == [u for (_, u, _) in g])
            print("%-14d %9.2f%% %11.1f%% %9.1f" % (k, 100.0 * hit / n_plies, 100.0 * exact / len(games), time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
