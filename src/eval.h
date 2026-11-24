/* eval.h — static evaluation: how good is this position, without looking ahead (pass 3).
 *
 * Material plus piece-square tables, in integer centipawns (a pawn = 100).
 * The piece-square tables are Tomasz Michniewski's "Simplified Evaluation
 * Function": a knight is worth more in the centre than on the rim, a pawn
 * more as it advances, a king safer in its corner until the queens are gone.
 */
#ifndef CHESS_EVAL_H
#define CHESS_EVAL_H

#include "types.h"

/* Centipawn value of a piece type; PIECE_VALUE[KING] is 0 (kings are never traded). */
extern const int PIECE_VALUE[KING + 1];

/* Pre: board_consistent(pos).
 * Post: the score from the point of view of the side to move: positive means
 * the side to move is better. evaluate(mirror image with colours swapped) is equal. */
int evaluate(const Position *pos);

#endif /* CHESS_EVAL_H */
