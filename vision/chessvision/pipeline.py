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

# A photo is unreadable if even the best move explains it worse than this mean log-likelihood per
# square. Good photos score around -0.1; a board found one square off scores below -0.6, and can
# still show a confident-looking gap between two wrong moves, so the gap alone is not enough.
MIN_FIT = -0.4

HOLD = "hold"        # an AskFn may answer this: do not play, decode this photo with the next one
NO_MOVE = "no-move"  # or this: the photo shows the position unchanged

AskFn = Callable[[str, Sequence[Candidate]], Optional[str]]  # (fen, candidates) -> uci, HOLD, NO_MOVE, or None = take the best


@dataclass
class Ply:
    uci: str
    san: str
    confidence: float
    asked: bool = False
    recovered: bool = False   # decoded together with the next photo because this one was unreadable


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


class GameDecoder:
    """Feed observations one at a time; the engine holds the game.

    A photo the decoder cannot read with confidence (typically a failed board detection: no
    legal move explains it better than the others) is not played. It is *held*, and the next
    photo is decoded as two plies at once, scoring every legal pair of moves against both
    photos. One bad photo therefore costs nothing instead of derailing the rest of the game.
    With an `ask` callback the human is asked instead, as in pass V4.
    """

    def __init__(self, engine: EngineClient, threshold: float = 2.0, ask: Optional[AskFn] = None,
                 min_fit: float = MIN_FIT):
        self.engine, self.threshold, self.ask, self.min_fit = engine, threshold, ask, min_fit
        self.res = GameResult()
        self.held: Optional[np.ndarray] = None

    def feed(self, obs: np.ndarray) -> List[Ply]:
        """Plies played because of this observation: none (no move, or held), one, or two."""
        if self.engine.status() != "ongoing":
            return []
        if self.held is not None:
            return self._feed_after_held(obs)
        fen = self.engine.fen()
        cands = decode_move(fen, obs, self.engine.moves())
        conf, best = confidence(cands), cands[0].uci
        if conf < self.threshold or cands[0].score / 64 < self.min_fit:
            if self.ask is None:
                self.held = obs
                return []
            chosen = self.ask(fen, cands)
            if chosen == HOLD:
                self.held = obs
                return []
            if chosen is not None:
                return self._play([None if chosen == NO_MOVE else chosen], conf, asked=True)
        return self._play([best], conf)

    def _feed_after_held(self, obs: np.ndarray) -> List[Ply]:
        held, self.held = self.held, None
        lines = decode_two(self.engine, held, obs)
        conf = lines[0][1] - lines[1][1] if len(lines) > 1 else 0.0
        return self._play(lines[0][0], conf, recovered=True)

    def _play(self, ucis: Sequence[Optional[str]], conf: float, asked: bool = False,
              recovered: bool = False) -> List[Ply]:
        played = []
        for uci in ucis:
            if uci is None:
                self.res.skipped += 1
                continue
            san = self.engine.san(uci)
            self.engine.move(uci)
            played.append(Ply(uci, san, conf, asked, recovered))
        self.res.plies.extend(played)
        return played

    def finish(self) -> GameResult:
        """Play the best reading of a photo still held (the last one), then report."""
        if self.held is not None and self.engine.status() == "ongoing":
            held, self.held = self.held, None
            cands = decode_move(self.engine.fen(), held, self.engine.moves())
            self._play([cands[0].uci], confidence(cands))
        self.res.final_fen = self.engine.fen()
        self.res.status = self.engine.status()
        return self.res


def decode_two(engine: EngineClient, first: np.ndarray, second: np.ndarray):
    """Rank what happened across two photos: [(moves, score)], best first.

    `moves` is [m1, m2] (a ply per photo), or [None, m] (the first photo showed no move).
    Score = log-likelihood of the first photo after m1 plus that of the second after m1, m2.
    Postcondition: the engine is back at the position it started from.
    """
    fen = engine.fen()
    firsts = decode_move(fen, first, engine.moves())
    lines = []
    for c in firsts:
        if c.uci is not None:
            engine.move(c.uci)
        if engine.status() == "ongoing":
            seconds = decode_move(engine.fen(), second, engine.moves(), include_no_move=False)
            lines.extend(([c.uci, s.uci], c.score + s.score) for s in seconds[:3])
        if c.uci is not None:
            engine.undo()
    lines.sort(key=lambda t: t[1], reverse=True)
    return lines or [([firsts[0].uci], firsts[0].score)]


def decode_game(observations: Iterable[np.ndarray], engine: EngineClient,
                start_fen: str = START_FEN, threshold: float = 2.0,
                ask: Optional[AskFn] = None) -> GameResult:
    """Decode a whole game. Precondition: `engine` is open; observations are (64,13) arrays.

    Postcondition: the engine holds the final position; the result lists every
    ply played, with the engine's SAN and the decoder's confidence.
    """
    engine.position(start_fen)
    dec = GameDecoder(engine, threshold, ask)
    for obs in observations:
        dec.feed(obs)
    return dec.finish()
