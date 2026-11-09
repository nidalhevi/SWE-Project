import os

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from chessvision.corner_net import DEFAULT_WEIGHTS, CornerNet, canonical_order, preprocess  # noqa: E402


def test_canonical_order_is_tl_tr_br_bl():
    c = np.array([[900, 120], [200, 760], [1000, 700], [300, 150]], np.float32)
    o = canonical_order(c)
    assert o.tolist() == [[300, 150], [900, 120], [1000, 700], [200, 760]]


def test_forward_shape_and_range():
    net = CornerNet(pretrained=False).eval()
    x = preprocess(np.zeros((640, 480, 3), np.uint8)).unsqueeze(0)
    with torch.no_grad():
        y = net(x)
    assert y.shape == (1, 8) and float(y.min()) >= 0 and float(y.max()) <= 1


@pytest.mark.skipif(not os.path.exists(DEFAULT_WEIGHTS), reason="corner_net weights not trained")
def test_predictor_on_synthetic_board():
    from chessvision.corner_net import CornerPredictor
    from tests.test_board import synthetic_scene
    truth = np.array([[300, 150], [900, 120], [1000, 700], [200, 760]], np.float32)
    c = CornerPredictor()(synthetic_scene(truth, 0))
    assert c.shape == (4, 2)
