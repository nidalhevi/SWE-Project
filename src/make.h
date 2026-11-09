/* make.h — applying and undoing moves (SPEC.md §Public API). Session 2. */
#ifndef CHESS_MAKE_H
#define CHESS_MAKE_H

#include "types.h"

/* Pre: board_consistent(pos), m is a legal move in pos, pos->ply < MAX_PLY.
 * Post: m has been played, the side to move flipped, castling/ep/clocks
 * updated, and one Undo entry pushed. board_consistent(pos) still holds. */
void make_move(Position *pos, Move m);

/* Pre: pos->ply > 0.  Post: the last make_move() is undone exactly. */
void unmake_move(Position *pos);

#endif /* CHESS_MAKE_H */
