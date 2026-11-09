# First prompts

Policy (a) from session 0: Claude writes every module; we review, make it explain, and must be able to defend every line.

## Session 0 — interview (10 minutes) — DONE 2026-11-07
```
Read CLAUDE.md and SPEC.md. This is a three-person course project and we're new to C.
Interview me until every [Q] item in SPEC.md and docs/QUESTIONNAIRE.md is resolved and you have
no remaining questions about pass 1. Multiple-choice where possible, one topic at a time.
Then rewrite SPEC.md with the answers and remove the [Q] markers. Don't write any code yet.
```
`/clear` afterwards.

## Session 1 — scaffolding + FEN (Claude writes, we read)
```
Read CLAUDE.md and SPEC.md. Implement pass 1 scaffolding only:
Makefile (debug/release/test/clean), .github/workflows/ci.yml, src/types.h, src/board.c, src/fen.c with
fen_parse/fen_write, src/cli.c with the four subcommands, tests/test_fen.c with at least 20 malformed FENs,
and tools/diff_vs_python_chess.py wired to `./build/debug/chess moves`. Leave src/movegen.c, src/make.c
and src/perft.c as headers plus stub .c files that fail loudly ("not implemented"); they are session 2.
First check whether `python3 -c "import chess"` works; if not, install it and log the hurdle in HURDLES.md.
Be ambitious on the FEN edge cases. Run `make test` under the sanitizers and show me the output.
When done, summarise each file in 5 lines and the one non-obvious decision in it.
```
Then enable `.claude/settings.json` (Stop hook + deny rule) and `/clear`.

## Session 2 — movegen, make/unmake, perft (Claude writes, we learn)
```
Read CLAUDE.md and SPEC.md. Implement src/movegen.c, src/make.c and src/perft.c per §Data model and
§Rules that must be exact, plus tests/test_movegen.c with hand-picked positions for castling, en passant
(including the rank-exposure case), promotion, pins and checks. Run `make test`, then
`./build/debug/chess perft-suite tests/perft_suite.epd 4` and `python3 tools/diff_vs_python_chess.py --games 100`.
For every failure, use `divide` to localise the root move and fix it; add the position to tests/test_movegen.c
and one dated line to HURDLES.md. Show me the final outputs.
When done, summarise each file in 5 lines and the one non-obvious decision in it.
```
Then `/clear` and run the learning loop for each module (one module per prompt):
```
Explain src/make.c to me as if I had to reimplement it tomorrow without you: the data flow, the one
invariant that make/unmake must preserve, and the two most likely bugs. Then quiz me with 3 questions.
```

## Session 3 — independent review (fresh session, someone who didn't drive sessions 1–2)
```
Read CLAUDE.md and SPEC.md. Use a subagent to review src/movegen.c and src/make.c against SPEC.md
§Rules that must be exact and §Data model. Run `./build/release/chess perft-suite tests/perft_suite.epd 5`
and `python3 tools/diff_vs_python_chess.py --games 500`. Report gaps that affect correctness only, skip
style. Don't fix the code; tell me where to look.
```

## Session V1 — photo path: engine bridge + decoder (Python, no images yet)
```
Read CLAUDE.md, SPEC.md and docs/VISION_SPEC.md. Implement pass V1 only, inside vision/: pyproject.toml,
chessvision/engine.py (EngineClient over `./build/release/chess batch`), chessvision/decoder.py, chessvision/pipeline.py
(sequence of observations -> moves -> PGN via the engine's `san`), scripts/eval_decoder.py with the synthetic noise
model, and pytest tests. Do not write any image code and do not touch src/ except to report a needed engine change.
Run `make release`, then `pytest vision/tests` and `python3 vision/scripts/eval_decoder.py --games 200`, and show me
the accuracy table per noise level. Add a `vision` job to .github/workflows/ci.yml. Summarise each file in 5 lines
and the one non-obvious decision in it.
```

## When perft disagrees
```
perft 4 on "<fen>" gives N, suite says M. Use `./build/debug/chess divide 4 "<fen>"` and
`python3 tools/diff_vs_python_chess.py --divide "<fen>" 4`, find the root move whose subtree
differs, descend until you have a depth-1 position where our move list differs from python-chess,
and give me that FEN plus the two move lists. ultrathink.
```
