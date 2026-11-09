from chessvision.labels import placement_from_fen, placement_to_fen, square, square_name, LABEL_OF_CHAR

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_square_indexing_matches_engine():
    assert square("a1") == 0 and square("h1") == 7 and square("a2") == 8 and square("h8") == 63
    assert all(square_name(square(n)) == n for n in ("a1", "e4", "h8", "c7"))


def test_placement_roundtrip():
    b = placement_from_fen(START)
    assert b[square("e1")] == LABEL_OF_CHAR["K"] and b[square("d8")] == LABEL_OF_CHAR["q"]
    assert b[square("e4")] == 0
    assert placement_to_fen(b) == START.split()[0]
    fen2 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1"
    assert placement_to_fen(placement_from_fen(fen2)) == fen2
