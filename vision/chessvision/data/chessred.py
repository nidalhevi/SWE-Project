"""ChessReD reader (Masouris & van Gemert 2023, CC BY-NC-SA 4.0).

Layout under CHESSRED_DIR (default ~/Datasets/ChessReD):
  annotations.json            all 10,800 images: per-square piece labels, splits,
                              and board corners for the ChessReD2K subset (2,078 images)
  images/<game>/G###_IMG###.jpg
Categories are remapped to the engine's labels (src/types.h): ChessReD numbers
pieces pawn,rook,knight,bishop,queen,king per colour and 12 = empty; we use
EMPTY=0, WP..WK=1..6, BP..BK=7..12 with the P N B R Q K order.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional

import numpy as np

from ..labels import square

DEFAULT_DIR = os.environ.get("CHESSRED_DIR", os.path.expanduser("~/Datasets/ChessReD"))

# ChessReD category id -> engine label
_CAT_TO_LABEL = {0: 1, 1: 4, 2: 2, 3: 3, 4: 5, 5: 6, 6: 7, 7: 10, 8: 8, 9: 9, 10: 11, 11: 12, 12: 0}
_CORNER_ORDER = ("top_left", "top_right", "bottom_right", "bottom_left")


@dataclass
class Sample:
    image_id: int
    path: str                      # absolute path to the jpg
    game_id: int
    move_id: int
    labels: List[int]              # 64 engine labels, a1 first
    corners: Optional[np.ndarray]  # (4,2) TL TR BR BL as named from White's side, or None
    width: int
    height: int


class ChessReD:
    """Index over annotations.json. Precondition: the file exists under `root`."""

    def __init__(self, root: str = DEFAULT_DIR):
        self.root = root
        with open(os.path.join(root, "annotations.json")) as f:
            ann = json.load(f)
        self._images = {im["id"]: im for im in ann["images"]}
        self._labels: Dict[int, List[int]] = {}
        for p in ann["annotations"]["pieces"]:
            board = self._labels.setdefault(p["image_id"], [0] * 64)
            board[square(p["chessboard_position"])] = _CAT_TO_LABEL[p["category_id"]]
        self._corners: Dict[int, np.ndarray] = {}
        for c in ann["annotations"]["corners"]:
            self._corners[c["image_id"]] = np.array([c["corners"][k] for k in _CORNER_ORDER], dtype=np.float32)
        self.splits = ann["splits"]

    def ids(self, split: str = "test", subset: str = "chessred2k") -> List[int]:
        """Image ids of a split. subset 'chessred2k' (has corners) or 'full'."""
        s = self.splits[subset][split] if subset == "chessred2k" else self.splits[split]
        return list(s["image_ids"])

    def sample(self, image_id: int) -> Sample:
        im = self._images[image_id]
        return Sample(image_id, os.path.join(self.root, im["path"]), im["game_id"], im["move_id"],
                      self._labels.get(image_id, [0] * 64), self._corners.get(image_id),
                      im["width"], im["height"])

    def samples(self, split: str = "test", subset: str = "chessred2k") -> Iterator[Sample]:
        for i in self.ids(split, subset):
            yield self.sample(i)

    def has_images(self) -> bool:
        return os.path.isdir(os.path.join(self.root, "images"))

    def __len__(self) -> int:
        return len(self._images)
