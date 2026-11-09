import numpy as np
import cv2

from chessvision.board import corner_error, find_corners_classical, square_crops, warp_topdown
from chessvision.labels import square


def synthetic_scene(truth, seed=0, pieces=True):
    rng = np.random.default_rng(seed)
    img = np.full((900, 1200, 3), 120, np.uint8)
    img = cv2.add(img, rng.integers(0, 25, (900, 1200, 3), dtype=np.uint8))
    bd = np.zeros((640, 640, 3), np.uint8)
    for r in range(8):
        for c in range(8):
            bd[r * 80:(r + 1) * 80, c * 80:(c + 1) * 80] = (230, 220, 200) if (r + c) % 2 == 0 else (60, 90, 120)
    if pieces:
        for _ in range(24):
            r, c = rng.integers(8), rng.integers(8)
            cv2.circle(bd, (int(c * 80 + 40), int(r * 80 + 40)), 30,
                       (20, 20, 20) if rng.random() < .5 else (240, 240, 240), -1)
    src = np.array([[0, 0], [640, 0], [640, 640], [0, 640]], np.float32)
    H = cv2.getPerspectiveTransform(src, truth)
    w = cv2.warpPerspective(bd, H, (1200, 900))
    m = cv2.warpPerspective(np.full((640, 640), 255, np.uint8), H, (1200, 900)) > 0
    img[m] = w[m]
    return img


def test_find_corners_on_synthetic_boards():
    cases = [np.array([[300, 150], [900, 120], [1000, 700], [200, 760]], np.float32),
             np.array([[400, 250], [800, 250], [950, 650], [250, 650]], np.float32),
             np.array([[150, 100], [1050, 150], [1100, 850], [100, 800]], np.float32)]
    for i, t in enumerate(cases):
        pred = find_corners_classical(synthetic_scene(t, i))
        assert pred is not None
        assert corner_error(pred, t) < 0.03


def test_find_corners_returns_none_without_a_board():
    rng = np.random.default_rng(1)
    noise = rng.integers(0, 255, (600, 800, 3), dtype=np.uint8)
    assert find_corners_classical(noise) is None


def test_square_crops_follow_engine_indexing():
    # top-down board where each square is painted with its own index
    img = np.zeros((1024, 1024, 3), np.uint8)
    for sq in range(64):
        f, r = sq & 7, sq >> 3
        col, row = f, 7 - r                      # white at the bottom: rank 1 is the last row
        img[row * 128:(row + 1) * 128, col * 128:(col + 1) * 128] = (sq, sq, sq)
    crops = square_crops(img, white_bottom=True, top_extra=0.0)
    assert len(crops) == 64
    assert int(crops[square("a1")][48, 32, 0]) == square("a1")
    assert int(crops[square("h8")][48, 32, 0]) == square("h8")
    assert int(crops[square("e4")][48, 32, 0]) == square("e4")
    flipped = square_crops(img, white_bottom=False, top_extra=0.0)
    assert int(flipped[square("a1")][48, 32, 0]) == square("h8")


def test_warp_roundtrip():
    truth = np.array([[300, 150], [900, 120], [1000, 700], [200, 760]], np.float32)
    img = synthetic_scene(truth, 5, pieces=False)
    top = warp_topdown(img, truth, size=512)
    assert top.shape == (512, 512, 3)
    # light and dark squares alternate along the top-left row of the warped board
    a, b = top[32, 32].astype(int), top[32, 96].astype(int)
    assert abs(int(a.sum()) - int(b.sum())) > 150
