# SPEC — chess-c

A chess program in C. Built in passes; each pass has a definition of done that a command can check.
All open decisions were resolved in session 0 (2026-11-07); see §Decisions at the end.

## Pass 1 — rules engine (this pass)

### Goal
A library + CLI that represents a chess position, generates exactly the legal moves, applies and undoes them, and proves it with perft.

### Repository layout
```
SWE-Project/            local clone at ~/Projects/SWE-Project, remote github.com/nidalhevi/SWE-Project
  Makefile              targets: debug, release, test, clean
  .github/workflows/ci.yml   runs `make test` on ubuntu-latest with clang (pass 1)
  .claude/settings.json Stop hook (`make test` must pass) + deny rule on tests/perft_suite.epd
  src/
    types.h             Piece, Color, Square, Move, Position
    board.c/.h          init, piece_at, set/clear, consistency check
    fen.c/.h            fen_parse(), fen_write()
    movegen.c/.h        gen_pseudo_legal(), gen_legal(), is_square_attacked()
    make.c/.h           make_move(), unmake_move(), undo stack
    perft.c/.h          perft(), perft_divide()
    cli.c               main(): subcommands below
  tests/
    perft_suite.epd     reference positions and node counts (do not edit)
    test_fen.c          FEN round-trips and ≥20 invalid-input cases
    test_movegen.c      hand-picked positions: castling, en passant, promotion, pins, checks
  tools/
    diff_vs_python_chess.py   differential test; needs `pip install chess`
  docs/
  HURDLES.md            append-only log of bugs and surprises
```

### Data model
- `Color`: `WHITE = 0, BLACK = 1`.
- `Piece` (int): `EMPTY = 0, WP, WN, WB, WR, WQ, WK, BP, BN, BB, BR, BQ, BK` (1..12). `piece_color(p)`, `piece_type(p)` helpers.
- `Square` (int 0..63): `a1 = 0, b1 = 1, … h1 = 7, a2 = 8, … h8 = 63`. `file = sq & 7`, `rank = sq >> 3`. `NO_SQUARE = -1`.
- `Move` (struct): `from`, `to`, `promo` (EMPTY or piece type), `flags` (NORMAL, CAPTURE, DOUBLE_PUSH, EN_PASSANT, CASTLE_K, CASTLE_Q, PROMOTION). A plain struct in pass 1; the packed 16-bit encoding is a pass-3 optimisation, measured before and after.
- `Position`: `board[64]`, `side_to_move`, `castling` (4 bits: K Q k q), `ep_square`, `halfmove_clock`, `fullmove_number`, `king_sq[2]`, and an undo stack of `{move, captured_piece, castling, ep_square, halfmove_clock}` with a fixed capacity of 1024 plies.
- `MoveList`: fixed array of 256 moves + count. No heap.

### Public API (src/*.h)
```c
int  fen_parse(Position *pos, const char *fen);        // 0 ok, nonzero = invalid (never crashes)
void fen_write(const Position *pos, char *buf, size_t n);
int  gen_legal(const Position *pos, MoveList *out);     // returns count
bool is_square_attacked(const Position *pos, Square sq, Color by);
bool in_check(const Position *pos);
void make_move(Position *pos, Move m);
void unmake_move(Position *pos);                        // pops the undo stack
uint64_t perft(Position *pos, int depth);
void move_to_uci(Move m, char buf[6]);                  // e2e4, e7e8q
int  move_from_uci(const Position *pos, const char *s, Move *out);
bool board_consistent(const Position *pos);             // used by assert() in make/unmake
```

### CLI (`./build/debug/chess <subcommand>`; release build at `./build/release/chess`)
- `perft <depth> [fen]`: prints the node count. Without fen, the start position.
- `divide <depth> [fen]`: one line per root move, `e2e4 12345`, then a final line `total <n>`. (Exact contract used by `tools/diff_vs_python_chess.py --divide`.)
- `moves [fen]`: legal moves in UCI notation, sorted, one per line. (Exact contract used by `tools/diff_vs_python_chess.py`.)
- `perft-suite <file> <maxdepth>`: runs every line of the EPD file up to `maxdepth`, prints PASS/FAIL per line, exit code 1 on any failure.
- Any invalid FEN or argument: message on stderr, exit code 2, no crash.

### Rules that must be exact
Castling (rights, not through/into/out of check, squares empty), en passant (including the capture that would expose the king along the rank), promotion to N/B/R/Q, fifty-move counter, fullmove number, king never captured (a position where the side not to move is in check is invalid input to `gen_legal`).

En-passant square: a double pawn push **always** sets `ep_square` to the skipped square, and `fen_write` **always** writes it. (python-chess writes it only when a capture is possible; the differential test compares move lists, not FEN strings, so this only matters for our own round-trip tests, which must use FENs we wrote ourselves or compare parsed positions rather than strings.)

