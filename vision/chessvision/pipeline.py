"""decode_game: a sequence of observations -> moves -> PGN, with the engine as oracle.

Each observation is the per-square probability array taken *after* a move.
For every observation the decoder ranks the engine's legal moves; the best one
is played in the engine (which then tracks castling rights, en passant, clocks
and repetition), its SAN is recorded, and the PGN is assembled at the end.
Low-confidence plies are handed to an optional `ask` callback (the human
correction hook of pass V4); without it the best candidate is taken.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence

import numpy as np

from .decoder import Candidate, confidence, decode_move
from .engine import START_FEN, EngineClient

AskFn = Callable[[str, Sequence[Candidate]], Optional[str]]  # (fen, candidates) -> chosen uci or None


@dataclass
class Ply:
    uci: str
    san: str
    confidence: float
    asked: bool = False


@dataclass
class GameResult:
    plies: List[Ply] = field(default_factory=list)
    skipped: int = 0            # observations decoded as "no move"
    final_fen: str = START_FEN
    status: str = "ongoing"

    @property
    def ucis(self) -> List[str]:
        return [p.uci for p in self.plies]

    def pgn(self, headers: Optional[dict] = None) -> str:
        """PGN movetext from the engine's SAN strings; result tag from the engine's status."""
        hdr = {"Event": "chessvision", "Site": "?", "Date": "????.??.??",
               "Round": "?", "White": "?", "Black": "?"}
        hdr.update(headers or {})
        result = _result_tag(self.status, len(self.plies))
        hdr["Result"] = result
        lines = ['[%s "%s"]' % (k, v) for k, v in hdr.items()]
        tokens: List[str] = []
        for i, p in enumerate(self.plies):
            if i % 2 == 0:
                tokens.append("%d." % (i // 2 + 1))
            tokens.append(p.san)
        tokens.append(result)
        return "\n".join(lines) + "\n\n" + _wrap(tokens) + "\n"


def _result_tag(status: str, nplies: int) -> str:
    if status == "checkmate":
        return "0-1" if nplies % 2 == 0 else "1-0"  # side to move after an even number of plies is White
    if status in ("stalemate", "insufficient-material", "fifty-moves", "threefold-repetition"):
        return "1/2-1/2"
    return "*"


def _wrap(tokens: Sequence[str], width: int = 79) -> str:
    lines, cur = [], ""
    for t in tokens:
        if cur and len(cur) + 1 + len(t) > width:
            lines.append(cur)
            cur = t
        else:
            cur = (cur + " " + t) if cur else t
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def decode_game(observations: Iterable[np.ndarray], engine: EngineClient,
                start_fen: str = START_FEN, threshold: float = 2.0,
                ask: Optional[AskFn] = None) -> GameResult:
    """Decode a whole game. Precondition: `engine` is open; observations are (64,13) arrays.

    Postcondition: the engine holds the final position; the result lists every
    ply played, with the engine's SAN and the decoder's confidence.
    """
    engine.position(start_fen)
    res = GameResult()
    for obs in observations:
        status = engine.status()
        if status != "ongoing":
            break
        fen = engine.fen()
        cands = decode_move(fen, obs, engine.moves())
        conf = confidence(cands)
        best = cands[0].uci
        asked = False
        if conf < threshold and ask is not None:
            chosen = ask(fen, cands)
            if chosen is not None:
                best, asked = chosen, True
        if best is None:
            res.skipped += 1
            continue
        san = engine.san(best)
        engine.move(best)
        res.plies.append(Ply(best, san, conf, asked))
    res.final_fen = engine.fen()
    res.status = engine.status()
    return res
