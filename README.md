# SWE-Project: chess from photos

Goal: photograph a chess game, one photo after each move. The program works out which moves were played in a physical board,
writes the game as a standard PGN file, and shows it on a board where it can be analysed.

It has three parts, each a separate program:

| Part | Folder | Language | What it does |
|---|---|---|---|
| **Referee and engine** | `src/` | C17, no libraries | Knows the rules of chess exactly, and can also choose moves |
| **Vision** | `vision/` | Python | Finds the board in a photo, reads the pieces, asks the referee which legal move fits |
| **GUI** | `chess_app/` | Python (PySide6) | Shows the board; will load photo games and run analysis |

```
 photos ──► vision ──────────► game.pgn + game.json ──► GUI board ──► Stockfish analysis
              │  "which legal moves exist here?"            │
              └──────────────►  referee (C)  ◄──────────────┘
```

**The idea that makes it work.** Reading 64 squares from a photo perfectly is hard. But between two photos
exactly one legal move was played, and the referee can list them all (about 30). So the vision side never has
to read the board perfectly: it only has to tell which of those 30 candidates fits the photo best.

## Status (2026-11-23)

| Piece | State | Evidence |
|---|---|---|
| Rules: moves, FEN, check/mate/draws, SAN, PGN | Done | perft suite; 50 games / 18,392 positions identical to python-chess on every test run |
| Terminal play, batch protocol | Done | `chess play`, `chess batch` |
| Engine: search, evaluation, UCI | Done | scores 54% against Stockfish limited to 1900 (40 games, 0.1 s/move) |
| Performance ladder | Done | perft 47 → 133 million nodes/s on one thread, 1,211 on 15 threads; see `docs/perf.md` |
| Vision: board detection, square classifier, move decoder | Done | on unseen ChessReD games: 99.0% of squares, 98.0% of moves, 3 of 3 games exact |
| Photos → PGN tool, correction prompt | Tooling done | tested on ChessReD; **not yet tested on our own board and photos** |
| GUI: board display, referee client | Started | board draws; playing moves on it is not wired yet |
| GUI: photo game on the board | Done | "Open photo game…" reads a folder of photos and steps through the moves; checked on a 103-photo ChessReD game |
| GUI: Stockfish analysis | Next | contract in `docs/GUI_INTEGRATION.md` |

Known gaps: `perf stat` measurements on Linux, HEIC photos outside macOS, no CI for `chess_app/`.

## Quick start

Needs `clang` (or gcc) and `make`. Python 3.10+ for the GUI, 3.9+ for vision.

```bash
make release          # builds build/release/chess
make test             # debug build with sanitizers + every test; must be green before a commit
```

**Play in the terminal.** Type moves like `e4` or `e2e4`; `go` lets the engine move; `help` lists commands.

```bash
./build/release/chess play
```

**Use the engine from a chess program** (Cute Chess, Arena…): add it as a UCI engine with this command.

```bash
./build/release/chess uci
```

**Photos → PGN.** A folder of photos in file-name order, one per move. The section
"Photo games" below explains the folder, the file names and where to get test photos.

```bash
pip install numpy opencv-python-headless torch torchvision chess
python3 vision/scripts/run_game.py path/to/photos -o game.pgn --json game.json
```

Add `--ask` to be asked whenever a photo is doubtful.

**GUI.**

```bash
pip install -r chess_app/requirements.txt
cd chess_app && python main.py
```

"Open photo game…" asks for a folder of photos and shows the game on the board, with a move list to step
through. It runs the photo reader as a separate program. If the vision packages (torch, OpenCV) are installed
in a different Python than PySide6, say which one:

```bash
cd chess_app && CHESSVISION_PYTHON=/usr/bin/python3 python main.py
```

Check that the GUI can talk to the referee (12 checks):

```bash
cd chess_app && python check_referee.py --bin ../build/release/chess
```

## Photo games: folder, file names, how to open one

**One folder per game.** Put all the photos of one game, and only that game, in one folder. Keep it outside
the repository (photos are large and must not be committed), for example:

```
~/Datasets/OwnGames/game01/IMG_4301.jpg
~/Datasets/OwnGames/game01/IMG_4302.jpg
~/Datasets/OwnGames/game01/...
```

**The order is the file-name order, nothing else.** The program sorts the names alphabetically and reads them
as move 1, move 2, … It does not look at the date of the photo.

- A phone's own names (`IMG_4301`, `IMG_4302`, …) are already in order: copy the files without renaming them.
- If you rename by hand, pad the numbers: `photo002.jpg`, not `photo2.jpg` (`photo10` sorts before `photo2`).
- Do not mix two games or two cameras in one folder.
- Formats: `.jpg`, `.jpeg`, `.png`, `.bmp`; `.heic` / `.heif` on macOS only.

**What the photos must show.** One photo after every move, whole board and all four corners visible, taken
from 40 to 60 degrees above the table. A photo of the starting position before move 1 is fine, and so is a
second photo of the same position (both are read as "no move"). Do not skip a move.
Details: `docs/PHOTO_GUIDE.md`.

