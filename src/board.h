/* board.h — the mailbox board and its helpers (SPEC.md §Data model). */
#ifndef CHESS_BOARD_H
#define CHESS_BOARD_H

#include "types.h"
#include <stdio.h>

/* Pre: pos != NULL.  Post: empty board, white to move, no rights, no ep,
 * counters 0/1, king_sq = NO_SQUARE, undo stack empty. */
void board_init(Position *pos);

/* Pre: 0 <= sq < 64.  Post: returns the piece on sq (EMPTY if none). */
Piece piece_at(const Position *pos, Square sq);

/* Pre: 0 <= sq < 64, EMPTY <= p < PIECE_NB.
 * Post: board[sq] == p; king_sq is updated when p is a king; the piece part
 * of pos->hash is updated. */
void board_set(Position *pos, Square sq, Piece p);

/* Pre: 0 <= sq < 64.  Post: board[sq] == EMPTY and the hash is updated.
 * king_sq is NOT touched (a king is never removed from the board; it only moves). */
void board_clear(Position *pos, Square sq);

/* Pre: pos != NULL.  Post: true iff every structural invariant holds:
 * piece codes in range, exactly one king per side and king_sq pointing at it,
 * side/castling/ep/counters/ply in range, no pawn on rank 1 or 8, and the
 * Zobrist hash equal to one computed from scratch.
 * Used by assert() in make/unmake, never for input validation. */
bool board_consistent(const Position *pos);

/* Pre: board_consistent(pos), out != NULL.  Post: the board printed as 8
 * lines of piece letters ('.' = empty) from rank 8 down, plus a file legend. */
void board_print(const Position *pos, FILE *out);

/* Text conversions.  Return NO_SQUARE / EMPTY on bad input; never crash. */
Square str_to_square(const char *s);          /* "e4" -> 28 (reads 2 chars) */
void   square_to_str(Square sq, char buf[3]); /* 28 -> "e4" (pre: valid sq) */
Piece  char_to_piece(char c);                 /* 'N' -> WN, 'q' -> BQ, else EMPTY */
char   piece_to_char(Piece p);                /* WN -> 'N'; pre: p != EMPTY */

/* Print "<what> is not implemented yet (session 2)" to stderr and exit with
 * EXIT_NOT_IMPLEMENTED (3). Used by the session-2 stubs so a missing module
 * fails loudly and the Makefile can tell "unimplemented" from "crashed". */
_Noreturn void chess_not_implemented(const char *what);

#endif /* CHESS_BOARD_H */
