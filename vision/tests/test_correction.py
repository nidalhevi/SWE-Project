"""Pass V4: the correction prompt. No photos or weights needed: answers are fed as strings."""
import io

import numpy as np

from chessvision.correction import make_prompt, resolve
from chessvision.labels import placement_from_fen
from chessvision.pipeline import HOLD, NO_MOVE, GameDecoder
from chessvision.synthetic import one_hot

LEGAL = ["e2e4", "g1f3", "b1c3"]
SANS = ["e4", "Nf3", "Nc3"]


def test_resolve_understands_every_kind_of_answer():
    shown = ["g1f3", None, "e2e4"]
    assert resolve("", shown, LEGAL, SANS) == "g1f3"          # Enter takes the first candidate
    assert resolve("3", shown, LEGAL, SANS) == "e2e4"
    assert resolve("2", shown, LEGAL, SANS) == NO_MOVE
    assert resolve("s", shown, LEGAL, SANS) == HOLD
    assert resolve("n", shown, LEGAL, SANS) == NO_MOVE
    assert resolve("Nc3", shown, LEGAL, SANS) == "b1c3"       # SAN
    assert resolve("b1c3", shown, LEGAL, SANS) == "b1c3"      # UCI
    assert resolve("Nf3+", shown, LEGAL, SANS) == "g1f3"      # check marks are ignored
    assert resolve("9", shown, LEGAL, SANS) is None
    assert resolve("Qh5", shown, LEGAL, SANS) is None         # not legal here: asked again


def test_prompt_lets_the_human_fix_an_unreadable_photo(engine):
    engine.position()
    answers = iter(["Qh5", "e4"])                              # an illegal try first, then the real move
    out = io.StringIO()
    dec = GameDecoder(engine, ask=make_prompt(engine, read=lambda _: next(answers), out=out))
    plies = dec.feed(np.full((64, 13), 1.0 / 13))             # a photo that says nothing
    assert [p.uci for p in plies] == ["e2e4"] and plies[0].asked and plies[0].san == "e4"
    assert "not a legal move" in out.getvalue()


def test_prompt_is_not_shown_for_a_clear_photo(engine):
    engine.position()
    engine.move("d2d4")
    clear = one_hot(placement_from_fen(engine.fen()))
    engine.position()

    def never(_):
        raise AssertionError("asked about a clear photo")
    dec = GameDecoder(engine, ask=make_prompt(engine, read=never, out=io.StringIO()))
    assert [p.uci for p in dec.feed(clear)] == ["d2d4"]


def test_answering_s_postpones_to_the_next_photo(engine):
    engine.position()
    engine.move("e2e4")
    engine.move("c7c5")
    later = one_hot(placement_from_fen(engine.fen()))
    engine.position()
    dec = GameDecoder(engine, ask=make_prompt(engine, read=lambda _: "s", out=io.StringIO()))
    assert dec.feed(np.full((64, 13), 1.0 / 13)) == [] and dec.held is not None
    assert [p.uci for p in dec.feed(later)] == ["e2e4", "c7c5"]
