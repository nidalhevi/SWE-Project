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
