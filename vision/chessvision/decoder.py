"""The decoder: pick the legal move whose resulting board best explains the observation.

Input: the previous position (FEN), its legal moves (from the engine) and an
observation `probs[64][13]` (per-square class probabilities, a1 first).
Score of a move m: log-likelihood of the board after m under `probs`.
Only the squares m changes differ between candidates, so the shared part is
computed once and each move adds a small delta. A "no move" hypothesis (uci
None) catches duplicate or premature photos.

The board after a move is derived here from the UCI string alone, which is
exact *because the move is known to be legal*: a king moving two files is a
castle, a pawn moving diagonally onto an empty square is en passant, a fifth
character is a promotion. No legality is ever decided in this file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .labels import EMPTY, N_CLASSES, LABEL_OF_CHAR, placement_from_fen, square

WP, WN, WB, WR, WQ, WK = 1, 2, 3, 4, 5, 6
BP, BN, BB, BR, BQ, BK = 7, 8, 9, 10, 11, 12
LOG_FLOOR = 1e-6  # probabilities are clipped here before log so a 0 never vetoes a move outright


@dataclass
class Candidate:
    uci: Optional[str]      # None = board unchanged
    score: float            # log-likelihood of the resulting board
    changes: Dict[int, int]  # square -> new label (empty for the no-move hypothesis)


def _is_white(p: int) -> bool:
    return 1 <= p <= 6


def move_changes(board: Sequence[int], uci: str) -> Dict[int, int]:
    """Squares changed by playing legal `uci` on `board`, as {square: new_label}.

    Precondition: `uci` is legal in the position `board` belongs to.
    """
    frm, to = square(uci[0:2]), square(uci[2:4])
    piece = board[frm]
    assert piece != EMPTY, "move from an empty square: %s" % uci
    white = _is_white(piece)
    changes = {frm: EMPTY, to: piece}
    if len(uci) == 5:  # promotion: colour the promoted piece correctly
        changes[to] = LABEL_OF_CHAR[uci[4].upper() if white else uci[4].lower()]
    if piece in (WK, BK) and abs((to & 7) - (frm & 7)) == 2:  # castling moves the rook too
        rank = frm & ~7
        if to & 7 == 6:
            changes[rank + 7], changes[rank + 5] = EMPTY, (WR if white else BR)
        else:
            changes[rank + 0], changes[rank + 3] = EMPTY, (WR if white else BR)
    if piece in (WP, BP) and (frm & 7) != (to & 7) and board[to] == EMPTY:  # en passant
        changes[to - 8 if white else to + 8] = EMPTY
    return changes


def apply_changes(board: Sequence[int], changes: Dict[int, int]) -> List[int]:
    out = list(board)
    for sq, lab in changes.items():
        out[sq] = lab
    return out


def decode_move(prev_fen: str, probs: np.ndarray, legal_moves: Sequence[str],
                include_no_move: bool = True) -> List[Candidate]:
    """Rank `legal_moves` by how well the board after each explains `probs`.

    Precondition: probs has shape (64, 13), rows are probabilities (need not be
    exactly normalised). Postcondition: candidates sorted by score descending;
    if include_no_move, one candidate has uci None.
    """
    probs = np.asarray(probs, dtype=np.float64)
    if probs.shape != (64, N_CLASSES):
        raise ValueError("probs must be (64, 13), got %r" % (probs.shape,))
    logp = np.log(np.clip(probs, LOG_FLOOR, None))
    board = placement_from_fen(prev_fen)
    base = float(sum(logp[sq, board[sq]] for sq in range(64)))

    out: List[Candidate] = []
    if include_no_move:
        out.append(Candidate(None, base, {}))
    for uci in legal_moves:
        ch = move_changes(board, uci)
        delta = sum(logp[sq, lab] - logp[sq, board[sq]] for sq, lab in ch.items())
        out.append(Candidate(uci, base + float(delta), ch))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def confidence(cands: Sequence[Candidate]) -> float:
    """Log-likelihood gap between the best and second-best candidate (0 if only one)."""
    if len(cands) < 2:
        return 0.0
    return cands[0].score - cands[1].score


def to_tuples(cands: Sequence[Candidate]) -> List[Tuple[Optional[str], float]]:
    return [(c.uci, c.score) for c in cands]
