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

from .decoder import (TYPE_WEIGHT, Candidate, apply_changes, colour_first, colour_fit, confidence,
                      decode_move, label_fit)
from .engine import START_FEN, EngineClient
from .labels import placement_from_fen

# When is a photo unreadable (typically: the grid was found off the board)? The gap between the
# two best moves is not enough: two wrong moves can differ confidently by chance. Two tests on
# how well the best move explains the photo, both calibrated 2026-11-25 on five ChessReD games
# and our own first game, each with every photo also shifted one square in four directions:
#   MIN_FIT   the colours (empty / white / black per square, decoder.colour_fit) must fit at
#             least this well. Well-read photos: about -0.04 on ChessReD, -0.06 to -0.25 on our
#             board; shifted grids: -1.5 typically.
#   MAX_DROP  the exact labels (decoder.label_fit) must not fit much worse than in the photos
#             accepted so far in this game (median of the last FIT_WINDOW). Shifted grids drop
#             by about 2; the largest drop of a good photo was 0.42 on ChessReD, 0.13 on ours.
# Until 2026-11-25 the rule was "label fit above -0.4", an absolute level that only ChessReD's
# piece set reaches: on our own set it marked all 59 photos unreadable.
MIN_FIT = -0.35
MAX_DROP = 0.3
FIT_WINDOW = 15

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
                 min_fit: float = MIN_FIT, type_weight: float = TYPE_WEIGHT):
        self.engine, self.threshold, self.ask, self.min_fit = engine, threshold, ask, min_fit
        self.type_weight = type_weight
        self.res = GameResult()
        self.held: Optional[np.ndarray] = None   # a held photo, already colour-first weighted
        self._fits: List[float] = []             # label fit of the photos accepted so far

    def feed(self, obs: np.ndarray) -> List[Ply]:
        """Plies played because of this observation: none (no move, or held), one, or two.

        Precondition: obs is the classifier's (64, 13) output, a1 first. Moves are ranked on
        its colour-first weighting (decoder.colour_first); whether the photo is readable at all
        is judged by MIN_FIT and MAX_DROP above.
        """
        if self.engine.status() != "ongoing":
            return []
        raw, obs = obs, colour_first(obs, self.type_weight)
        if self.held is not None:
            return self._feed_after_held(obs)
        fen = self.engine.fen()
        cands = decode_move(fen, obs, self.engine.moves())
        conf, best = confidence(cands), cands[0].uci
        after = apply_changes(placement_from_fen(fen), cands[0].changes)
        fit = label_fit(raw, after)
        if conf >= self.threshold and colour_fit(raw, after) >= self.min_fit and not self._dropped(fit):
            self._fits.append(fit)
        else:
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

    def _dropped(self, fit: float) -> bool:
        """True if `fit` is far below what this game's accepted photos reached (no opinion on the first)."""
        return bool(self._fits) and fit < float(np.median(self._fits[-FIT_WINDOW:])) - MAX_DROP

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
