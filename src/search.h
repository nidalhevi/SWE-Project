/* search.h — choosing a move by looking ahead (pass 3).
 *
 * Negamax with alpha-beta pruning, iterative deepening (depth 1, 2, 3, ...
 * until the depth or time limit), quiescence search at the leaves (keep
 * capturing until the position is quiet, so a queen trade is not cut off in
 * the middle) and MVV-LVA move ordering (most valuable victim, least valuable
 * attacker first: good captures early make alpha-beta cut more).
 */
#ifndef CHESS_SEARCH_H
#define CHESS_SEARCH_H

#include "types.h"
#include <stdio.h>

enum {
    MATE_SCORE = 30000,     /* being mated now; mate in n plies scores MATE_SCORE - n */
    SCORE_INF  = 32000,     /* outside every real score; never INT_MIN (cannot be negated) */
    MAX_SEARCH_DEPTH = 64
};

typedef struct {
    int depth;         /* stop after this depth; 0 = MAX_SEARCH_DEPTH */
    int movetime_ms;   /* stop after this long; 0 = no time limit (then depth must be > 0) */
} SearchLimits;

typedef struct {
    Move     best;     /* valid iff has_move */
    bool     has_move; /* false iff the position has no legal move */
    int      score;    /* centipawns for the side to move, or +-(MATE_SCORE - plies) */
    int      depth;    /* last depth searched completely */
    uint64_t nodes;
} SearchResult;

/* Pre: board_consistent(pos), the side not to move is not in check,
 *      limits.depth > 0 or limits.movetime_ms > 0.
 * Post: the best move found within the limits; pos is unchanged. If info is
 *       not NULL, one UCI "info depth ... " line is printed per finished depth. */
SearchResult search_position(Position *pos, SearchLimits limits, FILE *info);

/* Pre: a score from search_position.  Post: true iff it announces a forced mate. */
bool score_is_mate(int score);

#endif /* CHESS_SEARCH_H */
