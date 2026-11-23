import json

import chess
import numpy as np
import pytest

from chessvision.export import game_record, write_game_record
from chessvision.pipeline import decode_game
from chessvision.synthetic import one_hot
from .test_pipeline import labels


def random_game(seed, plies):
    rng = np.random.default_rng(seed)
    b = chess.Board()
    obs, fens = [], []
    for _ in range(plies):
        legal = list(b.legal_moves)
        if not legal:
            break
        b.push(legal[int(rng.integers(len(legal)))])
        obs.append(one_hot(labels(b)))
        fens.append(b.board_fen())
    return obs, fens, b


def test_record_has_the_position_after_every_ply(engine):
    obs, fens, b = random_game(5, 40)
    res = decode_game(iter(obs), engine)
    rec = game_record(res, engine)
    assert rec["version"] == 1 and rec["status"] == res.status
    assert [p["n"] for p in rec["plies"]] == list(range(1, len(fens) + 1))
    assert [p["fen_after"].split()[0] for p in rec["plies"]] == fens
    assert rec["final_fen"] == rec["plies"][-1]["fen_after"] == engine.fen()
    replay = chess.Board(rec["start_fen"])
    for p in rec["plies"]:
        assert replay.san(chess.Move.from_uci(p["uci"])) == p["san"]
        replay.push_uci(p["uci"])
    assert replay.board_fen() == b.board_fen()


def test_record_of_an_empty_game(engine):
    res = decode_game(iter([]), engine)
    rec = game_record(res, engine)
    assert rec["plies"] == [] and rec["final_fen"] == rec["start_fen"]


def test_photos_are_attached_and_counted(engine):
    obs, _, _ = random_game(7, 6)
    res = decode_game(iter(obs), engine)
    names = ["p%d.jpg" % i for i in range(len(res.plies))]
    assert [p["photo"] for p in game_record(res, engine, photos=names)["plies"]] == names
    with pytest.raises(ValueError):
        game_record(res, engine, photos=names[:-1])


def test_record_is_json(engine, tmp_path):
    obs, _, _ = random_game(9, 10)
    rec = game_record(decode_game(iter(obs), engine), engine)
    path = tmp_path / "game.json"
    write_game_record(str(path), rec)
    assert json.loads(path.read_text()) == rec
