/* san.h — Standard Algebraic Notation: Move <-> "Nf3", "exd6", "O-O", "e8=Q+" (pass 2). */
#ifndef CHESS_SAN_H
#define CHESS_SAN_H

#include "types.h"

enum { SAN_MAX_LEN = 16 };   /* longest is "Qa1xb2=Q#" style: 9 chars + NUL, with margin */

typedef enum {
    SAN_OK = 0,
    SAN_ERR_SYNTAX,      /* not shaped like a SAN move */
    SAN_ERR_ILLEGAL,     /* well-formed, but no legal move matches */
    SAN_ERR_AMBIGUOUS    /* more than one legal move matches (needs disambiguation) */
} SanError;

/* Pre: board_consistent(pos), m is a legal move in pos, pos->ply < MAX_PLY.
 * Post: buf holds the SAN of m with the minimal disambiguation and a
 * trailing '+' or '#' when the move gives check or mate; pos is unchanged
 * (the move is made and unmade internally to find the suffix). */
void move_to_san(Position *pos, Move m, char buf[SAN_MAX_LEN]);

/* Pre: board_consistent(pos), s != NULL.
 * Post: SAN_OK and *out = the unique legal move written as s, else an error
 * code. Accepts "O-O"/"0-0", "=Q" or "Q" promotions, over-disambiguation,
 * and ignores trailing "+", "#", "!", "?". Never crashes. */
int move_from_san(const Position *pos, const char *s, Move *out);

#endif /* CHESS_SAN_H */
