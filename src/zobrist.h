/* zobrist.h — Zobrist hashing: a 64-bit key for a position (pass 2).
 *
 * Every (piece, square) pair, every castling-rights combination, every
 * en-passant file and "black to move" gets one random 64-bit number. The key
 * of a position is the XOR of the numbers for everything that is true about
 * it. XOR is its own inverse, so a move updates the key by XOR-ing out what
 * changed and XOR-ing in what replaced it, in constant time.
 *
 * The en-passant file is part of the key only when a legal en-passant
 * capture exists, which is the definition python-chess uses for repetition.
 */
#ifndef CHESS_ZOBRIST_H
#define CHESS_ZOBRIST_H

#include "types.h"

extern uint64_t ZOB_PIECE[PIECE_NB][SQUARE_NB];   /* ZOB_PIECE[EMPTY][*] is 0 */
extern uint64_t ZOB_CASTLING[CASTLE_ALL + 1];
extern uint64_t ZOB_EP_FILE[8];
extern uint64_t ZOB_SIDE;                          /* XOR-ed in when black is to move */

/* Pre: none.  Post: the tables above are filled from a fixed seed, so every
 * run of the program uses the same numbers. Calling it again does nothing. */
void zobrist_init(void);

/* Pre: board_consistent(pos) except possibly the hash itself.
 * Post: the part of the key that is not about pieces: castling rights, side
 * to move, and the en-passant file when a legal en-passant capture exists. */
uint64_t zobrist_state_key(const Position *pos);

/* Pre: as above.  Post: the full key, computed from scratch. make_move keeps
 * pos->hash equal to this incrementally; board_consistent() checks it. */
uint64_t zobrist_hash(const Position *pos);

#endif /* CHESS_ZOBRIST_H */
