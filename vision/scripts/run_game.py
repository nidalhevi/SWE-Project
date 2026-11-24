#!/usr/bin/env python3
"""Photos of a game -> PGN.

Give a folder (photos are taken in file-name order) or a list of image files, one photo after
each move. A photo of the starting position at the front is fine: it is read as "no move".
Usage: python3 vision/scripts/run_game.py <folder | photos...> [-o game.pgn] [--json game.json]
           [--ask] [--show] [--truth reference.pgn] [--orientation auto|0|1|2|3] [--start-fen FEN] [--threshold 2.0]
  --json   also write the game as JSON with the position after every ply (chessvision/export.py);
           this is what the GUI reads. Without --ask the script never waits for input.
  --ask    stop at every photo the decoder is not sure about and let you pick or type the move.
           Without it such a photo is decoded together with the next one, unattended.
  --show   with --ask: open the doubtful photo, with the detected grid drawn on it, in Preview.
  --truth  a PGN of the same game written down by hand: reports how many plies agree.
Orientation: 0 White sits at the camera, 1 a-file at the top of the photo, 2 Black at the camera,
3 a-file at the bottom; "auto" works it out per photo from the position reached so far.
iPhone HEIC photos are converted with macOS `sips`. The PGN is checked by our engine and by python-chess.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chessvision.board import draw_grid, find_corners  # noqa: E402
from chessvision.classifier import SquareClassifier  # noqa: E402
from chessvision.correction import make_prompt  # noqa: E402
from chessvision.engine import DEFAULT_BINARY, START_FEN, EngineClient  # noqa: E402
from chessvision.export import game_record, write_game_record  # noqa: E402
from chessvision.photos import decode_photos  # noqa: E402

EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".heic", ".heif")


def photo_paths(args_paths):
    if len(args_paths) == 1 and os.path.isdir(args_paths[0]):
        d = args_paths[0]
        return sorted(os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(EXTS))
    return list(args_paths)


def load_image(path: str):
    """BGR image; HEIC/HEIF goes through `sips` (macOS) because OpenCV cannot read it."""
    if path.lower().endswith((".heic", ".heif")):
        with tempfile.TemporaryDirectory() as tmp:
            jpg = os.path.join(tmp, "photo.jpg")
            done = subprocess.run(["sips", "-s", "format", "jpeg", path, "--out", jpg], capture_output=True)
            image = cv2.imread(jpg) if done.returncode == 0 else None
    else:
        image = cv2.imread(path)
    if image is None:
        raise SystemExit("cannot read image: %s" % path)
    return image


def save_grid(image, path: str, check_dir: str, show: bool) -> None:
    """Write the photo with the detected board grid on it, so a wrong detection is visible at a glance."""
    os.makedirs(check_dir, exist_ok=True)
    corners = find_corners(image)
    marked = draw_grid(image, corners) if corners is not None else image
    out = os.path.join(check_dir, os.path.splitext(os.path.basename(path))[0] + "_grid.jpg")
    cv2.imwrite(out, cv2.resize(marked, (1024, int(1024.0 * marked.shape[0] / marked.shape[1]))))
    print("  photo with detected grid: %s" % out, file=sys.stderr)
    if show and sys.platform == "darwin":
        subprocess.run(["open", out])


def validate(pgn_path: str) -> bool:
    """The written PGN must replay in our engine and, if installed, in python-chess."""
    ok = subprocess.run([DEFAULT_BINARY, "pgn", pgn_path], capture_output=True).returncode == 0
    print("engine replays the PGN: %s" % ("yes" if ok else "NO"), file=sys.stderr)
    try:
        import chess.pgn
    except ImportError:
        return ok
    with open(pgn_path) as f:
        game = chess.pgn.read_game(f)
    fine = game is not None and not game.errors
    print("python-chess replays the PGN: %s" % ("yes" if fine else "NO"), file=sys.stderr)
    return ok and fine


def compare(ucis, truth_path: str) -> None:
    import chess.pgn
    with open(truth_path) as f:
        truth = [m.uci() for m in chess.pgn.read_game(f).mainline_moves()]
    same = sum(a == b for a, b in zip(ucis, truth))
    first = next((i for i, (a, b) in enumerate(zip(ucis, truth)) if a != b), None)
    where = "identical" if ucis == truth else "first difference at ply %d" % ((first if first is not None else min(len(ucis), len(truth))) + 1)
    print("against %s: %d of %d plies agree, %s" % (os.path.basename(truth_path), same, len(truth), where), file=sys.stderr)


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photos", nargs="+")
    ap.add_argument("-o", "--out", help="write the PGN here (default: stdout)")
    ap.add_argument("--json", help="write the game record (moves and positions) here")
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--truth")
    ap.add_argument("--orientation", default="auto")
    ap.add_argument("--start-fen", default=START_FEN)
    ap.add_argument("--threshold", type=float, default=2.0)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    paths = photo_paths(args.photos)
    if not paths:
        raise SystemExit("no photos found")
    orientation = args.orientation if args.orientation == "auto" else int(args.orientation)
    check_dir = (os.path.splitext(args.out)[0] if args.out else "game") + "_check"
    now = {}
    photo_of = []   # photo file name of every ply, in order

    def images():
        for p in paths:
            now["path"], now["image"] = p, load_image(p)
            print("%s" % os.path.basename(p), file=sys.stderr)
            yield now["image"]

    def report(i, plies, held):
        name = os.path.basename(now["path"])
        photo_of.extend([now.pop("held", name)] * (len(plies) - 1) + [name] * min(len(plies), 1))
        if held:
            now["held"] = name
            print("  unreadable, will be decoded with the next photo", file=sys.stderr)
        elif not plies:
            print("  no move", file=sys.stderr)
        for ply in plies:
            note = "  (you chose)" if ply.asked else "  (recovered)" if ply.recovered else ""
            print("  %-8s confidence %6.1f%s" % (ply.san, ply.confidence, note), file=sys.stderr)

    with EngineClient() as engine:
        ask = make_prompt(engine, before=lambda: save_grid(now["image"], now["path"], check_dir, args.show)) if args.ask else None
        res = decode_photos(images(), engine, SquareClassifier(), orientation, args.start_fen, args.threshold, ask, report)
        headers = {} if args.start_fen == START_FEN else {"SetUp": "1", "FEN": args.start_fen}
        if args.json:
            if len(photo_of) + 1 == len(res.plies):   # the last photo was held and read at the end
                photo_of.append(now.get("held"))
            photos = photo_of if len(photo_of) == len(res.plies) else None
            write_game_record(args.json, game_record(res, engine, args.start_fen, photos, headers))
    print("%d plies from %d photos: %d chosen by you, %d recovered from an unreadable photo, final status %s"
          % (len(res.plies), len(paths), sum(p.asked for p in res.plies), sum(p.recovered for p in res.plies), res.status),
          file=sys.stderr)
    pgn = res.pgn(headers)
    if not args.out:
        sys.stdout.write(pgn)
    else:
        with open(args.out, "w") as f:
            f.write(pgn)
        if not validate(args.out):
            return 1
    if args.truth:
        compare(res.ucis, args.truth)
    return 0


if __name__ == "__main__":
    sys.exit(main())
