#!/usr/bin/env python3
"""
Differential test: our C engine vs python-chess (the oracle).

Contract with the C binary (see SPEC.md §CLI and src/play.h):
    ./chess moves  "<fen>"          -> legal moves, UCI, sorted, one per line
    ./chess divide <depth> "<fen>"  -> "<uci> <nodes>" per root move, then "total <n>"
    ./chess batch                   -> line protocol: position/move/moves/status/san/fen/quit

Modes:
    --games N        play N random games through one `chess batch` process per worker;
                     at every ply compare the legal-move set, the game-over verdict and the
                     SAN of the chosen move. Exit 1 on the first mismatch (with the move
                     list that reproduces it). --jobs splits the games over CPU cores.
    --divide FEN D   print root moves whose perft(D-1) subtree differs from python-chess.
    --fen FEN        compare the move list for one position.

pip install chess
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import random
import subprocess
import sys

import chess

BIN = "./build/debug/chess"
START_FEN = chess.STARTING_FEN


# ----------------------------------------------------------------- one-shot CLI --

def run(*args: str) -> list[str]:
    p = subprocess.run([BIN, *args], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"{BIN} {' '.join(args)!r} exited {p.returncode}: {p.stderr.strip()}")
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def theirs_moves(board: chess.Board) -> list[str]:
    return sorted(m.uci() for m in board.legal_moves)


def compare_position(board: chess.Board) -> bool:
    fen = board.fen()
    a, b = sorted(run("moves", fen)), theirs_moves(board)
    if a == b:
        return True
    print(f"MISMATCH at {fen}")
    print(f"  ours   - theirs: {sorted(set(a) - set(b))}")
    print(f"  theirs - ours  : {sorted(set(b) - set(a))}")
    return False


def perft(board: chess.Board, depth: int) -> int:
    if depth == 0:
        return 1
    return sum(_perft_child(board, m, depth) for m in board.legal_moves)


def _perft_child(board: chess.Board, m: chess.Move, depth: int) -> int:
    board.push(m)
    n = perft(board, depth - 1)
    board.pop()
    return n


def divide(fen: str, depth: int) -> int:
    board = chess.Board(fen)
    ours = {}
    for ln in run("divide", str(depth), fen):
        k, v = ln.split()
        if k != "total":
            ours[k] = int(v)
    theirs = {m.uci(): _perft_child(board, m, depth) for m in board.legal_moves}
    bad = 0
    for mv in sorted(set(ours) | set(theirs)):
        o, t = ours.get(mv), theirs.get(mv)
        if o != t:
            bad += 1
            print(f"{mv}: ours={o} theirs={t}")
    print("OK: all root subtrees agree" if not bad else f"{bad} root move(s) differ; recurse with --divide on the child FEN")
    return 1 if bad else 0


# ------------------------------------------------------------------- batch games --

def verdict(board: chess.Board) -> str:
    """python-chess's answer in the same words and precedence as src/game.c."""
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material():
        return "insufficient-material"
    if board.is_fifty_moves():
        return "fifty-moves"
    if board.is_repetition(3):
        return "threefold-repetition"
    return "ongoing"


class Engine:
    """One `chess batch` process: send a line, read a line."""

    def __init__(self, binary: str):
        self.p = subprocess.Popen([binary, "batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def cmd(self, line: str) -> str:
        assert self.p.stdin and self.p.stdout
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        out = self.p.stdout.readline()
        if out == "":
            sys.exit(f"engine died on {line!r} (exit {self.p.poll()})")
        return out.rstrip("\n")

    def close(self) -> None:
        try:
            self.cmd("quit")
        except SystemExit:
            pass
        self.p.wait()


def play_game(eng: Engine, game: int, seed: int, max_plies: int) -> tuple[int, str | None]:
    """Returns (positions compared, None) or (positions, mismatch report)."""
    rng = random.Random(f"{seed}:{game}")
    board = chess.Board()
    history: list[str] = []
    eng.cmd(f"position {START_FEN}")

    def report(what: str, ours: str, theirs: str) -> str:
        return (f"MISMATCH game {game} ply {board.ply()} ({what})\n  fen    {board.fen()}\n"
                f"  ours   {ours}\n  theirs {theirs}\n  moves  {' '.join(history)}")

    for ply in range(max_plies + 1):
        ours, theirs = eng.cmd("moves").split(), theirs_moves(board)
        if ours != theirs:
            return ply, report("legal moves", " ".join(sorted(set(ours) - set(theirs))) or "-",
                               " ".join(sorted(set(theirs) - set(ours))) or "-")
        status, want = eng.cmd("status"), verdict(board)
        if status != want:
            return ply, report("status", status, want)
        if status != "ongoing" or ply == max_plies:
            return ply + 1, None
        mv = rng.choice(list(board.legal_moves))
        san = eng.cmd(f"san {mv.uci()}")
        if san != board.san(mv):
            return ply, report(f"SAN of {mv.uci()}", san, board.san(mv))
        if eng.cmd(f"move {mv.uci()}") != "ok":
            return ply, report(f"make {mv.uci()}", "refused", "legal")
        board.push(mv)
        history.append(mv.uci())
    return max_plies, None


def worker(args: tuple[str, int, int, int, int]) -> tuple[int, str | None]:
    binary, seed, first, count, max_plies = args
    eng, positions = Engine(binary), 0
    try:
        for g in range(first, first + count):
            n, bad = play_game(eng, g, seed, max_plies)
            positions += n
            if bad:
                return positions, bad
    finally:
        eng.close()
    return positions, None


def games(n: int, seed: int, jobs: int, max_plies: int) -> int:
    jobs = max(1, min(jobs, n))
    chunk = (n + jobs - 1) // jobs
    tasks = [(BIN, seed, first, min(chunk, n - first), max_plies) for first in range(0, n, chunk)]
    with multiprocessing.Pool(len(tasks)) as pool:
        results = pool.map(worker, tasks)
    positions = sum(p for p, _ in results)
    for _, bad in results:
        if bad:
            print(bad)
            return 1
    print(f"OK: {n} games, {positions} positions, zero disagreements (moves, verdicts, SAN)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=BIN)
    ap.add_argument("--games", type=int)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--max-plies", type=int, default=600, help="stop a game that is still going (undo stack holds 1024)")
    ap.add_argument("--divide", nargs=2, metavar=("FEN", "DEPTH"))
    ap.add_argument("--fen")
    a = ap.parse_args()
    BIN = a.bin
    if a.games:
        sys.exit(games(a.games, a.seed, a.jobs, a.max_plies))
    if a.divide:
        sys.exit(divide(a.divide[0], int(a.divide[1])))
    if a.fen:
        sys.exit(0 if compare_position(chess.Board(a.fen)) else 1)
    ap.print_help()
