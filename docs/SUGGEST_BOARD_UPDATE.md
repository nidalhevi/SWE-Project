# Suggest board: detector update

## What changed

The update replaces `2d_recognition/lichess_2d/board_proposals.py`. The GUI,
proposal JSON protocol, process timeout, manual grid confirmation, recognition
profiles, and piece classifier keep their existing interfaces.

The old detector quantized colours into fixed 32-level RGB bins and required
three uninterrupted equal-width colour runs. Resampling creates narrow extra
colour runs; different square colours can also fall into the same bin. These
cases prevented candidates from reaching the old colour-fit scoring stage.

The replacement:

1. Detects continuous RGB changes along many scanlines. Adjacent antialiasing
   transitions are grouped into one boundary rather than separate colour runs.
2. Fits fractional square spacing from several boundaries and aggregates votes.
3. Searches at up to two resolutions (longest edge 960 and 1600 pixels), with
   a source-relative minimum size and a small working-resolution floor.
4. Checks alternating square background colours across the proposed 64 cells.
5. Refits at least five of the seven internal boundaries in each direction
   against the original image. Multiple scanlines reduce piece/text interference.
6. Checks that checkerboard colours do not simply continue beyond the proposed
   eight rows or columns. This rejects internal crops of a larger checkerboard.
7. Combines appearance and boundary support, suppresses duplicate regions, and
   returns up to three proposals by default (one to five through the API).

The detector uses only the existing NumPy and Pillow dependencies. It does not
infer pieces, orientation, turn, castling rights, or move history. Grid-fit
scores remain heuristics, not probabilities. User confirmation remains required.

## Files

| File | Action |
| --- | --- |
| `2d_recognition/lichess_2d/board_proposals.py` | Replace the detector; preserve the transport interface. |
| `2d_recognition/tests_board_proposals/test_board_proposals.py` | Add 18 focused regression tests. |
| `2d_recognition/check_board_proposals.py` | Add a standalone diagnostic command. |
| `docs/SUGGEST_BOARD_UPDATE.md` | Add this document. |

## Install the patch archive

Close the application. From the project root in PowerShell, with the downloaded
ZIP saved in Downloads, run:

```powershell
Expand-Archive -LiteralPath "$HOME\Downloads\chess_suggest_board_patch.zip" -DestinationPath ".\suggest_board_patch" -Force
python .\suggest_board_patch\apply_suggest_board_patch.py --project .
```

The installer verifies that the existing detector matches the supplied project
version (LF and CRLF variants are accepted), saves originals in a timestamped
backup directory, then installs the four payload files. Running it again is safe:
files already matching the patch are left alone. If the detector has other
changes, it reports the mismatch before writing any project files.

To preview installation without writing files:

```powershell
python .\suggest_board_patch\apply_suggest_board_patch.py --project . --dry-run
```

The installer prints a restore command with the exact backup path. Restoration
checks that installed files still match the patch before reverting them; it will
not overwrite subsequent edits.

On Linux/WSL, extract with Python instead of Expand-Archive:

```bash
python3 -m zipfile -e /path/to/chess_suggest_board_patch.zip ./suggest_board_patch
python3 ./suggest_board_patch/apply_suggest_board_patch.py --project .
```

## Verify

From the project root, using the Python environment that runs the GUI:

```powershell
python -m unittest discover -s .\2d_recognition\tests_board_proposals -v
python .\chess_app\main.py
```

The new suite does not require Qt, Stockfish, or the C referee. It uses existing
fixture images already present in the supplied full project. GUI operation still
requires its normal setup.

In the GUI, choose **Import image**, select a screenshot, then **Suggest board**.
Select a suggestion and use **Review suggestion...** to inspect/confirm the grid.
It is not applied automatically.

To inspect one image without launching the GUI:

```powershell
python .\2d_recognition\check_board_proposals.py --image "C:\path\to\screenshot.png"
```

For a screenshot with a known board rectangle, check the coordinates as well:

```powershell
python .\2d_recognition\check_board_proposals.py --image "C:\path\to\screenshot.png" --expect 117 83 568 568
```

Coordinates are left, top, width, height in original-image pixels after EXIF
correction. The command exits with status 1 if the expected board is not among
the suggestions within three pixels; use `--tolerance` to change that tolerance.
Repeat `--expect` for images containing multiple boards. No image is modified.

## Validation performed

- All 18 new regression tests passed, including original fixture geometry,
  large canvases, a smaller board, 517-pixel boards with fractional cell pitch,
  colours sharing the old quantization bin, low contrast, foreground pieces,
  coordinates, JPEG/resampling, highlights/arrows, and multiple boards.
- Negative controls reject uniform/striped/noisy panels, an incomplete board,
  and internal 8x8 windows of 9x9, 10x10 and 12x12 checkerboards.
- The existing five board-proposal/protocol regression tests passed, including
  the real worker process, multiple boards and invalid response handling.
- Running the detector on the two user-supplied GUI screenshots changed results
  from no proposals in either image to the main 954x954 board in one image and
  both visible boards (456x456 and approximately 555x555) in the other.
- Measured detector time on those screenshots was under one second per image
  in the development environment. This is not a performance guarantee.
- A live Qt GUI test was not run in the development environment because PySide6
  was unavailable. The proposal worker process and unchanged response protocol
  were exercised directly.

## Limits

This is a heuristic detector for complete, axis-aligned, approximately square
2D boards. It does not rectify rotated or perspective photographs. Boards must
be at least 128 pixels wide and high in the original image; images larger than
60 million pixels are rejected. Large surrounding images can still shrink a
very small board below usable detail at both bounded search resolutions; crop
the image or select the rectangle manually in that case.

Strong textures, dense overlays, hidden boundaries, very low contrast, unusual
artwork, or checker-like neighbouring UI elements can still confuse it. The
validation set is deliberately limited and is not an accuracy benchmark across
all chess websites. Add failing real screenshots and manually checked rectangles
to your own regression set before changing thresholds further.
