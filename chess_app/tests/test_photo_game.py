"""Run from the repository root: python -m pytest chess_app/tests"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models import STARTING_FEN  # noqa: E402
from photo_game import game_from_record, load_photo_game  # noqa: E402

AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
RECORD = {
    "version": 1, "start_fen": STARTING_FEN, "final_fen": AFTER_E5, "status": "ongoing",
    "pgn": "1. e4 e5 *\n",
    "plies": [
        {"n": 1, "san": "e4", "uci": "e2e4", "fen_after": AFTER_E4, "photo": "a.jpg",
         "confidence": 11.1, "recovered": False, "corrected": False},
        {"n": 2, "san": "e5", "uci": "e7e5", "fen_after": AFTER_E5, "photo": None,
         "confidence": 3.0, "recovered": True, "corrected": False},
    ],
}


def test_positions_and_labels():
    game = game_from_record(RECORD)
    assert game.position_at(0).fen == STARTING_FEN
    assert game.position_at(1).pieces["e4"] == "P"
    assert game.position_at(2).fen == AFTER_E5
    assert [p.label for p in game.plies] == ["1. e4", "1... e5 ?"]
    assert game.plies[0].move.uci == "e2e4" and game.plies[0].move.san == "e4"
    with pytest.raises(IndexError):
        game.position_at(3)


def test_empty_game():
    record = dict(RECORD, plies=[], final_fen=STARTING_FEN)
    assert game_from_record(record).position_at(0).fen == STARTING_FEN


@pytest.mark.parametrize("damage", [
    lambda r: r.update(version=2),
    lambda r: r.pop("start_fen"),
    lambda r: r.update(final_fen=AFTER_E4),
    lambda r: r["plies"][1].update(n=5),
    lambda r: r["plies"][0].update(uci="e2"),
    lambda r: r["plies"][0].update(fen_after="not a fen"),
    lambda r: r.update(plies=None),
])
def test_malformed_records_are_rejected(damage):
    record = copy.deepcopy(RECORD)
    damage(record)
    with pytest.raises(ValueError):
        game_from_record(record)


def test_load_from_file(tmp_path):
    good = tmp_path / "game.json"
    good.write_text(json.dumps(RECORD))
    assert len(load_photo_game(str(good)).plies) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2")
    with pytest.raises(ValueError):
        load_photo_game(str(bad))
