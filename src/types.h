/* types.h — core data types for chess-c (SPEC.md §Data model).
 *
 * Square indexing is a1 = 0, b1 = 1, ..., h1 = 7, a2 = 8, ..., h8 = 63
 * (file fastest), the same convention as python-chess. There is no other one.
 */
#ifndef CHESS_TYPES_H
#define CHESS_TYPES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef enum { WHITE = 0, BLACK = 1 } Color;

/* Piece codes: white 1..6, black 7..12. Black = white + 6, so the
 * colour and type can be recovered with one comparison and one subtraction. */
typedef int Piece;
enum { EMPTY = 0, WP, WN, WB, WR, WQ, WK, BP, BN, BB, BR, BQ, BK, PIECE_NB };

/* Piece types (colourless). PAWN..KING equal the white piece codes. */
enum { NO_TYPE = 0, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING };

/* One bit per square, bit sq set = "this square is in the set" (a1 = bit 0 ... h8 = bit 63). */
typedef uint64_t Bitboard;

typedef int Square;
enum { NO_SQUARE = -1, SQUARE_NB = 64 };
/* The squares castling cares about; everything else is computed. */
enum { A1 = 0, B1, C1, D1, E1, F1, G1, H1, A8 = 56, B8, C8, D8, E8, F8, G8, H8 };

/* Castling rights, one bit each, in FEN order: K Q k q. */
enum { CASTLE_WK = 1, CASTLE_WQ = 2, CASTLE_BK = 4, CASTLE_BQ = 8, CASTLE_ALL = 15 };

/* Move flags. These are bits, so a capturing promotion is CAPTURE | PROMOTION. */
enum {
    NORMAL      = 0,
    CAPTURE     = 1 << 0,
    DOUBLE_PUSH = 1 << 1,
    EN_PASSANT  = 1 << 2,
    CASTLE_K    = 1 << 3,
    CASTLE_Q    = 1 << 4,
    PROMOTION   = 1 << 5
};

/* A plain struct in pass 1 (SPEC.md decision Q3). */
typedef struct {
    Square from;
    Square to;
    int    promo;   /* NO_TYPE, or KNIGHT..QUEEN when PROMOTION is set */
    int    flags;   /* OR of the move flags above */
} Move;

/* What make_move() must remember so that unmake_move() can restore it. */
typedef struct {
    Move   move;
    Piece  captured;        /* EMPTY if nothing was captured */
    int    castling;
    Square ep_square;
    int    halfmove_clock;
    uint64_t hash;          /* key of the position before the move */
} Undo;

enum { MAX_PLY = 1024, MAX_MOVES = 256, FEN_MAX_LEN = 128 };

typedef struct {
    int    board[SQUARE_NB];   /* Piece on each square, EMPTY = 0 */
    Color  side_to_move;
    int    castling;           /* OR of CASTLE_* bits */
    Square ep_square;          /* NO_SQUARE, or the square a double push skipped */
    int    halfmove_clock;     /* plies since the last capture or pawn move */
    int    fullmove_number;    /* starts at 1, +1 after each black move */
    Square king_sq[2];         /* indexed by Color */
    uint64_t hash;             /* Zobrist key, kept in step by board_set/clear and make_move */
    Bitboard bb[PIECE_NB];     /* squares holding each piece code (bb[EMPTY] unused); pass 3 */
    Bitboard occ;              /* every occupied square; both kept in step by board_set/clear */
    int    ply;                /* number of entries in use on the undo stack */
    Undo   undo[MAX_PLY];      /* undo stack, fixed capacity, no heap. Kept LAST: everything
                                * before it is the position itself (about 500 bytes) and can be
                                * copied on its own, see position_copy_head() */
} Position;

typedef struct {
    Move moves[MAX_MOVES];
    int  count;
} MoveList;

/* Pre: src is a consistent position.  Post: dst is the same position with an
 * empty undo stack: only the bytes before `undo` are copied, not the 50 KB stack.
 * dst therefore has no history (repetition counts start again from here). */
static inline void position_copy_head(Position *dst, const Position *src)
{
    memcpy(dst, src, offsetof(Position, undo));
    dst->ply = 0;
}

/* Process exit codes shared by the CLI and the test Makefile. */
enum { EXIT_TEST_FAILURE = 1, EXIT_INVALID_INPUT = 2, EXIT_NOT_IMPLEMENTED = 3 };

/* --- small inline helpers; all take valid input (asserted by callers) --- */

static inline int sq_file(Square sq) { return sq & 7; }
static inline int sq_rank(Square sq) { return sq >> 3; }
static inline Square make_square(int file, int rank) { return (Square)(rank * 8 + file); }

/* Precondition: p != EMPTY. */
static inline Color piece_color(Piece p) { return p >= BP ? BLACK : WHITE; }
/* Returns NO_TYPE for EMPTY, PAWN..KING otherwise. */
static inline int piece_type(Piece p) { return p > WK ? p - 6 : p; }
static inline Piece make_piece(Color c, int type) { return c == WHITE ? type : type + 6; }

#endif /* CHESS_TYPES_H */
