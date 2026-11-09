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
