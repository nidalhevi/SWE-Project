import os

import pytest

from chessvision.data.chessred import DEFAULT_DIR, ChessReD
from chessvision.labels import placement_to_fen

pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(DEFAULT_DIR, "annotations.json")),
                                reason="ChessReD annotations not downloaded")


def test_annotations_index():
    ds = ChessReD()
    assert len(ds) == 10800
    for split, n in (("train", 1442), ("val", 330), ("test", 306)):
        ids = ds.ids(split, "chessred2k")
        assert len(ids) == n
        assert all(ds.sample(i).corners is not None for i in ids)
    assert placement_to_fen(ds.sample(0).labels) == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    c = ds.sample(0).corners
    assert c.shape == (4, 2) and (c >= 0).all() and (c <= 3072).all()
