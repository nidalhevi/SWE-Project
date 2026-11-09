import pytest

from chessvision.engine import EngineError, START_FEN


def test_start_position(engine):
    engine.position()
    assert len(engine.moves()) == 20
    assert engine.san("e2e4") == "e4"
    assert engine.san("g1f3") == "Nf3"
    assert engine.status() == "ongoing"
    assert engine.fen() == START_FEN


def test_move_undo_and_errors(engine):
    engine.position()
    engine.move("e2e4")
    assert engine.fen().split()[1] == "b"
    with pytest.raises(EngineError):
        engine.move("e2e4")  # not black's piece
    engine.undo()
    assert engine.fen() == START_FEN
    with pytest.raises(EngineError):
        engine.position("garbage")
    engine.position()  # still alive afterwards
    assert len(engine.moves()) == 20


def test_game_over_status(engine):
    engine.position("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert engine.status() == "checkmate"
    assert engine.moves() == []
