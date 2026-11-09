/* fen.h — Forsyth–Edwards Notation: text <-> Position (SPEC.md §Public API). */
#ifndef CHESS_FEN_H
#define CHESS_FEN_H

#include "types.h"

/* Why fen_parse rejected a string. 0 means success; every other value is a
 * distinct reason so the tests can check that the parser failed for the right
 * reason and the CLI can print a useful message. */
typedef enum {
    FEN_OK = 0,
    FEN_ERR_NULL,         /* fen or pos pointer is NULL */
    FEN_ERR_FIELDS,       /* fewer than the 6 space-separated fields */
    FEN_ERR_TRAILING,     /* anything but whitespace after the fullmove number */
    FEN_ERR_RANK_COUNT,   /* not exactly 8 ranks separated by '/' */
    FEN_ERR_RANK_WIDTH,   /* a rank does not describe exactly 8 squares */
    FEN_ERR_BAD_CHAR,     /* not a piece letter or a digit 1-8 (or two digits in a row) */
    FEN_ERR_KINGS,        /* not exactly one king per side, or the kings touch */
    FEN_ERR_PAWN_RANK,    /* a pawn on rank 1 or rank 8 */
    FEN_ERR_PIECE_COUNT,  /* more than 8 pawns or more than 16 pieces of one colour */
    FEN_ERR_SIDE,         /* side to move is not exactly "w" or "b" */
    FEN_ERR_CASTLING,     /* bad castling field, or a right whose king/rook is not at home */
    FEN_ERR_EP_SQUARE,    /* malformed ep square, wrong rank for the side to move,
                             or no pawn behind it / squares not empty */
    FEN_ERR_COUNTER,      /* counters not plain decimal, out of range, or
                             halfmove clock nonzero right after a double push */
    FEN_ERR_IN_CHECK,     /* the side NOT to move is in check (king could be captured) */
    FEN_ERR_COUNT         /* number of codes, not an error */
} FenError;

/* Pre: none (both pointers may be NULL, the string may be anything).
 * Post: returns FEN_OK and *pos holds the position, or returns a FenError and
 * *pos is left exactly as it was. Never crashes, whatever the input.
 * Accepts fields separated by any whitespace; trailing whitespace is fine. */
int fen_parse(Position *pos, const char *fen);

/* Pre: board_consistent(pos), buf has room for n bytes.
 * Post: buf holds the FEN, NUL-terminated and truncated to fit n (n == 0
 * writes nothing). The ep square is always written when set (decision Q4).
 * FEN_MAX_LEN bytes is always enough. */
void fen_write(const Position *pos, char *buf, size_t n);

/* Pre: none.  Post: a short human-readable reason for a FenError code. */
const char *fen_error_string(int err);

#endif /* CHESS_FEN_H */
