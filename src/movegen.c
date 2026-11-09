/* movegen.c — attack detection and move generation on the mailbox board.
 *
 * Directions are (file delta, rank delta) pairs and step() refuses to leave
 * the board, so there is no wrap-around to worry about anywhere. gen_legal()
 * filters the pseudo-legal list by replaying each move on a 64-int scratch
 * copy of the board and asking whether our king is attacked there — far
 * cheaper than copying the whole Position with its undo stack.
 */
#include "movegen.h"
#include "board.h"

#include <assert.h>
#include <string.h>

typedef struct { int df, dr; } Dir;

static const Dir KNIGHT_DIRS[8] = {{1,2},{2,1},{2,-1},{1,-2},{-1,-2},{-2,-1},{-2,1},{-1,2}};
static const Dir KING_DIRS[8]   = {{1,0},{1,1},{0,1},{-1,1},{-1,0},{-1,-1},{0,-1},{1,-1}};
static const Dir BISHOP_DIRS[4] = {{1,1},{-1,1},{-1,-1},{1,-1}};
static const Dir ROOK_DIRS[4]   = {{1,0},{0,1},{-1,0},{0,-1}};

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

/* Does a `by`-coloured piece `a` or `b` sit on the first occupied square
 * along any of the given rays from sq? */
static bool slider_hits(const int board[SQUARE_NB], Square sq, const Dir *dirs, int n,
                        Piece a, Piece b)
{
    for (int i = 0; i < n; i++) {
        Square s = step(sq, dirs[i].df, dirs[i].dr);
        while (s != NO_SQUARE && board[s] == EMPTY) s = step(s, dirs[i].df, dirs[i].dr);
        if (s != NO_SQUARE && (board[s] == a || board[s] == b)) return true;
    }
    return false;
}

static bool leaper_hits(const int board[SQUARE_NB], Square sq, const Dir *dirs, int n, Piece p)
{
    for (int i = 0; i < n; i++) {
        Square s = step(sq, dirs[i].df, dirs[i].dr);
        if (s != NO_SQUARE && board[s] == p) return true;
    }
    return false;
}

/* True iff a piece of colour `by` on `board` attacks sq. */
static bool attacked_on_board(const int board[SQUARE_NB], Square sq, Color by)
{
    /* A `by` pawn attacks sq from one rank behind (relative to its direction). */
    Piece pawn = make_piece(by, PAWN);
    Square l = step(sq, -1, -pawn_dir(by)), r = step(sq, 1, -pawn_dir(by));
    if ((l != NO_SQUARE && board[l] == pawn) || (r != NO_SQUARE && board[r] == pawn)) return true;

    if (leaper_hits(board, sq, KNIGHT_DIRS, 8, make_piece(by, KNIGHT))) return true;
    if (leaper_hits(board, sq, KING_DIRS, 8, make_piece(by, KING))) return true;
    Piece queen = make_piece(by, QUEEN);
    if (slider_hits(board, sq, BISHOP_DIRS, 4, make_piece(by, BISHOP), queen)) return true;
    return slider_hits(board, sq, ROOK_DIRS, 4, make_piece(by, ROOK), queen);
}

bool is_square_attacked(const Position *pos, Square sq, Color by)
{
    assert(sq >= 0 && sq < SQUARE_NB);
    return attacked_on_board(pos->board, sq, by);
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

/* Knights and kings: one step in each direction, onto empty or enemy squares. */
static void gen_leaper(const Position *pos, MoveList *list, Square from, const Dir *dirs, int n)
{
    for (int i = 0; i < n; i++) {
        Square to = step(from, dirs[i].df, dirs[i].dr);
        if (to == NO_SQUARE) continue;
        Piece target = pos->board[to];
        if (target == EMPTY) add_move(list, from, to, NO_TYPE, NORMAL);
        else if (piece_color(target) != pos->side_to_move) add_move(list, from, to, NO_TYPE, CAPTURE);
    }
}

/* Bishops, rooks, queens: slide until something is hit; capture it if enemy. */
static void gen_slider(const Position *pos, MoveList *list, Square from, const Dir *dirs, int n)
{
    for (int i = 0; i < n; i++) {
        for (Square to = step(from, dirs[i].df, dirs[i].dr); to != NO_SQUARE;
             to = step(to, dirs[i].df, dirs[i].dr)) {
            Piece target = pos->board[to];
            if (target == EMPTY) { add_move(list, from, to, NO_TYPE, NORMAL); continue; }
            if (piece_color(target) != pos->side_to_move) add_move(list, from, to, NO_TYPE, CAPTURE);
            break;
        }
    }
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
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        Piece p = pos->board[sq];
        if (p == EMPTY || piece_color(p) != pos->side_to_move) continue;
        switch (piece_type(p)) {
        case PAWN:   gen_pawn(pos, out, sq); break;
        case KNIGHT: gen_leaper(pos, out, sq, KNIGHT_DIRS, 8); break;
        case BISHOP: gen_slider(pos, out, sq, BISHOP_DIRS, 4); break;
        case ROOK:   gen_slider(pos, out, sq, ROOK_DIRS, 4); break;
        case QUEEN:  gen_slider(pos, out, sq, BISHOP_DIRS, 4);
                     gen_slider(pos, out, sq, ROOK_DIRS, 4); break;
        case KING:   gen_leaper(pos, out, sq, KING_DIRS, 8);
                     gen_castling(pos, out); break;
        default:     assert(!"bad piece type");
        }
    }
    return out->count;
}

/* ----------------------------------------------------------- legal moves -- */

/* Replay m on a scratch copy of the board and report whether our king is
 * safe afterwards. Promotion does not matter for king safety, so the pawn
 * is simply moved; castling moves the rook too, for a faithful board. */
static bool leaves_king_safe(const Position *pos, Move m)
{
    int board[SQUARE_NB];
    memcpy(board, pos->board, sizeof board);
    Color us = pos->side_to_move, them = us == WHITE ? BLACK : WHITE;

    if (m.flags & EN_PASSANT) board[m.to - 8 * pawn_dir(us)] = EMPTY;   /* the captured pawn */
    if (m.flags & CASTLE_K) { board[m.to - 1] = board[m.to + 1]; board[m.to + 1] = EMPTY; }
    if (m.flags & CASTLE_Q) { board[m.to + 1] = board[m.to - 2]; board[m.to - 2] = EMPTY; }
    board[m.to] = board[m.from];
    board[m.from] = EMPTY;

    Square king = piece_type(pos->board[m.from]) == KING ? m.to : pos->king_sq[us];
    return !attacked_on_board(board, king, them);
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
