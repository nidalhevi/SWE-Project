#!/usr/bin/env python3
"""Train the board-corner regressor on ChessReD2K (cache512 copies, see data/chessred.py).

Augmentation (applied to image and corners together): random scale/crop, 90-degree rotations,
horizontal flip, colour jitter. Loss: L1 on normalised corner coordinates in canonical order.
Usage: python3 vision/scripts/train_corners.py [--epochs 40] [--batch 32] [--out vision/weights/corner_net.pt]
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chessvision.corner_net import INPUT, MEAN, STD, CornerNet, canonical_order, device  # noqa: E402
from chessvision.data.chessred import DEFAULT_DIR  # noqa: E402

CACHE = os.path.join(DEFAULT_DIR, "cache512")


def load_split(split: str):
    meta = json.load(open(os.path.join(CACHE, "meta.json")))
    items = [(os.path.join(CACHE, k), np.array(v["corners"], np.float32)) for k, v in meta.items() if v["split"] == split]
    return sorted(items)


def augment(img: np.ndarray, c: np.ndarray, rng: np.random.Generator):
    h, w = img.shape[:2]
    # random crop that keeps all corners inside, with a margin
    lo, hi = c.min(axis=0), c.max(axis=0)
    pad = rng.uniform(0.02, 0.35, size=2) * np.array([w, h])
    x0 = rng.uniform(0, max(1e-3, lo[0] - pad[0])); y0 = rng.uniform(0, max(1e-3, lo[1] - pad[1]))
    x1 = rng.uniform(min(w - 1e-3, hi[0] + pad[0]), w); y1 = rng.uniform(min(h - 1e-3, hi[1] + pad[1]), h)
    img = img[int(y0):int(y1), int(x0):int(x1)]
    c = c - np.array([int(x0), int(y0)], np.float32)
    h, w = img.shape[:2]
    k = int(rng.integers(4))  # 90-degree rotations
    for _ in range(k):
        img = np.ascontiguousarray(np.rot90(img))  # counter-clockwise
        c = np.stack([c[:, 1], w - 1 - c[:, 0]], axis=1); h, w = w, h
    if rng.random() < 0.5:
        img = np.ascontiguousarray(img[:, ::-1]); c = np.stack([w - 1 - c[:, 0], c[:, 1]], axis=1)
    img = img.astype(np.float32)
    img = img * rng.uniform(0.6, 1.4) + rng.uniform(-30, 30)                      # brightness/contrast
    img = img * rng.uniform(0.85, 1.15, size=(1, 1, 3))                            # colour cast
    img = np.clip(img, 0, 255).astype(np.uint8)
    return img, c


def to_tensor(img: np.ndarray, c: np.ndarray):
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(cv2.resize(img, (INPUT, INPUT), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    x = (rgb.astype(np.float32) / 255.0 - MEAN) / STD
    y = canonical_order(c) / np.array([w, h], np.float32)
    return torch.from_numpy(x.transpose(2, 0, 1).copy()), torch.from_numpy(y.reshape(-1))


def batches(items, bs, rng, train):
    idx = rng.permutation(len(items)) if train else np.arange(len(items))
    for i in range(0, len(idx), bs):
        xs, ys = [], []
        for j in idx[i:i + bs]:
            path, c = items[j]
            img = cv2.imread(path)
            if train:
                img, c = augment(img, c, rng)
            x, y = to_tensor(img, c); xs.append(x); ys.append(y)
        yield torch.stack(xs), torch.stack(ys)


def corner_err(pred: torch.Tensor, truth: torch.Tensor) -> torch.Tensor:
    """Mean corner distance / mean side length, in normalised coordinates (both canonical order)."""
    p, t = pred.view(-1, 4, 2), truth.view(-1, 4, 2)
    side = (t - t.roll(1, dims=1)).norm(dim=2).mean(dim=1)
    return (p - t).norm(dim=2).mean(dim=1) / side


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "weights", "corner_net.pt"))
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed); torch.manual_seed(a.seed)
    dev = device(); print("device", dev)
    train, val = load_split("train"), load_split("val")
    print("train %d  val %d" % (len(train), len(val)))
    net = CornerNet(pretrained=True).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * ((len(train) + a.batch - 1) // a.batch))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    best = 1e9
    for ep in range(a.epochs):
        net.train(); t0 = time.time(); tl = 0.0; n = 0
        for x, y in batches(train, a.batch, rng, True):
            x, y = x.to(dev), y.to(dev)
            loss = F.smooth_l1_loss(net(x), y, beta=0.02)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tl += loss.item() * len(x); n += len(x)
        net.eval(); errs = []
        with torch.no_grad():
            for x, y in batches(val, 64, rng, False):
                errs.append(corner_err(net(x.to(dev)).cpu(), y))
        e = torch.cat(errs)
        ok2 = float((e <= 0.02).float().mean()); med = float(e.median())
        print("epoch %2d  loss %.4f  val median err %.2f%%  <=2%%: %.1f%%  (%.0fs)" % (ep + 1, tl / n, 100 * med, 100 * ok2, time.time() - t0), flush=True)
        if med < best:
            best = med; torch.save(net.state_dict(), a.out)
    print("saved best (val median %.2f%%) to %s" % (100 * best, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
