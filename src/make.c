/* make.c — make_move / unmake_move with a fixed-size undo stack.
 *
 * make_move records everything it is about to destroy (captured piece,
 * castling rights, ep square, halfmove clock) in one Undo entry, then edits
 * the board. unmake_move replays the same steps backwards from that entry.
 * Castling rights are updated with castle_mask(): any move from or to a
 * king/rook home square clears the rights that depend on that square.
 * The Zobrist hash: board_set/board_clear keep the piece part in step; the
 * castling/side/ep part is XOR-ed out before the move and XOR-ed in after.
 */
#include "make.h"
#include "board.h"
#include "zobrist.h"

#include <assert.h>

/* Castling rights a move keeps when it touches sq. Only six squares matter:
 * a king leaving its home square loses both rights, a rook leaving (or an
 * enemy piece landing on) a corner loses the right for that corner. */
static int castle_mask(Square sq)
{
    switch (sq) {
    case E1: return CASTLE_ALL & ~(CASTLE_WK | CASTLE_WQ);
    case A1: return CASTLE_ALL & ~CASTLE_WQ;
    case H1: return CASTLE_ALL & ~CASTLE_WK;
    case E8: return CASTLE_ALL & ~(CASTLE_BK | CASTLE_BQ);
    case A8: return CASTLE_ALL & ~CASTLE_BQ;
    case H8: return CASTLE_ALL & ~CASTLE_BK;
    default: return CASTLE_ALL;
    }
}

static int pawn_dir(Color c) { return c == WHITE ? 1 : -1; }

/* Square of the pawn an en-passant capture removes: behind the target square. */
static Square ep_victim_square(Move m, Color us) { return m.to - 8 * pawn_dir(us); }

/* The rook's squares for a castling move: from the corner to beside the king. */
static void castling_rook_squares(Move m, Square *rook_from, Square *rook_to)
{
    if (m.flags & CASTLE_K) { *rook_from = m.to + 1; *rook_to = m.to - 1; }
    else                    { *rook_from = m.to - 2; *rook_to = m.to + 1; }
}

void make_move(Position *pos, Move m)
{
    assert(board_consistent(pos));
    assert(pos->ply < MAX_PLY);
    Color us = pos->side_to_move;
    Piece piece = pos->board[m.from];
    assert(piece != EMPTY && piece_color(piece) == us);

    Undo *u = &pos->undo[pos->ply++];
    u->move = m;
    u->castling = pos->castling;
    u->ep_square = pos->ep_square;
    u->halfmove_clock = pos->halfmove_clock;
    u->hash = pos->hash;
    pos->hash ^= zobrist_state_key(pos);   /* XOR out old castling/side/ep; pieces follow */

    Square victim_sq = (m.flags & EN_PASSANT) ? ep_victim_square(m, us) : m.to;
    u->captured = pos->board[victim_sq];
    assert(((m.flags & CAPTURE) != 0) == (u->captured != EMPTY));
    if (u->captured != EMPTY) board_clear(pos, victim_sq);

    board_clear(pos, m.from);
    board_set(pos, m.to, (m.flags & PROMOTION) ? make_piece(us, m.promo) : piece);
    if (m.flags & (CASTLE_K | CASTLE_Q)) {
        Square rook_from, rook_to;
        castling_rook_squares(m, &rook_from, &rook_to);
        board_set(pos, rook_to, pos->board[rook_from]);
        board_clear(pos, rook_from);
    }

    pos->castling &= castle_mask(m.from) & castle_mask(m.to);
    pos->ep_square = (m.flags & DOUBLE_PUSH) ? m.from + 8 * pawn_dir(us) : NO_SQUARE;
    bool resets_clock = piece_type(piece) == PAWN || u->captured != EMPTY;
    pos->halfmove_clock = resets_clock ? 0 : pos->halfmove_clock + 1;
    if (us == BLACK) pos->fullmove_number++;
    pos->side_to_move = us == WHITE ? BLACK : WHITE;
    pos->hash ^= zobrist_state_key(pos);   /* XOR in the new ones */
    assert(board_consistent(pos));
}

void unmake_move(Position *pos)
{
    assert(pos->ply > 0);
    Undo *u = &pos->undo[--pos->ply];
    Move m = u->move;
    Color us = pos->side_to_move == WHITE ? BLACK : WHITE;   /* who played m */

    Piece piece = pos->board[m.to];
    if (m.flags & PROMOTION) piece = make_piece(us, PAWN);
    board_clear(pos, m.to);
    board_set(pos, m.from, piece);
    if (m.flags & (CASTLE_K | CASTLE_Q)) {
        Square rook_from, rook_to;
        castling_rook_squares(m, &rook_from, &rook_to);
        board_set(pos, rook_from, pos->board[rook_to]);
        board_clear(pos, rook_to);
    }
    if (u->captured != EMPTY) {
        Square victim_sq = (m.flags & EN_PASSANT) ? ep_victim_square(m, us) : m.to;
        board_set(pos, victim_sq, u->captured);
    }

    pos->castling = u->castling;
    pos->ep_square = u->ep_square;
    pos->halfmove_clock = u->halfmove_clock;
    if (us == BLACK) pos->fullmove_number--;
    pos->side_to_move = us;
    pos->hash = u->hash;   /* restore, never recompute: board_set/clear above moved it around */
    assert(board_consistent(pos));
}
