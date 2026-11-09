# VISION_SPEC — photo → move → PGN (the Python front end)

Companion to SPEC.md. The C engine is the rules oracle; this Python package turns photos of a physical board into
moves and a PGN. Built in passes with checkable done criteria. Decided 2026-11-08: **hybrid recognition + engine decoder**.

## Idea in one paragraph
Recognising a whole board from one photo is unreliable (best published result on real photos: ~15% of boards fully
correct, ~3.4 wrong squares per board). We never need that. We photograph the board after every move, so we always
know the previous position. The engine lists its legal moves (typically 20–40), each move predicts exactly which
squares change, and we pick the legal move whose predicted board agrees best with the classifier's per-square
probabilities. A 64-square, 13-class problem with three expected errors becomes a 30-way choice. The output is a
UCI move; SAN and PGN come from the engine. Castling rights, en passant and side to move are never read from the
photo: the engine tracks them.

## Repository layout
```
SWE-Project/
  vision/                    Python package (own pyproject.toml; Python ≥3.9 (the Macs ship 3.9.6); torch, torchvision, opencv-python, numpy)
    chessvision/
      engine.py              EngineClient: one long-lived `chess batch` process (position/move/undo/moves/san/fen/status)
      decoder.py             decode_move(prev_fen, probs[64][13], legal_moves) -> ranked moves with scores
      board.py               find_corners(image) -> 4 points; warp_topdown(image, corners) -> 8x8 grid of square crops
      classifier.py          SquareClassifier: MobileNetV3-small, 13 classes, returns softmax per square
      pipeline.py            photo sequence -> moves -> PGN; human-correction hook
      data/chessred.py       ChessReD download, split, per-square crop dataset
    scripts/                 train_classifier.py, eval_decoder.py, run_game.py
    tests/                   pytest; the decoder tests need the C binary at ../build/release/chess
  docs/VISION_SPEC.md        this file
```
Python lives in `vision/` only. The C engine is never modified for the vision work except via the engine-side
items listed per pass below. CI gets a second job: `pytest vision/tests` on ubuntu-latest after `make release`.

## Data model
- **Square labels** (13): `EMPTY, WP, WN, WB, WR, WQ, WK, BP, BN, BB, BR, BQ, BK`, same order and values as `Piece` in `src/types.h`.
- **Square indexing**: a1 = 0 … h8 = 63, identical to the engine. The warp step must output crops in this order given the
  known camera side (white at bottom unless `--black-bottom`); orientation is a pipeline argument, never guessed in pass V1–V3.
- **Observation**: `probs: float32[64][13]`, rows sum to 1.
- **Decoder output**: list of `(uci, score)` sorted by score descending, plus `confidence = score[0] - score[1]`.

## The decoder (pass V1, pure Python, no ML)
For the known previous position `P` and each legal move `m` (from `moves`), let `B_m` be the board after `m`
(from `position`, `move m`, `fen`, `undo`, or computed locally from the FEN for speed). Score
`s(m) = Σ_sq log probs[sq][B_m[sq]]` (log-likelihood of the predicted board under the classifier). Only the 2–4
squares that `m` changes differ between candidates, so compute the shared part once and the delta per move.
Add a "no move" hypothesis (board unchanged) so a duplicate or premature photo is detected, not forced into a move.
Promotion: four candidates per promoting pawn, scored on the promotion square. Confidence below a threshold → ask the human.

## Passes

### Pass V1 — engine bridge + decoder on synthetic observations
Build `engine.py`, `decoder.py`, `pipeline.py` (without images), tests.
Synthetic observations: take real games from python-chess (random or PGN), render the true board as one-hot
probabilities, then corrupt them with a noise model (confusion between similar classes, random square flips, a
per-square temperature) at 1, 3, 5 and 8 wrong squares per board. **Done:** `scripts/eval_decoder.py` reports
top-1 move accuracy per noise level over ≥200 games; ≥99% at 3 wrong squares, ≥95% at 5; a full game decodes to a
PGN that python-chess parses and that equals the source game. Engine-side: none (uses `chess batch` as is).

