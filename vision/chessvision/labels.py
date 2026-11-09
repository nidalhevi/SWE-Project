"""Square labels shared with the C engine (src/types.h): EMPTY=0, WP..WK=1..6, BP..BK=7..12.

Square indexing is a1 = 0 ... h8 = 63, file fastest, exactly as in the engine.
"""
from __future__ import annotations

from typing import List

N_CLASSES = 13
EMPTY = 0
NAMES = ["EMPTY", "WP", "WN", "WB", "WR", "WQ", "WK", "BP", "BN", "BB", "BR", "BQ", "BK"]
FEN_CHARS = ".PNBRQKpnbrqk"  # index = label

LABEL_OF_CHAR = {c: i for i, c in enumerate(FEN_CHARS) if c != "."}


def square(name: str) -> int:
    """'e4' -> 28. Precondition: two chars a-h, 1-8."""
    return (ord(name[0]) - ord("a")) + 8 * (ord(name[1]) - ord("1"))


def square_name(sq: int) -> str:
    return "abcdefgh"[sq & 7] + str((sq >> 3) + 1)


def placement_from_fen(fen: str) -> List[int]:
    """Parse the first FEN field into a 64-entry label list (a1 first).

    Precondition: a well-formed placement (the engine already validated the FEN).
    """
    board = [EMPTY] * 64
    ranks = fen.split()[0].split("/")
    if len(ranks) != 8:
        raise ValueError("FEN placement needs 8 ranks")
    for r, row in enumerate(ranks):
        rank = 7 - r
        file = 0
        for ch in row:
            if ch.isdigit():
                file += int(ch)
            else:
                board[rank * 8 + file] = LABEL_OF_CHAR[ch]
                file += 1
        if file != 8:
            raise ValueError("rank %d has %d files" % (rank + 1, file))
    return board


def placement_to_fen(board: List[int]) -> str:
    """Inverse of placement_from_fen (first FEN field only)."""
    rows = []
    for rank in range(7, -1, -1):
        row, empties = "", 0
        for file in range(8):
            p = board[rank * 8 + file]
            if p == EMPTY:
                empties += 1
            else:
                if empties:
                    row += str(empties)
                    empties = 0
                row += FEN_CHARS[p]
        if empties:
            row += str(empties)
        rows.append(row)
    return "/".join(rows)
