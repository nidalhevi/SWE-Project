/* board.c — the mailbox board: init, access, consistency check, text helpers. */
#include "board.h"
#include "bitboard.h"
#include "zobrist.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char PIECE_CHARS[] = " PNBRQKpnbrqk";   /* index = Piece code */

void board_init(Position *pos)
{
    assert(pos != NULL);
    zobrist_init();
    bb_init();
    memset(pos, 0, sizeof *pos);   /* board = EMPTY, castling = 0, ply = 0, hash = 0 */
    pos->side_to_move    = WHITE;
    pos->ep_square       = NO_SQUARE;
    pos->fullmove_number = 1;
    pos->king_sq[WHITE]  = NO_SQUARE;
    pos->king_sq[BLACK]  = NO_SQUARE;
}

Piece piece_at(const Position *pos, Square sq)
{
    assert(sq >= 0 && sq < SQUARE_NB);
    return pos->board[sq];
}

void board_set(Position *pos, Square sq, Piece p)
{
    assert(sq >= 0 && sq < SQUARE_NB);
    assert(p >= EMPTY && p < PIECE_NB);
    Piece old = pos->board[sq];
    Bitboard b = 1ULL << sq;
    pos->hash ^= ZOB_PIECE[old][sq] ^ ZOB_PIECE[p][sq];
    pos->bb[old] &= ~b;            /* bb[EMPTY] absorbs the no-piece cases; it is never read */
    pos->bb[p] |= b;
    pos->occ = p == EMPTY ? pos->occ & ~b : pos->occ | b;
    pos->board[sq] = p;
    if (p == WK) pos->king_sq[WHITE] = sq;
    if (p == BK) pos->king_sq[BLACK] = sq;
}

void board_clear(Position *pos, Square sq)
{
    assert(sq >= 0 && sq < SQUARE_NB);
    pos->hash ^= ZOB_PIECE[pos->board[sq]][sq];
    pos->bb[pos->board[sq]] &= ~(1ULL << sq);
    pos->occ &= ~(1ULL << sq);
    pos->board[sq] = EMPTY;
}

/* The bitboards must say exactly what the mailbox says. */
static bool bitboards_consistent(const Position *pos)
{
    Bitboard occ = 0;
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        Piece p = pos->board[sq];
        if (p == EMPTY) continue;
        occ |= 1ULL << sq;
        if (!(pos->bb[p] & (1ULL << sq))) return false;
    }
    Bitboard all = 0;
    for (Piece p = WP; p < PIECE_NB; p++) {
        if (all & pos->bb[p]) return false;   /* two pieces on one square */
        all |= pos->bb[p];
    }
    return occ == pos->occ && all == occ;
}

/* One king per colour, and king_sq must point at it. */
static bool kings_consistent(const Position *pos)
{
    int kings[2] = {0, 0};
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        if (pos->board[sq] == WK) kings[WHITE]++;
        if (pos->board[sq] == BK) kings[BLACK]++;
    }
    for (int c = WHITE; c <= BLACK; c++) {
        Square k = pos->king_sq[c];
        if (kings[c] != 1 || k < 0 || k >= SQUARE_NB) return false;
        if (pos->board[k] != make_piece((Color)c, KING)) return false;
    }
    return true;
}

static bool ep_consistent(const Position *pos)
{
    Square ep = pos->ep_square;
    if (ep == NO_SQUARE) return true;
    if (ep < 0 || ep >= SQUARE_NB) return false;
    /* White to move: black just pushed to rank 5, skipping rank 6 (index 5). */
    int want_rank = pos->side_to_move == WHITE ? 5 : 2;
    return sq_rank(ep) == want_rank && pos->board[ep] == EMPTY;
}

bool board_consistent(const Position *pos)
{
    if (pos == NULL) return false;
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        Piece p = pos->board[sq];
        if (p < EMPTY || p >= PIECE_NB) return false;
        if (piece_type(p) == PAWN && (sq_rank(sq) == 0 || sq_rank(sq) == 7)) return false;
    }
    if (pos->side_to_move != WHITE && pos->side_to_move != BLACK) return false;
    if (pos->castling < 0 || pos->castling > CASTLE_ALL) return false;
    if (pos->halfmove_clock < 0 || pos->fullmove_number < 1) return false;
    if (pos->ply < 0 || pos->ply > MAX_PLY) return false;
    return kings_consistent(pos) && ep_consistent(pos) && bitboards_consistent(pos) &&
           pos->hash == zobrist_hash(pos);
}

void board_print(const Position *pos, FILE *out)
{
    assert(board_consistent(pos));
    for (int rank = 7; rank >= 0; rank--) {
        fprintf(out, " %d ", rank + 1);
        for (int file = 0; file < 8; file++) {
            Piece p = pos->board[make_square(file, rank)];
            fprintf(out, " %c", p == EMPTY ? '.' : piece_to_char(p));
        }
        fputc('\n', out);
    }
    fputs("    a b c d e f g h\n", out);
}

Square str_to_square(const char *s)
{
    if (s == NULL) return NO_SQUARE;
    if (s[0] < 'a' || s[0] > 'h' || s[1] < '1' || s[1] > '8') return NO_SQUARE;
    return make_square(s[0] - 'a', s[1] - '1');
}

void square_to_str(Square sq, char buf[3])
{
    assert(sq >= 0 && sq < SQUARE_NB);
    buf[0] = (char)('a' + sq_file(sq));
    buf[1] = (char)('1' + sq_rank(sq));
    buf[2] = '\0';
}

Piece char_to_piece(char c)
{
    for (Piece p = WP; p < PIECE_NB; p++)
        if (PIECE_CHARS[p] == c) return p;
    return EMPTY;
}

char piece_to_char(Piece p)
{
    assert(p > EMPTY && p < PIECE_NB);
    return PIECE_CHARS[p];
}

_Noreturn void chess_not_implemented(const char *what)
{
    fprintf(stderr, "chess: %s is not implemented yet (session 2)\n", what);
    exit(EXIT_NOT_IMPLEMENTED);
}
