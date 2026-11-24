# perf.md — pass 3 measurements

Machine: Apple M5 Pro (5 performance + 10 efficiency cores), Apple clang 21, `-O2 -DNDEBUG`.
Tool: `hyperfine -N --warmup 1 --runs 5` (mean of 5 runs; the spread was under 1% except where noted).
Measured 2026-11-18. Reproduce the last three rows of each table with `tools/bench_perft.sh`.

Workloads (perft counts leaves; depth 1 is bulk-counted, so "nodes" means leaf positions):
- **start**: `perft 6` from the starting position, 119,060,324 nodes.
- **kiwipete**: `perft 5` on `r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1`, 193,690,690 nodes.

Every rung was accepted only after `chess perft-suite tests/perft_suite.epd 5` passed, and the final code passes
`make test` under ASan + UBSan. The threaded perft also ran clean under ThreadSanitizer.

## The ladder, one thread

| Rung | What changed | start: time | M nodes/s | instr/node | kiwipete: time | M nodes/s | instr/node |
|---|---|---|---|---|---|---|---|
| 0 | mailbox only (end of pass 2) | 2.533 s | 47.0 | 582 | 3.904 s | 49.6 | 564 |
| 1 | bitboards for attack detection | 1.738 s | 68.5 | 438 | 2.468 s | 78.5 | 420 |
| 2 | lookup tables for knight, king, pawn | 1.426 s | 83.5 | 381 | 2.149 s | 90.1 | 369 |
| 3 | magic tables for bishop, rook, queen | 0.895 s | 133.1 | 223 | 1.167 s | 166.0 | 190 |
| 4 | make/unmake (kept) | 0.892 s | 133.4 | 222 | 1.164 s | 166.5 | 190 |
| 4 | copy-make (`perft-copy`) | 0.898 s | 132.5 | 222 | 1.161 s | 166.8 | 190 |

Overall, one thread: **2.8x** on start, **3.4x** on kiwipete. (Rung 1 on start had one slow run, ±0.18 s.)

What each rung is, and why it helped:
- **Rung 1.** The position keeps one 64-bit set per piece code and one for all occupied squares, updated in
  `board_set` / `board_clear`. "Is the king attacked after this move" used to copy the 64-int board, replay the
  move and walk rays from the king. Now nothing is copied: the move changes the occupied set by two bits and
  removes at most one enemy piece, and that is all the attack test needs (`leaves_king_safe` in movegen.c).
  This is the test that runs once per pseudo-legal move, so it is where the time was.
- **Rung 2.** Knight, king and pawn attack sets no longer get computed by shifting: they are read from tables
  filled once at start-up. Knight and king moves are generated from the same tables.
- **Rung 3.** The slider rays were still walked square by square. A magic table turns "where can this rook go,
  given what is on its rays" into a multiply, a shift and one memory read. The biggest single step, because
  sliders are both the most common attackers to test for and the pieces with the most moves. The 128 magic
  constants come from `tools/gen_magics.c` and are pasted into bitboard.c; the engine never searches for them.
  The tables are 860 KB of static storage, filled in under a millisecond.
- **Rung 4: no measurable difference**, and the reason is worth more than the number. Copy-make copies the
  ~500 bytes of position that sit before the undo stack; make/unmake writes one undo record and reverses it.
  Both are cheap next to generating and filtering the moves, and with bulk counting a move is only *made* at
  interior nodes, about one in thirty. We kept make/unmake because the search and the game history need the
  undo stack anyway. Copy-make stays as `chess perft-copy` so the comparison can be rerun.

## Rung 5: root split with threads (`perft-mt`)

| Threads | start: time | M nodes/s | speed-up | CPU time |
|---|---|---|---|---|
| 1 | 0.896 s | 133 | 1.0x | 0.89 s |
| 2 | 0.462 s | 258 | 1.9x | 0.89 s |
| 4 | 0.244 s | 489 | 3.7x | 0.91 s |
| 8 | 0.143 s | 831 | 6.3x | 1.02 s |
| 15 | 0.098 s | 1,211 | 9.1x | 1.10 s |

Kiwipete: 8 threads 0.183 s (1,057 M nodes/s, 6.4x), 15 threads 0.125 s (1,551 M nodes/s, 9.3x).

The root moves are handed out through one atomic counter; each thread has its own copy of the position, so
nothing else is shared and no lock is needed. Scaling is near-linear up to 4 threads and then bends, for two
reasons visible in the table: beyond 5 threads the work lands on efficiency cores, which are slower (CPU time
rises from 0.89 s to 1.10 s for the same instructions), and with 20 root moves the last few subtrees cannot be
divided further, so some threads finish early.

Start to end, with all cores: 47 M nodes/s to 1,211 M nodes/s, **26x**.

## What the same work did for the search

`chess search 6` from the starting position: 0.29 s before the ladder, 0.16 s after, on about 607,000 nodes
(2.1 to 3.8 M nodes/s). The search spends its time in the same move generator, plus evaluation and ordering.

## Playing strength

cutechess-cli is not packaged for Homebrew and building it needs Qt, so the matches were run with
`tools/match.py`: python-chess drives both engines over UCI and referees. 40 games per match, 0.1 s per move,
20 openings each played with both colours, against Stockfish with `UCI_LimitStrength` at three levels.

| Opponent | Result for chess-c | Score | Implied Elo (95% interval) |
|---|---|---|---|
| Stockfish limited to 1320 | +38 =1 −1 | 96% | above 1700 |
| Stockfish limited to 1600 | +26 =4 −10 | 70% | about 1750 (1650 to 1880) |
| Stockfish limited to 1900 | +18 =7 −15 | 54% | about 1925 (1830 to 2030) |

Read this as **roughly 1750 to 1950 on Stockfish's limited-strength scale at this time control**, not as a
rating. The two estimates do not agree with each other because Stockfish's scale is calibrated for much longer
games, and 40 games give wide intervals. The engine lost no game on time or by an illegal move.

## Not done
- **`perf stat` on the course Linux VM** (decision Q11). We had no access to the VM from this session. hyperfine
  on macOS already reports instructions and cycles per run, which is where the instr/node columns come from;
  cache-miss and branch-miss counters still need the Linux run.
- **Packed 16-bit `Move`** (decision Q3 left it as a measured pass-3 option). Not tried: after rung 3 the move
  list is not where the time goes.
- Rungs 0 to 3 were timed from binaries saved while building (`build/perf/`, not committed). They cannot be
  rebuilt from git unless each rung is committed separately; the table above is the record.
