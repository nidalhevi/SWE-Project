"""Pass V3: crop geometry, orientation handling and the classifier's plumbing (no trained weights needed)."""
import numpy as np
import pytest

from chessvision.board import (CELL, CROP_H, CROP_W, canonical_order, grid_crops, grid_of_square,
                               orientation_from_named, warp_for_crops)
from chessvision.labels import placement_from_fen, square

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_grid_of_square_is_a_permutation_for_every_orientation():
    for k in range(4):
        assert sorted(grid_of_square(k).tolist()) == list(range(64))


def test_grid_of_square_corners():
    # orientation 0: White at the camera, so a1 is the bottom-left cell and h8 the top-right one
    assert grid_of_square(0)[square("a1")] == 7 * 8 + 0
    assert grid_of_square(0)[square("h8")] == 0 * 8 + 7
    # orientation 2: Black at the camera, the board is turned half way round
    assert grid_of_square(2)[square("a1")] == 0 * 8 + 7
    # orientation 1: a quarter turn clockwise puts a1 top-left
    assert grid_of_square(1)[square("a1")] == 0


def test_orientation_from_named_recovers_each_rotation():
    canon = np.array([[100, 100], [900, 120], [880, 900], [90, 880]], dtype=np.float32)
    for k in range(4):
        named = np.roll(canon, -k, axis=0)  # the a8 corner is the k-th corner clockwise from the image's top-left
        assert orientation_from_named(canon, named) == k


def test_warp_and_crops_shapes_and_content():
    board = np.zeros((800, 800, 3), dtype=np.uint8)
    board[100:700, 100:700] = 255                       # a white "board" on black
    corners = np.array([[100, 100], [699, 100], [699, 699], [100, 699]], dtype=np.float32)
    warped = warp_for_crops(board, corners[[2, 0, 3, 1]])  # corner order must not matter
    assert warped.shape == (10 * CELL, 10 * CELL, 3)
    assert warped[5 * CELL, 5 * CELL].min() > 200 and warped[CELL // 2, CELL // 2].max() < 50
    crops = grid_crops(warped)
    assert crops.shape == (64, CROP_H, CROP_W, 3)
    assert crops[0][:CELL // 2].max() < 50               # the top row's crops start in the border above the board
    assert crops[27][CELL + CELL // 2, CROP_W // 2].min() > 200


def test_canonical_order_starts_top_left_and_goes_clockwise():
    c = canonical_order(np.array([[9, 9], [0, 9], [9, 0], [0, 0]], dtype=np.float32))
    assert c.tolist() == [[0, 0], [9, 0], [9, 9], [0, 9]]


def test_best_orientation_and_square_net():
    torch = pytest.importorskip("torch")
    from chessvision.classifier import SquareNet, best_orientation, normalise
    board = np.array(placement_from_fen(START))
    for k in range(4):
        grid = np.full((64, 13), 0.01)
        grid[grid_of_square(k), board] = 0.88            # a confident, correct reading seen from side k
        assert best_orientation(grid, board)[0] == k
    net = SquareNet(pretrained=False).eval()
    x = normalise(torch.zeros(4, CROP_H, CROP_W, 3, dtype=torch.uint8))
    assert x.shape == (4, 3, CROP_H, CROP_W)
    with torch.no_grad():
        assert net(x).shape == (4, 13)
