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
      board.py               find_corners(image) -> 4 points; warp_for_crops + grid_crops -> 64 crops; grid_of_square(orientation)
      xcorners.py            find_corners_pattern: board finder from the checker pattern alone, no training (2026-11-25)
      corner_net.py          CornerNet / CornerPredictor: MobileNetV3-small regressing the 4 corners (pass V2)
      classifier.py          SquareNet / SquareClassifier: MobileNetV3-small, 13 classes, softmax per square; best_orientation
      pipeline.py            GameDecoder: observations -> moves -> PGN; holds an unreadable photo and recovers it; human-correction hook
      correction.py          make_prompt: the human-correction prompt (pass V4)
      photos.py              decode_photos: photos -> board -> crops -> probabilities -> GameDecoder
      data/chessred.py       ChessReD reader: labels, corners, splits
    scripts/                 run_game.py (photos -> PGN), train_classifier.py, eval_classifier.py, build_square_cache.py,
                             export_onnx.py, train_corners.py, eval_corner_net.py, eval_corners.py, eval_decoder.py
    weights/                 corner_net.pt, square_net.pt, square_net.onnx (4.4 MB each)
    tests/                   pytest; the decoder tests need the C binary at ../build/release/chess
  docs/VISION_SPEC.md        this file
```
Python lives in `vision/` only. The C engine is never modified for the vision work except via the engine-side
items listed per pass below. CI gets a second job: `pytest vision/tests` on ubuntu-latest after `make release`.

## Data model
- **Square labels** (13): `EMPTY, WP, WN, WB, WR, WQ, WK, BP, BN, BB, BR, BQ, BK`, same order and values as `Piece` in `src/types.h`.
- **Square indexing**: a1 = 0 … h8 = 63, identical to the engine. The warp step must output crops in this order given the
  known camera side (white at bottom unless `--black-bottom`); orientation is a pipeline argument (0..3, see `board.grid_of_square`) or `auto`, which infers it per photo from the previous position (pass V3).
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

**Changed 2026-11-25: rung 3, a finder that needs no training (`xcorners.py`).** On our own board the regressor
put the grid over about 6x7 squares in every photo checked: it has only ever seen ChessReD's one board. The new
finder uses what every board has, the 49 points where four squares meet: a ChESS ring response (Bennett &
Lasenby 2014) at two radii, its local maxima, a perspective lattice through them by RANSAC, then the 7x7 window of
lattice points that is the board's interior. `find_corners` now asks both finders and returns the quadrilateral
with the higher checker contrast (`_checker_score`), the pattern finder winning a tie. Test split, 306 images
(`scripts/eval_corners.py --method auto|pattern|learned`):

| | ≤2% | ≤5% | median | time per photo |
|---|---|---|---|---|
| regressor + warp refinement (`learned`) | 88.6% | 97.4% | 1.16% | 0.09 s |
| pattern finder alone (`pattern`) | 98.7% | 98.7% | 0.37% | 0.38 s |
| both, more board-like wins (`auto`, the default) | **100%** | **100%** | **0.38%** | 0.43 s |

Validation split, 330 images: pattern finder alone 100% within 2% (worst 1.4%), regressor 86.4% / 98.8%. The two
fail on different photos: the pattern finder's 3 test misses are photos where it finds no convincing board
(contrast below 0.35, so it answers None and the regressor's answer is used), plus one where it is 12% off with
a contrast of 0.84 against the regressor's 0.86. That last photo is why the rule compares the two contrasts
instead of trusting the pattern finder whenever it answers; the validation split could not tell those two rules
apart (both 100%), so "100% on test" rests on that one photo and should be read as "99.7% to 100%". Cost: the
whole pipeline went from about 70 ms to about 360 ms per photo on the Mac GPU, still inside the 500 ms bar.

### Pass V3 — square classifier (built 2026-11-18; see status below)
`classifier.py` + `scripts/train_classifier.py`: MobileNetV3-small fine-tuned on ChessReD crops produced by V2
(train/val/test split as published). Export to ONNX. **Done:** per-square accuracy ≥ 95% on the ChessReD test split
(published end-to-end model: 94.7%); top-1 *move* accuracy ≥ 97% when V1's decoder consumes V3's probabilities on
ChessReD game sequences; inference < 0.5 s per photo on the Mac (CPU or MPS).

**Status.** Data: the ChessReD2K subset (the 2,078 photos that have corner annotations; 14 / 3 / 3 games for
train / val / test, split by game, so no test position was seen in training). `build_square_cache.py` warps each
photo once to a 640x640 top-down view with the camera at the bottom edge (`warp_for_crops`); one crop is a square
plus the square behind it and a quarter square each side (96x128 px). Train warps use the annotated corners, two
jittered copies (0.8% and 1.5% of the board side) and our detector's corners; val and test use only the detector's,
which is what the classifier meets in use. 10 epochs, ~30 min on the Mac GPU. Results on the test split
(`scripts/eval_classifier.py`, 306 photos, 3 games):

| | ours | bar / published |
|---|---|---|
| squares correct | **98.99%** | ≥ 95% (end-to-end model 94.7%) |
| boards fully correct | 85.9% | (end-to-end model 15.3%) |
| wrong squares per board | mean 0.65, median 0 | (end-to-end model 3.4) |
| moves correct, previous position given | **98.04%** | ≥ 97% |
| whole games decoded exactly, unaided | **3 of 3** (303 plies) | not in the bar |
| time per photo, whole pipeline, Mac GPU | **70 ms** | < 500 ms |

Validation games: 99.24% squares, 99.39% moves, 2 of 3 games exact (the third is wrong only on its last two plies,
where the last photo is unreadable and there is no next photo to recover it with).

Three things found on the way, all in the code now:
- **Every misread move is a board-detection failure**, not a classifier failure: the 6 wrong plies on the test split
  have 9 to 35 wrong squares each (the grid lands a square off), against a median of 0.
- **Such a photo is detectable**: even its best move explains it badly (mean log-likelihood per square below -0.6,
  against about -0.1 for a good photo). `GameDecoder` holds a photo that is unreadable (`MIN_FIT = -0.4`) or
  ambiguous (gap to the second-best move below the threshold) and decodes it together with the next photo as two
  plies. Before this, one bad photo derailed the rest of the game (92/102 and 86/102 plies on two test games);
  after, all three are exact. `MIN_FIT` was set after looking at those test failures, so the validation games are
  the unbiased check. Limit: two unreadable photos in a row are not recovered (it would need a three-ply search).
- **Orientation is no longer a required argument.** ChessReD photos are taken from all four sides. Given the
  position before the move, the orientation that best explains the photo is the right one on 100% of the 636
  val + test photos (`best_orientation`), so `run_game.py` defaults to `--orientation auto`.

Use: `python3 vision/scripts/run_game.py <folder of photos> -o game.pgn` (one photo per move, file-name order;
103 photos take 23 s). ONNX: `vision/weights/square_net.onnx`, logits equal to PyTorch's within 1e-5.
Not done in V3: the full 10,800-photo ChessReD (only ChessReD2K is on disk and has corners), and photos of our own
board, which is pass V4 and the real test of whether this transfers beyond the dataset's one board and piece set.

### Pass V4 — the product
`run_game.py`: a folder of photos (or the camera) → PGN. Human correction: when confidence is below threshold, show
the warped board, the top-3 candidates and let the user pick or type a move. Final PGN validated by both the engine
(`pgn` subcommand) and python-chess. **Done:** 10 real games photographed by us (phone, our board) decoded with ≤ 2
corrections per game; one 2-minute demo video for the presentation. Engine-side: optionally a `pgn` write path over
`batch` so the Python side never formats PGN itself.

**Status (2026-11-18): tooling built, our own photos not taken yet.** `run_game.py` has `--ask` (the correction
prompt in `correction.py`: pick a candidate, type a move in SAN or UCI, `s` to decide with the next photo, `n` for
no move), `--show` (opens the doubtful photo with the detected grid drawn on it), `--truth ref.pgn` (plies agreeing
with a hand-written record), HEIC input through macOS `sips`, and a final check that both our engine (`chess pgn`)
and python-chess replay the PGN. Tried on ChessReD test game 0 with scripted answers: 102 of 102 plies, 1 correction.
How to photograph and where to put the files: `docs/PHOTO_GUIDE.md`. The done bar (10 own games, ≤ 2 corrections
each, demo video) is open until those photos exist. Known weak spot to watch on our board: when detection fails,
the grid usually lands exactly one square inside the real one (the refinement locks onto an inner line).

**Status (2026-11-25): first own game photographed, and it did not decode.** 59 photos (phone, 4000x1848, our
board and pieces, one photo per move, a 58-ply game). The result through the GUI was a wrong game with every
move marked unclear. Two separate causes, both now fixed in the code:
1. *Board not found* (see the 2026-11-25 note under pass V2). With `xcorners.py` the board is found in all 59.
2. *Piece types misread on our set.* With the right corners, empty / white / black is read correctly on 97.6% of
   squares, but the exact piece on only 43.6% of occupied squares (rooks 31 of 219, knights 52 of 199). Legal
   moves almost always differ in which squares are empty, white or black, so this does not stop the decoder,
   but the old "unreadable photo" rule (label fit above -0.4, a level only ChessReD's set reaches) flagged
   every photo. Three changes in `decoder.py` / `pipeline.py`:
   - moves are ranked *colour first* (`colour_first`): P(label) = P(colour) x P(type | colour)^0.5
     (`TYPE_WEIGHT`). With the true game as reference, the true move is ranked first on 59 of 59 photos at
     every weight from 0 to 1; 0.5 gave the widest smallest margin (2.0, against 0.9 at weight 1), and on
     ChessReD it costs under 10% of the margin.
   - a photo is unreadable if its colours do not fit (`colour_fit` below `MIN_FIT = -0.35`), or
   - if its exact labels fit much worse than in the photos already accepted in the same game (`label_fit`
     more than `MAX_DROP = 0.3` below their median). The second test is what catches a grid one file off
     while both back ranks are full, which colours alone cannot see.

Checked on the 3 validation and 3 test games of ChessReD plus our game, each photo also with its grid shifted
one square in each of four directions (3,475 readings):

| | old rule | new rule |
|---|---|---|
| ChessReD, good photos wrongly held | 2 of 627 | 2 of 627 |
| ChessReD, misplaced grids accepted | 0 of 2,553 | 1 of 2,553 (the right move was still played) |
| own game, good photos wrongly held | **59 of 59** | **0 of 59** |
| own game, misplaced grids accepted | 0 of 236 | 1 of 236 (a wrong move) |

End to end from the original photos (`photos.decode_photos`): all 6 ChessReD games exact (630 plies, 1 photo
held; with the old finder's corners 11 photos were held), and our game gives 58 plies, none held, 22 s for the
59 photos. **Limits.** (a) Our game has no hand-written record yet: "right" means legal throughout, the same
under three scorings, and the final position equal to the last photo square by square. (b) The thresholds
were chosen on the same readings the table reports, so the table is a fit, not a test; the next own games are
the test. (c) The very first photo of a game has no earlier photo to compare with: a grid one file off at the
starting position can pass (that is the 1 of 236). (d) One game, one board, one room. The done bar (10 own
games, ≤ 2 corrections each) is still open, and "import a position from a single photo" needs the piece types,
which means fine-tuning the classifier on our set: a decoded and checked game gives 3,776 labelled crops.

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

**Changed 2026-11-19:** a GUI is being built after all (`chess_app/`, PySide6). The vision side stays a command-line
program; the GUI runs `run_game.py --json game.json` as a subprocess and reads the result: the PGN plus the
position after every ply (`chessvision/export.py`, format in docs/GUI_INTEGRATION.md). Checked on ChessReD game 0:
102 plies, final FEN equal to the referee's after replaying the moves.

## Open points to settle with the team
- Dataset storage: ChessReD is ~10,800 photos; keep it outside the repo (`~/Datasets/ChessReD`), path via env var `CHESSRED_DIR`.
- Training hardware: Mac MPS is enough for MobileNetV3-small fine-tuning; if not, Colab with the same scripts.
- Which board/pieces we photograph for the V4 demo, and whether to add our own photos to the training set (domain adaptation).
