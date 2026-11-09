# Fuzzing the parsers

Pass 2's definition of done says the FEN and PGN parsers must survive one hour
of fuzzing. The targets are in `fuzz/`; they use libFuzzer, which is built into
clang **but not into Apple's clang**. On the Macs install Homebrew LLVM once:

```bash
brew install llvm
```

(about 2 GB; it does not replace Apple clang, it lives in `/opt/homebrew/opt/llvm`).

## Running

```bash
make fuzz-fen      # builds build/fuzz/fuzz_fen with -fsanitize=fuzzer,address,undefined and runs it for 1 hour
make fuzz-pgn      # same for the PGN parser
```

Both targets take `FUZZ_SECONDS=...` (default 3600) and `LLVM=/path/to/llvm`
(default `/opt/homebrew/opt/llvm`; on Linux use `LLVM=/usr` because clang there
ships libFuzzer). The committed seed corpora are `fuzz/corpus_fen/` and
`fuzz/corpus_pgn/`. Inputs the fuzzer discovers go to `build/fuzz/corpus_*/`
(libFuzzer writes only to the first directory it is given), so they survive
between runs on one machine but are not committed; copy one into `fuzz/` only
if it reproduces a bug.

## What a finding looks like

The fuzzer stops and writes a file `crash-<hash>` (or `timeout-…`, `leak-…`) in the
current directory with the input that broke the parser. Reproduce it with the
same binary:

```bash
./build/fuzz/fuzz_fen crash-abc123
```

Fix the parser, add the input to the matching `tests/test_*.c` as a regression
case, and log one dated line in HURDLES.md with the input.

## What the targets check

- `fuzz_fen`: `fen_parse` never crashes; when it accepts, the position is
  `board_consistent` and `fen_write` → `fen_parse` round-trips.
- `fuzz_pgn`: `pgn_parse` never crashes; when it accepts, the position is
  consistent and `pgn_write` → `pgn_parse` reproduces the same number of plies.

Both run under ASan + UBSan, so any out-of-bounds read or undefined behaviour
on the way is a finding too, even when the parser's answer looks right.
