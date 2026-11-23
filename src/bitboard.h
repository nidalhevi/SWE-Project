/* bitboard.h — sets of squares as 64-bit words, and the attack sets built on them (pass 3).
 *
 * A Bitboard has bit sq set when square sq (a1 = 0 ... h8 = 63) is in the set.
 * "Which squares does a knight on f3 attack" is then one word, and "is any
 * enemy knight on one of them" is one AND. This file is the performance
 * ladder of SPEC.md pass 3; docs/perf.md records what each rung bought.
 */
#ifndef CHESS_BITBOARD_H
#define CHESS_BITBOARD_H

#include "types.h"

#define BB_FILE_A 0x0101010101010101ULL
#define BB_FILE_H 0x8080808080808080ULL

/* Pre: 0 <= sq < 64 (a shift by 64 or more is undefined behaviour). */
static inline Bitboard bb_of(Square sq) { return 1ULL << sq; }

/* Index of the lowest set bit. Pre: b != 0 (the builtin is undefined for 0). */
static inline Square bb_lsb(Bitboard b) { return (Square)__builtin_ctzll(b); }

/* Attack sets of the leapers, one word per square, filled by bb_init(). */
extern Bitboard BB_KNIGHT[SQUARE_NB];
extern Bitboard BB_KING[SQUARE_NB];
extern Bitboard BB_PAWN[2][SQUARE_NB];   /* [colour of the pawn][its square] */

/* Pre: none.  Post: the tables above are filled. Called by board_init(), so
 * every Position that exists was created after it; calling it again does nothing. */
void bb_init(void);

/* Pre: 0 <= sq < 64, bb_init() has run.  Post: the squares a knight / king on sq attacks. */
static inline Bitboard bb_knight_attacks(Square sq) { return BB_KNIGHT[sq]; }
static inline Bitboard bb_king_attacks(Square sq) { return BB_KING[sq]; }

/* Pre: as above.  Post: the squares a pawn of colour c on sq attacks (not where it pushes). */
static inline Bitboard bb_pawn_attacks(Color c, Square sq) { return BB_PAWN[c][sq]; }

/* A slider's attack set depends on which squares of its rays are occupied.
 * "Magic" lookup: keep only the occupied squares that matter (mask), multiply
 * by a constant chosen so that every such arrangement lands in its own slot
 * (magic), keep the top bits (shift), and read the precomputed answer (table).
 * The constants come from tools/gen_magics.c; bb_init() fills the tables. */
typedef struct {
    Bitboard        mask;    /* the ray squares whose occupancy matters (board edges excluded) */
    uint64_t        magic;
    const Bitboard *table;   /* 2^(64 - shift) attack sets for this square */
    int             shift;
} BbMagic;

extern BbMagic BB_BISHOP_MAGIC[SQUARE_NB];
extern BbMagic BB_ROOK_MAGIC[SQUARE_NB];

/* Pre: 0 <= sq < 64, bb_init() has run; occ = every occupied square.
 * Post: the squares a bishop / rook on sq attacks: along each ray up to and
 * including the first occupied square, whatever stands there. */
static inline Bitboard bb_bishop_attacks(Square sq, Bitboard occ)
{
    const BbMagic *m = &BB_BISHOP_MAGIC[sq];
    return m->table[((occ & m->mask) * m->magic) >> m->shift];
}

static inline Bitboard bb_rook_attacks(Square sq, Bitboard occ)
{
    const BbMagic *m = &BB_ROOK_MAGIC[sq];
    return m->table[((occ & m->mask) * m->magic) >> m->shift];
}

#endif /* CHESS_BITBOARD_H */
