"""Synthetic observations for pass V1: a true board -> noisy per-square probabilities.

The noise model stands in for the square classifier of pass V3 and is meant to
be *harder* than a real one in the way that matters: the wrong squares are
confusions a camera classifier actually makes (pawn/bishop, knight/bishop,
rook/queen, king/queen, colour swaps, piece/empty), not uniform flips.
"""
from __future__ import annotations

from typing import List, Sequence

import numpy as np

from .labels import EMPTY, N_CLASSES

# plausible confusions per class (same colour unless the swap is a colour swap)
_CONFUSE = {
    0: [1, 7, 3, 9],              # empty <-> pawn or bishop (shadows)
    1: [3, 2, 0, 7], 2: [3, 1, 8], 3: [1, 2, 9, 0], 4: [5, 10, 1], 5: [4, 6, 11], 6: [5, 12, 3],
    7: [9, 8, 0, 1], 8: [9, 7, 2], 9: [7, 8, 3, 0], 10: [11, 4, 7], 11: [10, 12, 5], 12: [11, 6, 9],
}


def observe(board: Sequence[int], wrong_squares: int, rng: np.random.Generator,
            sharp: float = 4.0, margin: float = 1.0, jitter: float = 0.5) -> np.ndarray:
    """Return probs (64,13) whose argmax is wrong on exactly `wrong_squares` squares.

    Precondition: 0 <= wrong_squares <= 64. The correct class keeps the second
    highest logit on corrupted squares (a confused classifier, not a blind one).
    """
    logits = rng.normal(0.0, jitter, size=(64, N_CLASSES))
    for sq in range(64):
        logits[sq, board[sq]] += sharp
    if wrong_squares:
        for sq in rng.choice(64, size=wrong_squares, replace=False):
            wrong = int(rng.choice(_CONFUSE[board[sq]]))
            logits[sq, wrong] = logits[sq, board[sq]] + margin
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    return p / p.sum(axis=1, keepdims=True)


def one_hot(board: Sequence[int]) -> np.ndarray:
    p = np.full((64, N_CLASSES), 1e-9)
    for sq in range(64):
        p[sq, board[sq]] = 1.0
    return p / p.sum(axis=1, keepdims=True)
