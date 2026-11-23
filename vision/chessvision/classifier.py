"""Square classifier (pass V3): one crop of a square -> probabilities over the 13 labels.

A MobileNetV3-small backbone (ImageNet weights) looks at each of the 64 crops that
board.grid_crops cuts from the top-down view and outputs a softmax over
EMPTY, WP..WK, BP..BK (labels.py). `SquareClassifier` turns a photo into the
`probs[64][13]` array the decoder consumes, a1 first.

The classifier is allowed to be wrong: the decoder only needs the true move to
explain the photo better than the other legal moves do (see decoder.py).
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision

from .board import find_corners, grid_crops, grid_of_square, warp_for_crops
from .corner_net import MEAN, STD, device
from .labels import N_CLASSES

DEFAULT_WEIGHTS = os.path.join(os.path.dirname(__file__), "..", "weights", "square_net.pt")


class SquareNet(nn.Module):
    def __init__(self, pretrained: bool = True):
        super().__init__()
        weights = torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
        m = torchvision.models.mobilenet_v3_small(weights=weights)
        self.features = m.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(576, 256), nn.Hardswish(), nn.Dropout(0.2),
                                  nn.Linear(256, N_CLASSES))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (N, 3, CROP_H, CROP_W) normalised RGB. Returns logits (N, 13)."""
        return self.head(self.pool(self.features(x)))


def normalise(crops_bgr: torch.Tensor) -> torch.Tensor:
    """(N, H, W, 3) uint8 BGR on any device -> (N, 3, H, W) float, ImageNet-normalised RGB."""
    x = crops_bgr.flip(-1).permute(0, 3, 1, 2).contiguous().float() / 255.0
    mean = torch.tensor(MEAN, device=x.device).view(1, 3, 1, 1)
    std = torch.tensor(STD, device=x.device).view(1, 3, 1, 1)
    return ((x - mean) / std).contiguous()  # MPS backward needs a contiguous input


class SquareClassifier:
    """Load weights once; classify the 64 squares of a photo. Precondition: weights file exists."""

    def __init__(self, weights: Optional[str] = None, dev: Optional[torch.device] = None):
        path = weights or DEFAULT_WEIGHTS
        if not os.path.exists(path):
            raise FileNotFoundError("square_net weights not found: %s (run vision/scripts/train_classifier.py)" % path)
        self.dev = dev or device()
        self.net = SquareNet(pretrained=False).to(self.dev)
        self.net.load_state_dict(torch.load(path, map_location=self.dev))
        self.net.eval()

    @torch.no_grad()
    def grid_probs(self, warped: np.ndarray) -> np.ndarray:
        """(64, 13) probabilities for a board.warp_for_crops image, in grid order (top-left cell first)."""
        crops = torch.from_numpy(grid_crops(warped)).to(self.dev)
        return torch.softmax(self.net(normalise(crops)), dim=1).cpu().numpy()

    def probs(self, image: np.ndarray, orientation: int = 0, corners=None) -> np.ndarray:
        """(64, 13) probabilities, a1 first, for a BGR photo.

        orientation: see board.grid_of_square (0 = White sits at the camera). corners: TL TR BR BL
        if already known, else they are detected. Raises ValueError if no board is found.
        """
        if corners is None:
            corners = find_corners(image)
        if corners is None:
            raise ValueError("no board found in the photo")
        return self.grid_probs(warp_for_crops(image, corners))[grid_of_square(orientation)]


def best_orientation(grid_probs: np.ndarray, board) -> Tuple[int, float]:
    """Orientation under which `board` (64 labels, a1 first) best explains grid-order probabilities.

    Returns (orientation, mean log-likelihood per square). Used when the camera moves between
    photos: the previous position, which differs from the current one by at most a few squares,
    is enough to tell the four orientations apart.
    """
    logp = np.log(np.clip(grid_probs, 1e-6, None))
    board = np.asarray(board)
    scores = [float(logp[grid_of_square(k), board].mean()) for k in range(4)]
    k = int(np.argmax(scores))
    return k, scores[k]
