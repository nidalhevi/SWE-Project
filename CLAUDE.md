# chess-c

Chess rules engine in C for the Bocconi Software Engineering (20875) course project.
The spec is SPEC.md; read it before any task. Build only what the current pass in SPEC.md asks for.

## Commands
- Build (debug, sanitizers on): `make debug`
- Build (release): `make release`
- All tests: `make test` (runs under the debug build; must be green before any commit)
- Perft suite only: `./build/debug/chess perft-suite tests/perft_suite.epd 4`
- Differential test vs python-chess: `python3 tools/diff_vs_python_chess.py --games 200`
- Play the engine: `./build/release/chess play` then `go`; UCI for a GUI: `./build/release/chess uci`
- Perft timings: `tools/bench_perft.sh` (needs hyperfine); matches: `/usr/bin/python3 tools/match.py --help`
- Photos → PGN (+ JSON for the GUI): `/usr/bin/python3 vision/scripts/run_game.py <folder> -o game.pgn --json game.json`
- GUI (PySide6, flat imports, run from its folder): `cd chess_app && python main.py`; referee check: `python check_referee.py --bin ../build/release/chess`; tests: `.venv/bin/python -m pytest chess_app/tests`; the photo reader runs under `CHESSVISION_PYTHON` (here `/usr/bin/python3`)
- Fuzz the FEN parser: see docs/FUZZING.md (Apple clang has no libFuzzer; use Homebrew LLVM)

## Conventions
- C17, `-Wall -Wextra -Werror`, no external libraries, no dynamic allocation in the hot path.
- Square indexing is a1 = 0 … h8 = 63 (file fastest), same as python-chess; never introduce a second convention.
- Representation is the mailbox `int board[64]` from SPEC.md plus, since pass 3, the bitboards in `Position` (`bb[]`, `occ`). Both are updated only through `board_set` / `board_clear`; never write `pos->board[]` directly.
- Functions under ~40 lines; every public function has a comment stating its precondition and postcondition.
- `assert()` encodes invariants (board consistency), never input validation. Invalid input returns an error code and the program must not crash.
- Integer centipawns only; no floating point anywhere in the engine.

## Working rules (this is a learning project)
- We must be able to explain every line in a 10-minute presentation. After writing a module, summarise in 5 lines what it does and the one non-obvious decision in it.
- Do not implement anything listed under "Not in this pass" in SPEC.md, even if it would be easy.
- Record every bug found by a test, the fuzzer or a sanitizer as one dated line in HURDLES.md (what broke, how it was found, the FEN that reproduces it). Append only.
- Do not commit; leave commits to us. Do not touch tests/perft_suite.epd.

## Gotchas
- Primary machine is an Apple Silicon Mac (clang, AArch64); CI runs on Linux x86_64. Code must build on both.
- `1ULL << 64` is UB; guard shifts. `-INT_MAX` is the lowest score, never `INT_MIN`.
