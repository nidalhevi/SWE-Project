"""Learned board-corner regressor (pass V2, rung 2).

A MobileNetV3-small backbone (ImageNet weights) on a 320x320 view of the photo regresses
the 4 board corners as 8 numbers in [0, 1] (fractions of width/height), in the canonical
geometric order TL, TR, BR, BL (TL = smallest x+y). It replaces the classical Hough/lattice
detector, which reaches ~26% of ChessReD images within 2% corner error; chesscog's RANSAC
detector reaches 34% on the same photos. Orientation (which corner is a1) is not predicted:
it stays a pipeline argument, as VISION_SPEC.md says.
"""
from __future__ import annotations

import os
from typing import Optional

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision

from .board import canonical_order  # noqa: F401  (re-exported; lives in board.py so it needs no torch)

INPUT = 320
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
DEFAULT_WEIGHTS = os.path.join(os.path.dirname(__file__), "..", "weights", "corner_net.pt")


class CornerNet(nn.Module):
    def __init__(self, pretrained: bool = True):
        super().__init__()
        weights = torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
        m = torchvision.models.mobilenet_v3_small(weights=weights)
        self.features = m.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(576, 256), nn.Hardswish(), nn.Dropout(0.2), nn.Linear(256, 8))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.head(self.pool(self.features(x))))


def preprocess(bgr: np.ndarray) -> torch.Tensor:
    """BGR uint8 image (any size) -> normalised (3, INPUT, INPUT) float tensor."""
    rgb = cv2.cvtColor(cv2.resize(bgr, (INPUT, INPUT), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    x = (rgb.astype(np.float32) / 255.0 - MEAN) / STD
    return torch.from_numpy(x.transpose(2, 0, 1).copy())


def device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class CornerPredictor:
    """Load weights once, predict corners in original-image pixels. Precondition: weights file exists."""

    def __init__(self, weights: Optional[str] = None, dev: Optional[torch.device] = None):
        path = weights or DEFAULT_WEIGHTS
        if not os.path.exists(path):
            raise FileNotFoundError("corner_net weights not found: %s (run vision/scripts/train_corners.py)" % path)
        self.dev = dev or device()
        self.net = CornerNet(pretrained=False).to(self.dev)
        self.net.load_state_dict(torch.load(path, map_location=self.dev))
        self.net.eval()

    @torch.no_grad()
    def __call__(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        y = self.net(preprocess(bgr).unsqueeze(0).to(self.dev))[0].cpu().numpy().reshape(4, 2)
        return canonical_order(y * np.array([w, h], dtype=np.float32))
