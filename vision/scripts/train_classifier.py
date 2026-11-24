#!/usr/bin/env python3
"""Train the square classifier on ChessReD2K warps (build them first with build_square_cache.py).

One training item is a whole warped board: it is augmented as a unit (small shift and scale, which
imitates corner error; colour; mirror) and cut into its 64 crops, so a batch of B boards is 64*B crops.
Validation uses the warps made from our own detected corners, which is what the classifier sees in use.
Usage: python3 vision/scripts/train_classifier.py [--epochs 30] [--batch 16] [--out vision/weights/square_net.pt]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chessvision.board import grid_crops, grid_of_square  # noqa: E402
from chessvision.classifier import DEFAULT_WEIGHTS, SquareNet, normalise  # noqa: E402
from chessvision.corner_net import device  # noqa: E402
from chessvision.data.chessred import DEFAULT_DIR, ChessReD  # noqa: E402

CACHE = os.path.join(DEFAULT_DIR, "cache_squares")


def load_rows(split: str, tags):
    """Index rows of a split with their JPEG bytes and grid-order labels attached."""
    ds = ChessReD()
    rows = [r for r in json.load(open(os.path.join(CACHE, "index.json"))) if r["split"] == split and r["tag"] in tags]
    for r in rows:
        with open(os.path.join(CACHE, r["file"]), "rb") as f:
            r["jpeg"] = np.frombuffer(f.read(), dtype=np.uint8)
        grid = np.zeros(64, dtype=np.int64)
        grid[grid_of_square(r["orientation"])] = ds.sample(r["image_id"]).labels
        r["grid_labels"] = grid
    return rows


def augment(img: np.ndarray, labels: np.ndarray, rng: np.random.Generator):
    """Shift/scale the board a little, change its colours, maybe mirror it left-right."""
    size = img.shape[0]
    s = rng.uniform(0.97, 1.03)
    tx, ty = rng.uniform(-5, 5, size=2)
    M = np.array([[s, 0, (1 - s) * size / 2 + tx], [0, s, (1 - s) * size / 2 + ty]], dtype=np.float32)
    img = cv2.warpAffine(img, M, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    if rng.random() < 0.5:  # a mirrored board is still a board seen from the same side
        img = np.ascontiguousarray(img[:, ::-1])
        labels = np.ascontiguousarray(labels.reshape(8, 8)[:, ::-1]).reshape(64)
    if rng.random() < 0.2:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.5, 1.5))
    out = img.astype(np.float32) * rng.uniform(0.6, 1.4) + rng.uniform(-30, 30)
    out = out * rng.uniform(0.85, 1.15, size=(1, 1, 3))
    return np.clip(out, 0, 255).astype(np.uint8), labels


class Boards(Dataset):
    def __init__(self, rows, train: bool):
        self.rows, self.train = rows, train

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        img = cv2.imdecode(r["jpeg"], cv2.IMREAD_COLOR)
        labels = r["grid_labels"]
        if self.train:
            img, labels = augment(img, labels, np.random.default_rng())
        return torch.from_numpy(grid_crops(img)), torch.from_numpy(labels)


def collate(batch):
    return torch.cat([b[0] for b in batch]), torch.cat([b[1] for b in batch])


@torch.no_grad()
def evaluate(net, loader, dev):
    """(square accuracy, share of boards with every square right, mean wrong squares per board)."""
    net.eval()
    wrong = []
    for x, y in loader:
        pred = net(normalise(x.to(dev))).argmax(1).cpu()
        wrong.extend((pred != y).view(-1, 64).sum(1).tolist())
    wrong = np.array(wrong)
    return 1 - wrong.sum() / (64 * len(wrong)), float((wrong == 0).mean()), float(wrong.mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=16, help="boards per batch (64 crops each)")
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=DEFAULT_WEIGHTS)
    args = ap.parse_args()
    dev = device()
    train = DataLoader(Boards(load_rows("train", ("pred", "gt", "j1", "j2")), True), batch_size=args.batch, shuffle=True,
                       num_workers=args.workers, collate_fn=collate, drop_last=True, persistent_workers=True)
    val = DataLoader(Boards(load_rows("val", ("pred",)), False), batch_size=args.batch, num_workers=2, collate_fn=collate)
    net = SquareNet().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * len(train), pct_start=0.15)
    best = 0.0
    for epoch in range(args.epochs):
        net.train()
        t0, total, n = time.time(), 0.0, 0
        for x, y in train:
            loss = F.cross_entropy(net(normalise(x.to(dev))), y.to(dev), label_smoothing=0.05)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            total, n = total + loss.item(), n + 1
        acc, exact, wrong = evaluate(net, val, dev)
        print("epoch %2d  loss %.4f  val squares %.4f  boards %.3f  wrong/board %.2f  (%.0fs)"
              % (epoch + 1, total / n, acc, exact, wrong, time.time() - t0), flush=True)
        if acc > best:
            best = acc
            torch.save(net.state_dict(), args.out)
    print("best val square accuracy %.4f -> %s" % (best, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
