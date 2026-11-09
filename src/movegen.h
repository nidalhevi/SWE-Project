/* movegen.h — move generation and attack detection (SPEC.md §Public API).
 * Implementation is session 2; pass 1 session 1 ships stubs that exit with
 * EXIT_NOT_IMPLEMENTED. move_to_uci() is already real. */
#ifndef CHESS_MOVEGEN_H
#define CHESS_MOVEGEN_H

#include "types.h"

/* Pre: board_consistent(pos).  Post: *out holds every pseudo-legal move
 * (king may be left in check); returns out->count. */
int gen_pseudo_legal(const Position *pos, MoveList *out);

/* Pre: board_consistent(pos) and the side NOT to move is not in check.
 * Post: *out holds exactly the legal moves; returns out->count. */
int gen_legal(const Position *pos, MoveList *out);

/* Pre: board_consistent(pos), 0 <= sq < 64.
 * Post: true iff a piece of colour `by` attacks sq. */
bool is_square_attacked(const Position *pos, Square sq, Color by);

/* Pre: board_consistent(pos).  Post: true iff the side to move is in check. */
bool in_check(const Position *pos);

/* Pre: board consistent (the hash may be stale: zobrist_state_key calls this).
 * Post: true iff the side to move has a LEGAL en-passant capture. */
bool has_legal_en_passant(const Position *pos);

/* Pre: m has valid from/to; promo is NO_TYPE or KNIGHT..QUEEN.
 * Post: buf holds "e2e4" or "e7e8q", NUL-terminated. */
void move_to_uci(Move m, char buf[6]);

/* Pre: board_consistent(pos), s != NULL.
 * Post: 0 and *out = the legal move written as s, or nonzero if s is not a
 * legal move in pos (never crashes). */
int move_from_uci(const Position *pos, const char *s, Move *out);

#endif /* CHESS_MOVEGEN_H */
