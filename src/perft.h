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

#endif /* CHESS_PERFT_H */
