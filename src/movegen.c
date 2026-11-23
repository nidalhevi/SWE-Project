/* movegen.c — attack detection and move generation.
 *
 * Pawns and castling read the mailbox board; step() refuses to leave the
 * board, so there is no wrap-around to worry about. Knights, kings and the
 * sliders take their target squares from the attack tables. Attack
 * detection uses the bitboards (bitboard.h, pass 3); gen_legal() filters the
 * pseudo-legal list by asking whether our king would be attacked after each
 * move, which needs only the changed occupied set, not a played position.
 */
#include "movegen.h"
#include "bitboard.h"
#include "board.h"

#include <assert.h>
#include <string.h>

/* Square reached from sq by one (df, dr) step, or NO_SQUARE if off the board. */
static Square step(Square sq, int df, int dr)
{
    int f = sq_file(sq) + df, r = sq_rank(sq) + dr;
    if (f < 0 || f > 7 || r < 0 || r > 7) return NO_SQUARE;
    return make_square(f, r);
}

/* Pawns move up the board for white (+1 rank) and down for black. */
static int pawn_dir(Color c) { return c == WHITE ? 1 : -1; }

/* ------------------------------------------------------------- attacks -- */

/* True iff a piece of colour `by` attacks sq, on a board whose occupied
 * squares are `occ` and from which the pieces on `gone` have been removed.
 * The two extra arguments let gen_legal ask "and after this move?" without
 * building the position: a move only changes occ and removes a captured piece.
 * A `by` pawn attacks sq exactly when a pawn of the other colour on sq would attack it. */
static bool attacked(const Position *pos, Square sq, Color by, Bitboard occ, Bitboard gone)
{
    const Bitboard *bb = pos->bb;
    Color other = by == WHITE ? BLACK : WHITE;
    if (bb_pawn_attacks(other, sq) & bb[make_piece(by, PAWN)] & ~gone) return true;
    if (bb_knight_attacks(sq) & bb[make_piece(by, KNIGHT)] & ~gone) return true;
    if (bb_king_attacks(sq) & bb[make_piece(by, KING)]) return true;
    Bitboard queens = bb[make_piece(by, QUEEN)];
    Bitboard diagonal = (bb[make_piece(by, BISHOP)] | queens) & ~gone;
    if (diagonal != 0 && (bb_bishop_attacks(sq, occ) & diagonal)) return true;
    Bitboard straight = (bb[make_piece(by, ROOK)] | queens) & ~gone;
    return straight != 0 && (bb_rook_attacks(sq, occ) & straight);
}

bool is_square_attacked(const Position *pos, Square sq, Color by)
{
    assert(sq >= 0 && sq < SQUARE_NB);
    return attacked(pos, sq, by, pos->occ, 0);
}

bool in_check(const Position *pos)
{
    Color us = pos->side_to_move;
    return is_square_attacked(pos, pos->king_sq[us], us == WHITE ? BLACK : WHITE);
}

/* ---------------------------------------------------- pseudo-legal moves -- */

static void add_move(MoveList *list, Square from, Square to, int promo, int flags)
{
    assert(list->count < MAX_MOVES);
    Move *m = &list->moves[list->count++];
    m->from = from; m->to = to; m->promo = promo; m->flags = flags;
}

/* A pawn arriving on the last rank becomes four moves, one per promotion piece. */
static void add_pawn_move(MoveList *list, Square from, Square to, int flags, int promo_rank)
{
    if (sq_rank(to) != promo_rank) { add_move(list, from, to, NO_TYPE, flags); return; }
    for (int type = KNIGHT; type <= QUEEN; type++)
        add_move(list, from, to, type, flags | PROMOTION);
}

static void gen_pawn(const Position *pos, MoveList *list, Square from)
{
    Color us = pos->side_to_move;
    int dir = pawn_dir(us);
    int start_rank = us == WHITE ? 1 : 6, promo_rank = us == WHITE ? 7 : 0;

    Square one = step(from, 0, dir);   /* never NO_SQUARE: no pawns on the back rank */
    if (pos->board[one] == EMPTY) {
        add_pawn_move(list, from, one, NORMAL, promo_rank);
        Square two = step(one, 0, dir);
        if (sq_rank(from) == start_rank && pos->board[two] == EMPTY)
            add_move(list, from, two, NO_TYPE, DOUBLE_PUSH);
    }
    for (int df = -1; df <= 1; df += 2) {
        Square to = step(from, df, dir);
        if (to == NO_SQUARE) continue;
        Piece target = pos->board[to];
        if (target != EMPTY && piece_color(target) != us)
            add_pawn_move(list, from, to, CAPTURE, promo_rank);
        else if (to == pos->ep_square)
            add_move(list, from, to, NO_TYPE, EN_PASSANT | CAPTURE);
    }
}

/* Add a move from `from` to every square in `targets`; landing on an occupied square is a capture. */
static void add_targets(const Position *pos, MoveList *list, Square from, Bitboard targets)
{
    while (targets != 0) {
        Square to = bb_lsb(targets);
        targets &= targets - 1;   /* clear the lowest set bit */
        add_move(list, from, to, NO_TYPE, (pos->occ & bb_of(to)) ? CAPTURE : NORMAL);
    }
}

/* Every square occupied by a piece of colour c. */
static Bitboard pieces_of(const Position *pos, Color c)
{
    const Bitboard *bb = pos->bb + (c == WHITE ? WP : BP);
    return bb[0] | bb[1] | bb[2] | bb[3] | bb[4] | bb[5];
}

/* Castling: right still held, squares between king and rook empty, and the
 * king not in check, not crossing, and not landing on an attacked square.
 * The FEN parser and make_move guarantee king and rook are at home while a
 * right is held, so only the squares in between are inspected here. */
