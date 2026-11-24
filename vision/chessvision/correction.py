"""The human-correction prompt (pass V4): asked only when the decoder is not sure about a photo.

`make_prompt` returns an AskFn for pipeline.GameDecoder. It lists the best candidates in SAN and
reads one line: a number picks a candidate, Enter takes the first, a typed move (SAN or UCI) is
accepted if it is legal, "s" postpones the photo to be decoded with the next one, "n" says the
board did not change. Legality is the engine's answer, never decided here.
"""
from __future__ import annotations

import sys
from typing import Callable, List, Optional, Sequence

from .decoder import Candidate
from .engine import EngineClient
from .pipeline import HOLD, NO_MOVE, AskFn


def _plain(san: str) -> str:
    return san.rstrip("+#!?").replace("0", "O")


def resolve(answer: str, shown: Sequence[Optional[str]], legal: Sequence[str], sans: Sequence[str]) -> Optional[str]:
    """Turn one typed line into a uci, HOLD or NO_MOVE; None if it is not understood or not legal.

    shown: the uci of each listed candidate (None = no move). legal/sans: every legal move and its SAN.
    """
    a = answer.strip()
    if a == "":
        a = "1"
    if a.lower() == "s":
        return HOLD
    if a.lower() == "n":
        return NO_MOVE
    if a.isdigit():
        if not 1 <= int(a) <= len(shown):
            return None
        pick = shown[int(a) - 1]
        return NO_MOVE if pick is None else pick
    if a.lower() in legal:
        return a.lower()
    matches = [u for u, s in zip(legal, sans) if _plain(s) == _plain(a)]
    return matches[0] if len(matches) == 1 else None


def make_prompt(engine: EngineClient, read: Callable[[str], str] = input, out=sys.stderr,
                before: Optional[Callable[[], None]] = None, top: int = 3) -> AskFn:
    """An AskFn that prints the candidates to `out` and reads the answer with `read`.

    `before` is called first, e.g. to save and show the photo with the detected grid drawn on it.
    Precondition: the engine holds the position the candidates were computed for.
    """
    def ask(fen: str, cands: Sequence[Candidate]) -> Optional[str]:
        if before is not None:
            before()
        legal: List[str] = engine.moves()
        sans = [engine.san(u) for u in legal]
        san_of = dict(zip(legal, sans))
        shown = [c.uci for c in cands[:top]]
        print("  not sure. Position: %s" % fen, file=out)
        for i, c in enumerate(cands[:top], 1):
            name = "no move" if c.uci is None else "%s (%s)" % (san_of[c.uci], c.uci)
            print("    %d. %-16s fit %7.1f" % (i, name, c.score), file=out)
        while True:
            chosen = resolve(read("  number, a move, s = decide with the next photo, n = no move [1]: "), shown, legal, sans)
            if chosen is not None:
                return chosen
            print("  not a legal move here; try again", file=out)
    return ask
