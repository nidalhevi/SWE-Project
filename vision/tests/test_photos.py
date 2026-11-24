"""Pass V3 end to end on real photos. Skips unless the dataset, both weight files and the engine are present."""
import os

import pytest

from chessvision.data.chessred import DEFAULT_DIR, ChessReD


@pytest.fixture(scope="module")
def game_photos():
    pytest.importorskip("torch")
    from chessvision.classifier import DEFAULT_WEIGHTS
    if not (os.path.exists(os.path.join(DEFAULT_DIR, "annotations.json")) and os.path.exists(DEFAULT_WEIGHTS)):
        pytest.skip("ChessReD or square_net weights not available")
    ds = ChessReD()
    if not ds.has_images():
        pytest.skip("ChessReD images not available")
    samples = sorted((s for s in ds.samples("test") if s.game_id == 0), key=lambda s: s.move_id)
    return samples[:9]  # the start position and the first 8 plies of a test game


def test_first_plies_of_a_test_game_decode_to_the_annotated_positions(engine, game_photos):
    import cv2
    from chessvision.classifier import SquareClassifier
    from chessvision.labels import placement_from_fen
    from chessvision.photos import decode_photos
    res = decode_photos((cv2.imread(s.path) for s in game_photos), engine, SquareClassifier())
    assert res.skipped == 1 and len(res.plies) == 8      # the first photo is the untouched start position
    assert placement_from_fen(res.final_fen) == game_photos[-1].labels
    assert res.pgn().count(".") >= 4
