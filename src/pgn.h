/* pgn.h — Portable Game Notation import and export (pass 2).
 *
 * A game is a Position whose undo stack holds the moves played, so there is
 * no separate Game type: pgn_parse() leaves the moves on pos's stack and
 * pgn_write() walks that stack. Only the first game in a text is read.
 */
#ifndef CHESS_PGN_H
#define CHESS_PGN_H

#include "types.h"
#include <stddef.h>

typedef enum {
    PGN_OK = 0,
    PGN_ERR_NULL,          /* a NULL pointer */
    PGN_ERR_TAG,           /* malformed [Tag "value"] pair, or a tag after the moves began */
    PGN_ERR_FEN,           /* the FEN tag does not parse */
    PGN_ERR_MOVE,          /* a move token is not a legal SAN move in that position */
    PGN_ERR_TOO_LONG,      /* more than MAX_PLY plies */
    PGN_ERR_UNTERMINATED,  /* a { comment or ( variation is never closed */
    PGN_ERR_COUNT
} PgnError;

enum { PGN_MAX_LEN = 16384 };   /* enough for the longest game the undo stack holds */

/* Pre: none (never crashes on any text).
 * Post: PGN_OK and *pos holds the final position with every move on the undo
 * stack (standard start, or the FEN tag's position), or an error code and
 * *pos left exactly as it was. Comments, variations, NAGs and move numbers
 * are skipped; a result token ends the game. */
int pgn_parse(Position *pos, const char *text);

/* Pre: board_consistent(pos), buf has room for n bytes.
 * Post: buf holds the seven-tag roster (with SetUp/FEN when the game did not
 * start from the standard position), the movetext in SAN wrapped at 80
 * columns, and the result; NUL-terminated and truncated to fit n. */
void pgn_write(const Position *pos, char *buf, size_t n);

/* Pre: none.  Post: a short human-readable reason for a PgnError code. */
const char *pgn_error_string(int err);

#endif /* CHESS_PGN_H */
