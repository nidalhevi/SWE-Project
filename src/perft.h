/* perft.h — move-generator correctness counting (SPEC.md §Public API). Session 2. */
#ifndef CHESS_PERFT_H
#define CHESS_PERFT_H

#include "types.h"

/* Pre: board_consistent(pos), 0 <= depth < MAX_PLY - pos->ply.
 * Post: returns the number of leaf nodes at exactly `depth` plies
 * (depth 0 -> 1). pos is unchanged on return. */
uint64_t perft(Position *pos, int depth);

/* Pre: as perft, depth >= 1.
 * Post: prints "<uci> <nodes>" for every root move (sorted by UCI string),
 * then "total <n>"; returns n. pos is unchanged on return. */
uint64_t perft_divide(Position *pos, int depth);

/* --- pass 3: two other ways to walk the same tree, for docs/perf.md -------- */

enum { PERFT_MAX_THREADS = 64 };

/* Pre: as perft, depth < 64.  Post: the same count as perft(pos, depth), obtained by
 * "copy-make": every move is played on a fresh copy of the position, and
 * nothing is ever undone. pos is never modified. */
uint64_t perft_copy(const Position *pos, int depth);

/* Pre: as perft, 1 <= threads <= PERFT_MAX_THREADS.
 * Post: the same count as perft(pos, depth), with the root moves shared out
 * among `threads` POSIX threads, each working on its own copy of the position.
 * Not re-entrant: one call at a time (the copies live in static storage). */
uint64_t perft_threads(const Position *pos, int depth, int threads);

#endif /* CHESS_PERFT_H */
