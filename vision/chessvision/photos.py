"""decode_photos: a sequence of photos -> moves -> PGN (passes V2 + V3 + V1 joined).

For each photo: find the board, warp it, classify the 64 squares, and let the decoder pick the
legal move that best explains the result. The orientation (which side of the photo holds rank 1)
is either given once for the whole game or, with "auto", re-estimated for every photo from the
position the engine currently holds, so the camera may move between photos.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Union

import numpy as np

from .board import find_corners, grid_of_square, warp_for_crops
from .classifier import SquareClassifier, best_orientation
from .decoder import colour_first
from .engine import START_FEN, EngineClient
from .labels import placement_from_fen
from .pipeline import AskFn, GameDecoder, GameResult

Orientation = Union[int, str]  # 0..3 (board.grid_of_square) or "auto"


def observe(image: np.ndarray, classifier: SquareClassifier, orientation: Orientation, fen: str) -> np.ndarray:
    """(64, 13) probabilities, a1 first, for one BGR photo. `fen` is the position before the move.

    Raises ValueError if no board is found.
    """
    corners = find_corners(image)
    if corners is None:
        raise ValueError("no board found in the photo")
    grid = classifier.grid_probs(warp_for_crops(image, corners))
    if orientation == "auto":   # judged colour first, like the moves: see decoder.colour_first
        orientation, _ = best_orientation(colour_first(grid), placement_from_fen(fen))
    return grid[grid_of_square(int(orientation))]


def decode_photos(images: Iterable[np.ndarray], engine: EngineClient, classifier: SquareClassifier,
                  orientation: Orientation = "auto", start_fen: str = START_FEN, threshold: float = 2.0,
                  ask: Optional[AskFn] = None, on_ply: Optional[Callable] = None) -> GameResult:
    """Decode a game from photos taken after each move (a photo of the unchanged board is skipped).

    Precondition: `engine` is open. Postcondition: the engine holds the final position.
    `on_ply(index, plies, held)` is called after each photo, for progress output: the plies it
    produced and whether it was held back as unreadable (see pipeline.GameDecoder).
    """
    engine.position(start_fen)
    dec = GameDecoder(engine, threshold, ask)
    for i, image in enumerate(images):
        if engine.status() != "ongoing":
            break
        plies = dec.feed(observe(image, classifier, orientation, engine.fen()))
        if on_ply is not None:
            on_ply(i, plies, dec.held is not None)
    return dec.finish()