### Pass V2 — board geometry (built 2026-11-08; see status below)
`board.py`: corner detection, homography to a 1024×1024 top-down view, 64 crops with a margin for tall pieces.
Two detectors exist. **Rung 1, classical** (Canny + Hough + RANSAC lattice + checkerboard-contrast window
selection): 26% of ChessReD2K test images within 2% corner error, 47% within 5% (chesscog's published RANSAC
detector reaches 34% board detection on the same photos). **Rung 2, learned** (`corner_net.py`: MobileNetV3-small
regressing the 4 corners, trained on the 1,442 ChessReD2K training images with geometric + colour augmentation,
`scripts/train_corners.py`, ~12 min on a Mac GPU) followed by `refine_by_warp` (Hough lines in the warped frame,
outer lines searched with an inward-biased band). Test split, 306 images, 160-epoch weights (~45 min on the Mac GPU):

| | ≤2% | ≤5% | median |
|---|---|---|---|
| classical (rung 1) | 26.5% | 47.5% | 2.7% of detections, 29% undetected |
| regressor alone | 84.0% | 97.4% | 1.26% |
| regressor + warp refinement (`find_corners`) | **88.6%** | **97.4%** | **1.16%** |

40 ms per image for the net on the Mac GPU plus 17 ms refinement. This meets the original ≤2%-on-85% bar as well as the revised one. `find_corners` uses rung 2 when `vision/weights/corner_net.pt` exists.
**Done bar, revised:** the original "≤2% on ≥85%" is stricter than the downstream needs. A 5% corner error is
0.4 of a square, which the crop margins absorb; the bar is now **≤5% on ≥90% of the test split and median ≤2%**,
with the ≤2% rate reported alongside. Debug overlays: `scripts/eval_corners.py --debug-dir`.

### Pass V3 — square classifier
`classifier.py` + `scripts/train_classifier.py`: MobileNetV3-small fine-tuned on ChessReD crops produced by V2
(train/val/test split as published). Export to ONNX. **Done:** per-square accuracy ≥ 95% on the ChessReD test split
(published end-to-end model: 94.7%); top-1 *move* accuracy ≥ 97% when V1's decoder consumes V3's probabilities on
ChessReD game sequences; inference < 0.5 s per photo on the Mac (CPU or MPS).

### Pass V4 — the product
`run_game.py`: a folder of photos (or the camera) → PGN. Human correction: when confidence is below threshold, show
the warped board, the top-3 candidates and let the user pick or type a move. Final PGN validated by both the engine
(`pgn` subcommand) and python-chess. **Done:** 10 real games photographed by us (phone, our board) decoded with ≤ 2
corrections per game; one 2-minute demo video for the presentation. Engine-side: optionally a `pgn` write path over
`batch` so the Python side never formats PGN itself.

### Not in V1–V4
Full-board recognition from a single photo (only as a baseline comparison in the report), the end-to-end ResNeXt,
any GUI beyond the correction prompt, live video, clocks, move-time inference, piece-colour from board orientation
guessing, a web service.

## Evaluation that goes in the report
Per pass, one table: metric, our number, published baseline (end-to-end: 15.3% boards correct / 94.7% squares;
chesscog: 2.3% / 73.6% on ChessReD). The argument of the project: constraining recognition with the rules engine
turns a weak classifier into a usable system, and the engine's correctness (perft, differential test) is what makes
that argument hold.

## Reuse decisions
| Candidate | Use |
|---|---|
| tmasouris/end-to-end-chess-recognition (MIT) | ChessReD dataset and loader; model only as the baseline row in the report. |
| davidmallasen/LiveChess2FEN (AGPL) | Read the paper for the detect→crop→classify design. No code reuse (licence, stale TF stack). |
| chesscog (MIT) | Reference for RANSAC corner detection if the Hough approach fails; no dependency. |
| Morditux/ChessGuiNG (GPL-2) | Not used: recognises screen diagrams, not photos; 2 months old, one author. |
| GUI | None built. Cute Chess + UCI (pass 3) for the engine; python-chess SVG / lichess URL for visual checks. |

## Open points to settle with the team
- Dataset storage: ChessReD is ~10,800 photos; keep it outside the repo (`~/Datasets/ChessReD`), path via env var `CHESSRED_DIR`.
- Training hardware: Mac MPS is enough for MobileNetV3-small fine-tuning; if not, Colab with the same scripts.
- Which board/pieces we photograph for the V4 demo, and whether to add our own photos to the training set (domain adaptation).