static void gen_castling(const Position *pos, MoveList *list)
{
    Color us = pos->side_to_move, them = us == WHITE ? BLACK : WHITE;
    Square base = us == WHITE ? A1 : A8;   /* a1 or a8; king is on base + 4 */
    Square king = base + 4;
    if (is_square_attacked(pos, king, them)) return;

    int right_k = us == WHITE ? CASTLE_WK : CASTLE_BK;
    int right_q = us == WHITE ? CASTLE_WQ : CASTLE_BQ;
    const int *b = pos->board;

    if ((pos->castling & right_k) && b[base + 5] == EMPTY && b[base + 6] == EMPTY &&
        !is_square_attacked(pos, base + 5, them) && !is_square_attacked(pos, base + 6, them))
        add_move(list, king, base + 6, NO_TYPE, CASTLE_K);

    if ((pos->castling & right_q) && b[base + 1] == EMPTY && b[base + 2] == EMPTY &&
        b[base + 3] == EMPTY &&
        !is_square_attacked(pos, base + 3, them) && !is_square_attacked(pos, base + 2, them))
        add_move(list, king, base + 2, NO_TYPE, CASTLE_Q);
}

int gen_pseudo_legal(const Position *pos, MoveList *out)
{
    assert(board_consistent(pos));
    out->count = 0;
    Bitboard own = pieces_of(pos, pos->side_to_move);
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        Piece p = pos->board[sq];
        if (p == EMPTY || piece_color(p) != pos->side_to_move) continue;
        switch (piece_type(p)) {
        case PAWN:   gen_pawn(pos, out, sq); break;
        case KNIGHT: add_targets(pos, out, sq, bb_knight_attacks(sq) & ~own); break;
        case BISHOP: add_targets(pos, out, sq, bb_bishop_attacks(sq, pos->occ) & ~own); break;
        case ROOK:   add_targets(pos, out, sq, bb_rook_attacks(sq, pos->occ) & ~own); break;
        case QUEEN:  add_targets(pos, out, sq, (bb_bishop_attacks(sq, pos->occ) |
                                                 bb_rook_attacks(sq, pos->occ)) & ~own); break;
        case KING:   add_targets(pos, out, sq, bb_king_attacks(sq) & ~own);
                     gen_castling(pos, out); break;
        default:     assert(!"bad piece type");
        }
    }
    return out->count;
}

/* ----------------------------------------------------------- legal moves -- */

/* Is our king safe after m? Nothing is copied or played: the occupied set
 * after the move is the old one with `from` cleared and `to` set, and the only
 * enemy pieces that disappear are the one on `to` and an en-passant victim.
 * Castling moves the rook as well, for a faithful occupied set. */
static bool leaves_king_safe(const Position *pos, Move m)
{
    Color us = pos->side_to_move, them = us == WHITE ? BLACK : WHITE;
    Bitboard gone = bb_of(m.to);
    Bitboard occ = (pos->occ & ~bb_of(m.from)) | gone;
    if (m.flags & EN_PASSANT) {
        Bitboard victim = bb_of(m.to - 8 * pawn_dir(us));
        occ &= ~victim;
        gone |= victim;
    }
    if (m.flags & CASTLE_K) occ = (occ & ~bb_of(m.to + 1)) | bb_of(m.to - 1);
    if (m.flags & CASTLE_Q) occ = (occ & ~bb_of(m.to - 2)) | bb_of(m.to + 1);

    Square king = piece_type(pos->board[m.from]) == KING ? m.to : pos->king_sq[us];
    return !attacked(pos, king, them, occ, gone);
}

bool has_legal_en_passant(const Position *pos)
{
    Square ep = pos->ep_square;
    if (ep == NO_SQUARE) return false;
    Color us = pos->side_to_move;
    Piece pawn = make_piece(us, PAWN);
    for (int df = -1; df <= 1; df += 2) {
        Square from = step(ep, df, -pawn_dir(us));   /* a pawn beside the pushed pawn */
        if (from == NO_SQUARE || pos->board[from] != pawn) continue;
        Move m = { from, ep, NO_TYPE, EN_PASSANT | CAPTURE };
        if (leaves_king_safe(pos, m)) return true;
    }
    return false;
}

int gen_legal(const Position *pos, MoveList *out)
{
    MoveList pseudo;
    gen_pseudo_legal(pos, &pseudo);
    out->count = 0;
    for (int i = 0; i < pseudo.count; i++)
        if (leaves_king_safe(pos, pseudo.moves[i])) out->moves[out->count++] = pseudo.moves[i];
    return out->count;
}

/* ------------------------------------------------------------------ UCI -- */

void move_to_uci(Move m, char buf[6])
{
    static const char PROMO_CHARS[] = { [KNIGHT] = 'n', [BISHOP] = 'b', [ROOK] = 'r', [QUEEN] = 'q' };
    assert(m.promo == NO_TYPE || (m.promo >= KNIGHT && m.promo <= QUEEN));
    square_to_str(m.from, buf);
    square_to_str(m.to, buf + 2);
    if (m.promo != NO_TYPE) {
        buf[4] = PROMO_CHARS[m.promo];
        buf[5] = '\0';
    }
}

int move_from_uci(const Position *pos, const char *s, Move *out)
{
    if (s == NULL || out == NULL) return 1;
    MoveList list;
    int n = gen_legal(pos, &list);
    for (int i = 0; i < n; i++) {
        char uci[6];
        move_to_uci(list.moves[i], uci);
        if (strcmp(uci, s) == 0) { *out = list.moves[i]; return 0; }
    }
    return 1;
}
