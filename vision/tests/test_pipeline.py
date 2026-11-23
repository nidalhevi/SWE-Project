import io

import chess
import chess.pgn
import numpy as np

from chessvision.pipeline import decode_game
from chessvision.synthetic import one_hot


def labels(b: chess.Board):
    out = [0] * 64
    for sq, pc in b.piece_map().items():
        out[sq] = pc.piece_type if pc.color == chess.WHITE else pc.piece_type + 6
    return out


def test_decode_game_reproduces_random_game(engine):
    rng = np.random.default_rng(3)
    b = chess.Board()
    ucis, obs = [], []
    for _ in range(60):
        legal = list(b.legal_moves)
        if not legal:
            break
        m = legal[int(rng.integers(len(legal)))]
        b.push(m)
        ucis.append(m.uci())
        obs.append(one_hot(labels(b)))
    res = decode_game(iter(obs), engine)
    assert res.ucis == ucis
    assert res.skipped == 0
    game = chess.pgn.read_game(io.StringIO(res.pgn()))
    assert [m.uci() for m in game.mainline_moves()] == ucis
    assert game.end().board().board_fen() == b.board_fen()


def test_duplicate_photo_is_skipped(engine):
    b = chess.Board()
    b.push_uci("e2e4")
    o = one_hot(labels(b))
    res = decode_game(iter([o, o]), engine)
    assert res.ucis == ["e2e4"] and res.skipped == 1


def test_scholars_mate_result_tag(engine):
    b = chess.Board()
    obs = []
    for u in ("e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"):
        b.push_uci(u)
        obs.append(one_hot(labels(b)))
    res = decode_game(iter(obs), engine)
    assert res.status == "checkmate"
    assert res.pgn().rstrip().endswith("1-0")
    assert "Qxf7#" in res.pgn()


def test_unreadable_photo_is_recovered_with_the_next_one(engine):
    """A photo that explains no move (uniform probabilities, as after a failed board detection)
    is held and decoded together with the following photo instead of being forced into a move."""
    import numpy as np
    from chessvision.labels import placement_from_fen
    from chessvision.pipeline import decode_game
    from chessvision.synthetic import one_hot
    moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]
    engine.position()
    observations = []
    for m in moves:
        engine.move(m)
        observations.append(one_hot(placement_from_fen(engine.fen())))
    observations[2] = np.full((64, 13), 1.0 / 13)          # the photo after g1f3 is garbage
    res = decode_game(observations, engine)
    assert res.ucis == moves
    assert [p.recovered for p in res.plies] == [False, False, True, True, False]


def test_photo_of_a_shifted_grid_is_held_not_played(engine):
    """A confident reading of the wrong board (the grid found one file off) fits no legal move:
    the decoder must hold it rather than play whichever wrong move happens to score best."""
    import numpy as np
    from chessvision.labels import placement_from_fen
    from chessvision.pipeline import GameDecoder
    from chessvision.synthetic import one_hot
    engine.position()
    engine.move("e2e4")
    after = np.array(placement_from_fen(engine.fen())).reshape(8, 8)
    shifted = np.roll(after, 1, axis=1).reshape(64).tolist()   # every piece one file to the right
    engine.position()
    dec = GameDecoder(engine)
    assert dec.feed(one_hot(shifted)) == [] and dec.held is not None
    engine.position()
    engine.move("e2e4")
    engine.move("e7e5")
    two_later = one_hot(placement_from_fen(engine.fen()))
    engine.position()
    assert [p.uci for p in dec.feed(two_later)] == ["e2e4", "e7e5"]
