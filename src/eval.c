/* eval.c — material + piece-square tables (see eval.h).
 *
 * The tables are written the way a board is printed: rank 8 on the first
 * line, file a on the left, from White's side. White's square sq therefore
 * reads entry (7 - rank) * 8 + file, and Black reads the vertically mirrored
 * entry rank * 8 + file, which is what makes the evaluation symmetric.
 */
#include "eval.h"

const int PIECE_VALUE[KING + 1] = { 0, 100, 320, 330, 500, 900, 0 };

static const int PST_PAWN[64] = {
      0,   0,   0,   0,   0,   0,   0,   0,
     50,  50,  50,  50,  50,  50,  50,  50,
     10,  10,  20,  30,  30,  20,  10,  10,
      5,   5,  10,  25,  25,  10,   5,   5,
      0,   0,   0,  20,  20,   0,   0,   0,
      5,  -5, -10,   0,   0, -10,  -5,   5,
      5,  10,  10, -20, -20,  10,  10,   5,
      0,   0,   0,   0,   0,   0,   0,   0 };
static const int PST_KNIGHT[64] = {
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   0,   0,   0, -20, -40,
    -30,   0,  10,  15,  15,  10,   0, -30,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -30,   0,  15,  20,  20,  15,   0, -30,
    -30,   5,  10,  15,  15,  10,   5, -30,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50 };
static const int PST_BISHOP[64] = {
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,  10,  10,   5,   0, -10,
    -10,   5,   5,  10,  10,   5,   5, -10,
    -10,   0,  10,  10,  10,  10,   0, -10,
    -10,  10,  10,  10,  10,  10,  10, -10,
    -10,   5,   0,   0,   0,   0,   5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20 };
static const int PST_ROOK[64] = {
      0,   0,   0,   0,   0,   0,   0,   0,
      5,  10,  10,  10,  10,  10,  10,   5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
      0,   0,   0,   5,   5,   0,   0,   0 };
static const int PST_QUEEN[64] = {
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,   5,   5,   5,   0, -10,
     -5,   0,   5,   5,   5,   5,   0,  -5,
      0,   0,   5,   5,   5,   5,   0,  -5,
    -10,   5,   5,   5,   5,   5,   0, -10,
    -10,   0,   5,   0,   0,   0,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20 };
static const int PST_KING_MIDDLE[64] = {
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
     20,  20,   0,   0,   0,   0,  20,  20,
     20,  30,  10,   0,   0,  10,  30,  20 };
static const int PST_KING_END[64] = {
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10,   0,   0, -10, -20, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -30,   0,   0,   0,   0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50 };

static const int *const PST[KING + 1] = {
    [PAWN] = PST_PAWN, [KNIGHT] = PST_KNIGHT, [BISHOP] = PST_BISHOP,
    [ROOK] = PST_ROOK, [QUEEN] = PST_QUEEN, [KING] = PST_KING_MIDDLE,
};

/* Index into a table for a piece of colour c standing on sq. */
static int pst_index(Color c, Square sq)
{
    return c == WHITE ? (7 - sq_rank(sq)) * 8 + sq_file(sq) : sq_rank(sq) * 8 + sq_file(sq);
}

int evaluate(const Position *pos)
{
    int score[2] = { 0, 0 };
    bool queens = false;
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        Piece p = pos->board[sq];
        if (p == EMPTY) continue;
        int type = piece_type(p);
        Color c = piece_color(p);
        if (type == QUEEN) queens = true;
        if (type != KING) score[c] += PIECE_VALUE[type] + PST[type][pst_index(c, sq)];
    }
    /* With the queens off the king stops hiding and walks to the centre. */
    const int *king_table = queens ? PST_KING_MIDDLE : PST_KING_END;
    for (int c = WHITE; c <= BLACK; c++)
        score[c] += king_table[pst_index((Color)c, pos->king_sq[c])];
    int white = score[WHITE] - score[BLACK];
    return pos->side_to_move == WHITE ? white : -white;
}
