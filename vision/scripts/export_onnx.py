#!/usr/bin/env python3
"""Export the square classifier to ONNX and check the export against PyTorch.

The ONNX file takes a batch of normalised crops (N, 3, 128, 96) and returns logits (N, 13); it lets the
classifier run without PyTorch (onnxruntime on any machine). Needs: pip install onnx onnxruntime.
Usage: python3 vision/scripts/export_onnx.py [--weights vision/weights/square_net.pt] [--out vision/weights/square_net.onnx]
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chessvision.board import CROP_H, CROP_W  # noqa: E402
from chessvision.classifier import DEFAULT_WEIGHTS, SquareNet  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=DEFAULT_WEIGHTS)
    ap.add_argument("--out", default=os.path.splitext(DEFAULT_WEIGHTS)[0] + ".onnx")
    args = ap.parse_args()
    net = SquareNet(pretrained=False)
    net.load_state_dict(torch.load(args.weights, map_location="cpu"))
    net.eval()
    x = torch.randn(64, 3, CROP_H, CROP_W)
    torch.onnx.export(net, x, args.out, input_names=["crops"], output_names=["logits"],
                      dynamic_axes={"crops": {0: "n"}, "logits": {0: "n"}}, opset_version=17, dynamo=False)
    import onnxruntime
    session = onnxruntime.InferenceSession(args.out, providers=["CPUExecutionProvider"])
    got = session.run(None, {"crops": x.numpy()})[0]
    with torch.no_grad():
        want = net(x).numpy()
    gap = float(np.abs(got - want).max())
    print("wrote %s (%.1f MB); max logit difference vs PyTorch %.2e" % (args.out, os.path.getsize(args.out) / 1e6, gap))
    return 0 if gap < 1e-3 else 1


if __name__ == "__main__":
    sys.exit(main())