### Definition of done (pass 1)
1. `make debug` and `make release` build with zero warnings on macOS/Apple clang and Linux/clang (CI).
2. `make test` passes: unit tests + `perft-suite tests/perft_suite.epd 4` under ASan+UBSan.
3. `perft-suite … 5` passes in the release build (slow is fine; this is the correctness bar).
4. `tools/diff_vs_python_chess.py --games 500` reports zero disagreements. `make test` runs it with `--games 50` when `python3 -c "import chess"` succeeds and prints a clear SKIP otherwise; the 500-game run is done by hand before pass 1 is declared done.
5. `./build/debug/chess perft 1 "garbage"` and 20 other malformed inputs (tests/test_fen.c) exit 2 without crashing.
6. HURDLES.md has at least one entry per bug the suite, the sanitizers or the diff tool caught, plus one entry for every setup hurdle (e.g. installing python-chess).
7. CI is green on `main`.

### Not in this pass
Bitboards, magic tables, Zobrist hashing, repetition/insufficient-material detection, SAN, PGN, terminal UI, search, evaluation, UCI, threads, SIMD, any GUI, any dependency.

## Pass 2 — the whole game (after pass 1 is done)
Zobrist hashing + threefold repetition; fifty-move and insufficient-material draws; checkmate/stalemate detection; SAN parse/print; PGN import/export; terminal two-player play with undo; libFuzzer harness for `fen_parse` and the PGN reader (needs Homebrew LLVM on the Macs; Apple clang ships no libFuzzer — install it when pass 2 starts and log the hurdle). Definition of done: 10,000 random games vs python-chess with identical legal-move sets at every ply and identical game-over verdicts; parsers survive one hour of fuzzing.

## Pass 3 — engine and performance
Negamax + alpha-beta, iterative deepening, quiescence, MVV-LVA; material + piece-square-table evaluation in centipawns; UCI protocol; cutechess-cli self-play for an Elo estimate. Performance ladder on perft, one measured rung at a time: bitboards for attack detection → lookup tables (leapers) → magic tables (sliders) → copy-make vs make/unmake → root-split perft with pthreads. Each rung: nodes/s before and after, recorded in docs/perf.md. Timings on the Macs with `hyperfine`; hardware counters on the course Linux VM with `perf stat`.

**Status (2026-11-18): built.** `src/eval.c` (material + piece-square tables), `src/search.c` (negamax
alpha-beta, iterative deepening, quiescence, MVV-LVA, check extension, draws by repetition / fifty moves /
material seen inside the tree), `src/uci.c` (`chess uci`), `chess search <depth> [fen]`, and `go` in `chess play`
so a human can play the engine in the terminal. Ladder: `src/bitboard.c` (rungs 1 to 3), `chess perft-copy`
(rung 4), `chess perft-mt <threads> <depth>` (rung 5). Numbers and what each rung taught us: docs/perf.md
(one thread 2.8x to 3.4x, all cores 26x; roughly 1750 to 1950 against strength-limited Stockfish).
Deviations: matches ran with `tools/match.py` (python-chess over UCI) because cutechess-cli is not packaged for
Homebrew; the engine speaks plain UCI, so cutechess-cli or Cute Chess can drive it unchanged. `perf stat` on the
Linux VM is still to do. UCI `stop` is not supported (the search runs in the command thread and always has a limit).

## Out of scope for the course deadline
NNUE, opening books, endgame tablebases, GUI, photo input (the Python starter kit covers that path separately).

**Changed 2026-11-19:** the GUI is now in scope. `chess_app/` (PySide6, branch `nidal/chess-gui`) shows the board
and talks to this engine through `chess batch`; next it loads a game decoded from photos and analyses the position
with Stockfish over UCI. The C side stays GUI-free: the GUI is a separate process. Contract: docs/GUI_INTEGRATION.md.

## Decisions (session 0, 2026-11-07)
| # | Decision |
|---|---|
| Q1 | Code at `~/Projects/SWE-Project` on each Mac (outside the vault); remote `github.com/nidalhevi/SWE-Project`, currently empty. First commit = this kit. |
| Q2 | Apple clang for passes 1 and 3; `brew install llvm` when pass 2's fuzzing starts. |
| Q3 | `Move` is a plain struct. Packed `uint16_t` is a measured pass-3 optimisation. |
| Q4 | `ep_square` always set after a double push and always written by `fen_write`. |
| Q5 | **Policy (a): Claude writes every module.** After each module Claude summarises it in 5 lines with the one non-obvious decision, then explains it as if we had to reimplement it and quizzes us with 3 questions. We rewrite nothing but must be able to explain every line. |
| Q6 | Pass 1 done Fri 2026-11-13; pass 2 Fri 2026-11-20; pass 3 + freeze Mon 2026-11-23; report 2026-11-24 → 27. |
| Q7 | GitHub Actions from pass 1: `make test` on ubuntu-latest with clang. |
| Q8 | `.claude/settings.json`: Stop hook running `make test`, deny rule on `tests/perft_suite.epd`. Enabled as soon as the Makefile exists. |
| Q9 | Claude never commits. Each of us commits after reading the diff. |
| Q10 | Three people, one branch per person (own Claude session, worktree if needed), `main` protected, merge after `make test` is green on every Mac and in CI. |
| Q11 | Pass 3 measurements: `hyperfine` on the Macs, `perf stat` on the course Linux VM. |
| Q12 | Everything in English. |
| — | python-chess availability on the Macs is unconfirmed: session 1 checks it, installs with `pip install chess` if missing, and records the hurdle. |
| Q13–15 | Deferred to pass 2/3; defaults stand. |