**Open it in the GUI.** Start the GUI (see Quick start), click **Open photo game…** and choose the game's
folder (the folder itself, not a photo). The status line shows progress, about 0.2 s per photo. When it
finishes, the board shows the last position; click a move in the list or use ◀ ▶ to step through the game.
A `?` after a move means that photo was unclear and deserves a second look. **Save PGN…** writes the game to
a file; nothing is saved otherwise, and the photos are never copied or changed.

**Or from the terminal:**

```bash
python3 vision/scripts/run_game.py ~/Datasets/OwnGames/game01 -o game01.pgn --json game01.json
```

### No photos of your own? Use the ChessReD sample

To try everything without photographing a game, download the public dataset we trained and tested on:
**Chess Recognition Dataset (ChessReD)**, Athanasios Masouris, TU Delft, at
<https://data.4tu.nl/datasets/99b5c721-280b-450b-b058-b2900b69a90f/2>. Licence: CC BY-NC-SA 4.0
(non-commercial; credit the author).

| File on that page | Size | MD5 | Needed for |
|---|---|---|---|
| `chessred2k.zip` | 4.7 GB | `4e55e299b6b2973e0d8659bd241c7975` | the photos: 20 games, 2,078 photos |
| `annotations.json` | 22 MB | `d34bca5ad46ec7a8df96a1d3c36784f3` | only for the vision tests and for training |
| `chessred.zip` | 24.6 GB | | not needed (the full 100 games) |

Unzip `chessred2k.zip` into `~/Datasets/ChessReD/` and put `annotations.json` next to it, so that you have:

```
~/Datasets/ChessReD/annotations.json
~/Datasets/ChessReD/images/0/G000_IMG000.jpg     game 0, starting position
~/Datasets/ChessReD/images/0/G000_IMG001.jpg     game 0, after move 1
~/Datasets/ChessReD/images/33/...                one folder per game
```

Each folder under `images/` is one game, already named in move order. In the GUI, open
`~/Datasets/ChessReD/images/0` (103 photos, 102 moves, about 20 seconds). Games 0, 33 and 76 were never used
for training, so they are the fair ones to demo. The vision tests that need the photos look in this same
folder and are skipped when it is missing.

## All commands of the `chess` binary

| Command | Purpose |
|---|---|
| `play [fen]` | Two players, or you against the engine, in the terminal |
| `batch` | Line protocol for other programs: `position`, `move`, `undo`, `moves`, `status`, `san`, `fen` |
| `uci` | Standard engine protocol for chess GUIs |
| `pgn <file>` | Check that a PGN file replays legally |
| `moves [fen]`, `status [fen]` | Legal moves / game state of a position |
| `search <depth> [fen]` | Best move and score at a fixed depth |
| `perft`, `divide`, `perft-suite`, `perft-copy`, `perft-mt` | Move-generation counts: the correctness test and the speed benchmark |

## Vocabulary

- **FEN**: one line of text describing one position (where the pieces are, whose turn, castling rights…).
- **PGN**: a text file describing a whole game as a list of moves.
- **SAN**: how people write a move (`Nf3`, `exd5`, `O-O`). **UCI move**: how programs write it (`g1f3`).
- **UCI protocol**: the text conversation between a chess GUI and an engine.
- **Perft**: count every position reachable in N moves. The counts are known, so one wrong rule shows up as a wrong number.
- **Referee**: our name for the C program when it is used only to answer "is this legal, what is legal, is the game over".

## Repository map

```
src/            C engine: board, movegen, make, fen, san, pgn, game, play (terminal + batch),
                eval, search, uci, bitboard, perft, cli
tests/          C unit tests and the perft reference suite (perft_suite.epd is never edited)
fuzz/           libFuzzer harnesses for the FEN and PGN parsers
tools/          differential test against python-chess, match runner, perft benchmark, magic generator
vision/         chessvision package, scripts (train / evaluate / run_game), tests, trained weights
chess_app/      the GUI
docs/           VISION_SPEC, GUI_INTEGRATION, PHOTO_GUIDE, perf, FUZZING
SPEC.md         what each pass of the engine must do, and what is done
HURDLES.md      dated log of every bug and surprise, append only
CLAUDE.md       conventions for working in this repo with Claude Code
```

## How we work

- `SPEC.md` and `docs/VISION_SPEC.md` say what is in scope. Build only what the current pass asks for.
- `make test` green before every commit. CI runs it again on Linux.
- Every bug a test, sanitizer or fuzzer finds gets one dated line in `HURDLES.md`.
- Code may be drafted with Claude Code, but a person reads the diff and makes the commit, and we must be able
  to explain every line.

## Data and third-party software

- Training and evaluation photos: the ChessReD dataset (Masouris and van Gemert), CC BY-NC-SA 4.0. Not stored
  in this repo; see "No photos of your own?" above for the download.
- Stockfish is used as an opponent for measuring strength and as the GUI's analysis engine. It is a separate
  GPL-3 program that you install yourself; it is not bundled.
- Libraries: python-chess (tests only), NumPy, OpenCV, PyTorch, PySide6.
