"""The pattern board finder (xcorners.py) on drawn boards; real photos are covered by scripts/eval_corners.py."""
import cv2
import numpy as np
import pytest

from chessvision import xcorners
from chessvision.board import corner_error, find_corners

from .test_board import synthetic_scene

CASES = [np.array([[300, 150], [900, 120], [1000, 700], [200, 760]], np.float32),
         np.array([[400, 250], [800, 250], [950, 650], [250, 650]], np.float32),
         np.array([[150, 100], [1050, 150], [1100, 850], [100, 800]], np.float32)]


def test_response_peaks_where_four_squares_meet_and_not_on_an_edge():
    img = np.zeros((120, 120), np.uint8)
    img[:60, :60] = img[60:, 60:] = 255                    # one square corner at (60, 60)
    resp = xcorners.xcorner_response(img)
    y, x = np.unravel_index(resp.argmax(), resp.shape)
    assert abs(y - 59.5) <= 1 and abs(x - 59.5) <= 1       # the corner lies between pixels 59 and 60
    edge = np.zeros((120, 120), np.uint8)
    edge[:, 60:] = 255                                     # a plain edge has no such point
    assert xcorners.xcorner_response(edge).max() < 0.05 * resp.max()


def test_finds_drawn_boards_with_pieces_on_them():
    for seed, truth in enumerate(CASES):
        found = xcorners.find_corners_pattern(synthetic_scene(truth, seed))
        assert found is not None
        assert corner_error(found, truth) < 0.02


def test_same_photo_gives_the_same_corners():
    scene = synthetic_scene(CASES[0], 0)
    assert np.array_equal(xcorners.find_corners_pattern(scene), xcorners.find_corners_pattern(scene))


def test_no_board_gives_none():
    rng = np.random.default_rng(1)
    assert xcorners.find_corners_pattern(rng.integers(0, 255, (600, 800, 3), dtype=np.uint8)) is None
    assert xcorners.find_corners_pattern(np.full((600, 800, 3), 128, np.uint8)) is None


def test_accepts_a_grayscale_image():
    gray = cv2.cvtColor(synthetic_scene(CASES[1], 1), cv2.COLOR_BGR2GRAY)
    assert corner_error(xcorners.find_corners_pattern(gray), CASES[1]) < 0.02


def lattice_block():
    """A 7x7 block of nodes under a plain scaling homography (50 px per step, origin at 100, 100)."""
    lat = np.array([[x, y] for y in range(7) for x in range(7)], float)
    H = np.array([[50.0, 0, 100], [0, 50.0, 100], [0, 0, 1]])
    return H, lat


def image_points(H, lat):
    return cv2.perspectiveTransform(lat.reshape(-1, 1, 2).astype(np.float32), H.astype(np.float32)).reshape(-1, 2)


def test_coarsen_undoes_a_half_square_step():
    H, lat = lattice_block()
    fine = lat.copy()
    fine[:, 0] *= 2                                        # every node sits on an even x line
    half = H @ np.diag([0.5, 1.0, 1.0])                    # the same image points with a half-size x step
    H2, lat2 = xcorners.coarsen(half, fine)
    assert sorted(map(tuple, lat2)) == sorted(map(tuple, lat))
    assert np.allclose(image_points(H2, lat2), image_points(half, fine), atol=1e-3)


def test_reduce_basis_straightens_slanted_axes():
    H, lat = lattice_block()
    shear = np.array([[1.0, 1.0], [0.0, 1.0]])             # x' = x + y: the same nodes, slanted axes
    slanted = lat @ shear.T
    change = np.eye(3)
    change[:2, :2] = np.linalg.inv(shear)
    H2, lat2 = xcorners.reduce_basis(H @ change, slanted)
    assert xcorners._block_count(slanted)[0] < 49 and xcorners._block_count(lat2)[0] == 49
    before = sorted(map(tuple, np.round(image_points(H @ change, slanted), 2)))
    after = sorted(map(tuple, np.round(image_points(H2, lat2), 2)))
    assert before == after                                 # the nodes did not move in the image


def test_find_corners_dispatch():
    scene = synthetic_scene(CASES[2], 2)
    assert corner_error(find_corners(scene, "pattern"), CASES[2]) < 0.02
    assert corner_error(find_corners(scene), CASES[2]) < 0.02      # auto: with or without the corner net
    with pytest.raises(ValueError):
        find_corners(scene, "magic")
