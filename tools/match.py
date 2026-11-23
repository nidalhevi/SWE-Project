#!/usr/bin/env python3
"""Play a match between two UCI engines and estimate the Elo difference.

A small stand-in for cutechess-cli (not packaged for Homebrew; building it needs Qt): the engines
are driven over UCI by python-chess, which also referees the games. Each opening is played twice
with colours swapped, so an unbalanced opening does not favour one engine.

Usage:
  python3 tools/match.py --games 40 --movetime 0.1                      # chess-c against itself
  python3 tools/match.py --b stockfish --b-elo 1500 --games 40          # against Stockfish limited to 1500
  python3 tools/match.py --a ./build/release/chess --b ./old/chess      # two builds of ours
An engine command with arguments is quoted: --a "./build/release/chess uci" is the default.
Prints wins/draws/losses for engine A and the Elo difference with a 95% interval.
"""
from __future__ import annotations

import argparse
import math
import shlex
import sys

import chess
import chess.engine

# Short, sound openings (UCI). Variety matters: both engines are deterministic.
OPENINGS = [
    "e2e4 e7e5 g1f3 b8c6", "e2e4 c7c5 g1f3 d7d6", "d2d4 d7d5 c2c4 e7e6", "d2d4 g8f6 c2c4 g7g6",
    "e2e4 e7e6 d2d4 d7d5", "e2e4 c7c6 d2d4 d7d5", "c2c4 e7e5 b1c3 g8f6", "g1f3 d7d5 g2g3 g8f6",
    "e2e4 e7e5 g1f3 g8f6", "d2d4 d7d5 g1f3 g8f6", "e2e4 d7d6 d2d4 g8f6", "d2d4 f7f5 g2g3 g8f6",
    "e2e4 g7g6 d2d4 f8g7", "b2b3 e7e5 c1b2 b8c6", "e2e4 e7e5 b1c3 g8f6", "d2d4 g8f6 g1f3 e7e6",
    "e2e4 c7c5 b1c3 b8c6", "c2c4 c7c5 g1f3 g8f6", "e2e4 e7e5 f1c4 g8f6", "d2d4 d7d5 c1f4 g8f6",
]


def open_engine(command: str, elo: int):
    engine = chess.engine.SimpleEngine.popen_uci(shlex.split(command))
    if elo:
        engine.configure({"UCI_LimitStrength": True, "UCI_Elo": elo})
    return engine


def play_game(white, black, opening: str, movetime: float, max_plies: int) -> str:
    """One game from the opening; returns '1-0', '0-1' or '1/2-1/2' (also when max_plies is reached)."""
    board = chess.Board()
    for uci in opening.split():
        board.push_uci(uci)
    limit = chess.engine.Limit(time=movetime)
    while not board.is_game_over(claim_draw=True) and board.ply() < max_plies:
        engine = white if board.turn == chess.WHITE else black
        move = engine.play(board, limit).move
        if move is None or move not in board.legal_moves:
            return "0-1" if board.turn == chess.WHITE else "1-0"   # an illegal or missing move loses
        board.push(move)
    result = board.result(claim_draw=True)
    return result if result != "*" else "1/2-1/2"


def elo_from_score(score: float) -> float:
    score = min(max(score, 1e-3), 1 - 1e-3)
    return -400.0 * math.log10(1.0 / score - 1.0)


def summary(wins: int, draws: int, losses: int) -> str:
    n = wins + draws + losses
    score = (wins + 0.5 * draws) / n
    var = (wins * (1 - score) ** 2 + draws * (0.5 - score) ** 2 + losses * score ** 2) / n
    half = 1.96 * math.sqrt(var / n)
    return ("A: +%d =%d -%d  score %.1f%%  Elo difference %+.0f (95%% interval %+.0f to %+.0f)"
            % (wins, draws, losses, 100 * score, elo_from_score(score),
               elo_from_score(score - half), elo_from_score(score + half)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", default="./build/release/chess uci")
    ap.add_argument("--b", default="./build/release/chess uci")
    ap.add_argument("--a-elo", type=int, default=0, help="limit engine A with UCI_Elo (Stockfish)")
    ap.add_argument("--b-elo", type=int, default=0)
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--movetime", type=float, default=0.1, help="seconds per move")
    ap.add_argument("--max-plies", type=int, default=300)
    args = ap.parse_args()
    a, b = open_engine(args.a, args.a_elo), open_engine(args.b, args.b_elo)
    wins = draws = losses = 0
    try:
        for g in range(args.games):
            a_white = g % 2 == 0
            result = play_game(a if a_white else b, b if a_white else a, OPENINGS[(g // 2) % len(OPENINGS)],
                               args.movetime, args.max_plies)
            a_points = {"1-0": 1, "0-1": 0, "1/2-1/2": 0.5}[result] if a_white else {"1-0": 0, "0-1": 1, "1/2-1/2": 0.5}[result]
            wins, draws, losses = wins + (a_points == 1), draws + (a_points == 0.5), losses + (a_points == 0)
            print("game %3d  A is %s  %s" % (g + 1, "white" if a_white else "black", result), flush=True)
    finally:
        a.quit()
        b.quit()
    print(summary(wins, draws, losses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
