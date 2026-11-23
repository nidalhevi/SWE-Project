# GUI integration: what the engine and vision sides offer `chess_app/`

Written 2026-11-19 after reading branch `nidal/chess-gui` (commit 1195faa). The GUI code is Nidal's; this file is
the contract from the other two sides, plus review notes. Order agreed by the team:

1. A game photographed move by move appears as a position on the board.
2. The GUI analyses the shown position with Stockfish.
3. Playing moves on the board, then playing against our own engine.

## The three programs the GUI talks to

| Program | Started as | Protocol | Client in `chess_app/` |
|---|---|---|---|
| Referee (our C engine) | `build/release/chess batch` | one line in, one line out | `referee_client.py` (exists) |
| Photo reader (Python) | `python vision/scripts/run_game.py …` | runs once, writes files | to write: run with `QProcess`, read the JSON |
| Analysis engine | `stockfish`, or `build/release/chess uci` | UCI | to write: `engine_client.py` |

All three are separate processes. That keeps PyTorch out of the GUI process and lets a crash in one of them be
reported instead of taking the window down, the same reasoning as in `referee_client.py`.

## 1. Photos → position

Command (never waits for input unless `--ask` is given; progress goes to stderr, one photo per line):

```
python vision/scripts/run_game.py <folder> -o game.pgn --json game.json
```

Exit code 0 means both files were written and the PGN replays in the referee. `game.json` (format version 1,
produced by `vision/chessvision/export.py`):

```json
{"version": 1,
 "start_fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
 "final_fen": "R7/5pk1/8/8/8/3p4/1p1r2P1/6K1 w - - 0 52",
 "status": "ongoing",
 "pgn": "[Event \"chessvision\"] ...",
 "plies": [{"n": 1, "san": "b4", "uci": "b2b4",
            "fen_after": "rnbqkbnr/pppppppp/8/8/1P6/8/P1PPPPPP/RNBQKBNR b KQkq b3 0 1",
            "photo": "G000_IMG001.jpg", "confidence": 11.14,
            "recovered": false, "corrected": false}]}
```

- `fen_after` is a full six-field FEN, so `PositionSnapshot(ply["fen_after"])` works directly.
- `recovered`: that photo was unreadable and the move was worked out from the next photo. Worth a marker in the
  move list: these are the plies a person should double-check.
- `corrected`: a person chose the move at the terminal prompt (`--ask`). Always false when the GUI runs it.
- `status` uses the same words as the referee's `status` command.

Suggested GUI steps:
1. "Open photo game…" → folder dialog → run the command with `QProcess` (program and arguments separately, as
   `RefereeClient.start` does). Show stderr lines as progress; about 0.2 s per photo on a Mac.
2. On exit code 0, load `game.json`. Show `final_fen`: `referee.load_position(PositionSnapshot(final_fen))`,
   then `board.set_position(...)` when `completed` arrives.
3. Previous / next buttons walk `plies[i].fen_after` (index −1 = `start_fen`). No referee call is needed to
   display a ply. To continue the game from a ply, load its FEN into the referee.
4. "Open PGN…" for an existing file: `chess pgn <file>` validates it. To show it, replay its moves through
   `play_move`. If that is awkward we add a `chess fens <file>` subcommand that prints one FEN per ply; ask.

Limits to know: the photo reader needs Python with `numpy`, `opencv-python-headless`, `torch`, `torchvision`
and the weights in `vision/weights/`; HEIC photos are converted with macOS `sips` (on Windows/Linux use JPEG
for now); the first photo may be the starting position (read as "no move").

## 2. Stockfish analysis

Stockfish is not bundled (GPL-3; it stays a separate program the user installs: `brew install stockfish`,
`apt install stockfish`, or the Windows download). Let the path be set in the GUI or by a `STOCKFISH`
environment variable.

`engine_client.py` can mirror `referee_client.py`. The UCI conversation:

```
> uci                         < id name ... / uciok
> isready                     < readyok
> position fen <six-field FEN>
> go depth 18                 (or: go movetime 1000)
< info depth 12 score cp 31 nodes 123456 time 80 pv e2e4 e7e5 g1f3
< info depth 13 score mate -4 ...
< bestmove e2e4
> stop                        (when the shown position changes before bestmove arrived)
```

Three things that are easy to get wrong:
- **Score sign.** UCI scores are from the side to move. `AnalysisResult` is from White's side, so negate `cp`
  and `mate` when the analysed position has Black to move.
- **Stale answers.** After `stop`, the old search still sends its `bestmove`. Count requests and drop every
  `info`/`bestmove` that belongs to an older `request_id`; simplest is to wait for that `bestmove` before
  sending the next `position`.
- **Lines to ignore.** `info string …`, `info currmove …`, and `info` lines without `score` or `pv`.

The same client drives our own engine with `build/release/chess uci`. Two differences today: its `info` line
carries a one-move `pv`, and it does not implement `stop` (every `go` must have `depth` or `movetime`, and
answers on its own). Lifting both is on the engine side's list.

## Review notes on the branch (none blocks the merge)

1. `main_window.py` does not use `RefereeClient` yet: a click highlights a square and nothing else. The client
   is exercised only by `check_referee.py`.
2. Imports are flat (`from models import …`), so the app runs only from inside `chess_app/`
   (`cd chess_app && python main.py`). Either keep that and say so in the README, or make it a package.
3. Leftovers to delete: the commented-out "step 1" blocks in `main_window.py` and `board_widget.py`, and the
   unused `starting_pieces()`.
4. Nothing in `chess_app/` runs in CI. `models.py` is pure Python and cheap to unit-test;
   `check_referee.py` needs only QtCore and should run headless on the Linux runner after `make release`.
5. `requirements.txt` is unpinned and the code needs Python ≥ 3.10 (`str | None`); the vision side declares ≥ 3.9.
6. `referee_client.py` is careful work: one request at a time, compound move+FEN requests, a timeout that
   stops the client (a late reply can never be matched to the wrong request), arguments never passed through a
   shell. The 158-byte command cap is below the referee's line buffer.
