import numpy as np

from chessvision.decoder import confidence, decode_move, move_changes
from chessvision.labels import placement_from_fen, square, LABEL_OF_CHAR
from chessvision.synthetic import observe, one_hot

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"


def test_move_changes_castling_ep_promotion():
    b = placement_from_fen(KIWIPETE)
    ch = move_changes(b, "e1g1")
    assert ch[square("e1")] == 0 and ch[square("g1")] == LABEL_OF_CHAR["K"]
    assert ch[square("h1")] == 0 and ch[square("f1")] == LABEL_OF_CHAR["R"]
    ep = placement_from_fen("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3")
    ch = move_changes(ep, "e5f6")
    assert ch[square("f5")] == 0 and ch[square("f6")] == LABEL_OF_CHAR["P"]
    pr = placement_from_fen("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    assert move_changes(pr, "a7a8q")[square("a8")] == LABEL_OF_CHAR["Q"]
    prb = placement_from_fen("k7/8/8/8/8/8/p6K/8 b - - 0 1")
    assert move_changes(prb, "a2a1n")[square("a1")] == LABEL_OF_CHAR["n"]


def test_decode_exact_observation(engine):
    engine.position(KIWIPETE)
    legal = engine.moves()
    for uci in ("e1g1", "e1c1", "d5e6", "e2a6", "f3h3"):
        assert uci in legal
        engine.position(KIWIPETE)
        engine.move(uci)
        after = placement_from_fen(engine.fen())
        cands = decode_move(KIWIPETE, one_hot(after), legal)
        assert cands[0].uci == uci
        assert confidence(cands) > 5.0


def test_decode_no_move_when_board_unchanged(engine):
    engine.position(KIWIPETE)
    cands = decode_move(KIWIPETE, one_hot(placement_from_fen(KIWIPETE)), engine.moves())
    assert cands[0].uci is None


def test_decode_survives_noise_on_other_squares(engine):
    rng = np.random.default_rng(0)
    engine.position(KIWIPETE)
    legal = engine.moves()
    engine.move("e5g6")
    after = placement_from_fen(engine.fen())
    ok = 0
    for _ in range(50):
        ok += decode_move(KIWIPETE, observe(after, 3, rng), legal)[0].uci == "e5g6"
    assert ok >= 48


# ---- colour first (2026-11-25): an unfamiliar piece set must not confuse the decoder ----
def scrambled_set(board):
    """One-hot probabilities from a classifier that knows colours but calls every piece a queen."""
    from chessvision.synthetic import one_hot
    return one_hot([0 if p == 0 else 5 if p <= 6 else 11 for p in board])


def test_colour_first_with_full_weight_changes_nothing():
    import numpy as np
    from chessvision.decoder import colour_first
    from chessvision.synthetic import observe
    probs = observe([0] * 32 + [1] * 16 + [7] * 16, 5, np.random.default_rng(0))
    assert np.allclose(colour_first(probs, 1.0), probs)


def test_colour_first_keeps_colour_and_softens_type():
    import numpy as np
    from chessvision.decoder import colour_first
    row = np.zeros((64, 13))
    row[:, 5], row[:, 4], row[:, 0] = 0.9, 0.09, 0.01      # "white queen, maybe a white rook"
    out = colour_first(row, 0.5)
    assert out[0, 5] > out[0, 4] > out[0, 7]               # order inside the colour is kept
    assert out[0, 4] / out[0, 5] > row[0, 4] / row[0, 5]   # but the rook is less far behind
    assert np.allclose(colour_first(row, 0.0)[0, 1:7], 0.99)   # weight 0: any white piece is as good


def test_colour_fit_ignores_piece_type_and_label_fit_does_not():
    from chessvision.decoder import colour_fit, label_fit
    from chessvision.labels import placement_from_fen
    board = placement_from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    probs = scrambled_set(board)
    assert colour_fit(probs, board) > -0.001
    assert label_fit(probs, board) < -5.0
    shifted = board[8:] + board[:8]                        # every rank moved down one: colours are wrong
    assert colour_fit(probs, shifted) < -3.0


def test_move_is_found_on_a_set_where_every_piece_reads_as_a_queen():
    from chessvision.decoder import colour_first, decode_move
    from chessvision.labels import placement_from_fen
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    after = placement_from_fen("rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1")
    legal = ["g1f3", "g1h3", "b1c3", "e2e4", "g2g3", "f2f3"]
    cands = decode_move(start, colour_first(scrambled_set(after)), legal)
    assert cands[0].uci == "g1f3"
