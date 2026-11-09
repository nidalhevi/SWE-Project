/* game.c — game-over detection (see game.h). */
#include "game.h"
#include "movegen.h"

#include <assert.h>

/* Count the pieces of one colour, by type, and remember what the bishops stand on. */
typedef struct { int count[KING + 1], total, bishops_on_light, bishops_on_dark; } Material;

static Material count_material(const Position *pos, Color c)
{
    Material m = { {0}, 0, 0, 0 };
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        Piece p = pos->board[sq];
        if (p == EMPTY || piece_color(p) != c) continue;
        m.count[piece_type(p)]++;
        m.total++;
        if (piece_type(p) == BISHOP) {
            bool light = (sq_file(sq) + sq_rank(sq)) % 2 == 1;
            if (light) m.bishops_on_light++; else m.bishops_on_dark++;
        }
    }
    return m;
}

/* python-chess's has_insufficient_material(color): can `c` still mate, even
 * with the opponent's cooperation? Pawns, rooks and queens always can. A lone
 * knight can only mate if the opponent has something to block its own king
 * with (anything but a queen). Bishops can only mate if the opponent has
 * pawns or knights or a bishop on the other colour. */
static bool side_insufficient(const Material *us, const Material *them)
{
    if (us->count[PAWN] || us->count[ROOK] || us->count[QUEEN]) return false;
    if (us->count[KNIGHT])
        return us->total <= 2 && them->total - them->count[KING] - them->count[QUEEN] == 0;
    if (us->count[BISHOP]) {
        bool all_same_colour = (us->bishops_on_light + them->bishops_on_light == 0) ||
                               (us->bishops_on_dark + them->bishops_on_dark == 0);
        return all_same_colour && us->count[PAWN] + them->count[PAWN] == 0 &&
               us->count[KNIGHT] + them->count[KNIGHT] == 0;
    }
    return true;   /* a bare king */
}

bool insufficient_material(const Position *pos)
{
    Material w = count_material(pos, WHITE), b = count_material(pos, BLACK);
    return side_insufficient(&w, &b) && side_insufficient(&b, &w);
}

int repetition_count(const Position *pos)
{
    /* Only the plies since the last pawn move or capture can hold the same
     * position: those moves are irreversible. Castling-right changes are
     * irreversible too, but they change the hash, so they fall out by themselves. */
    int back = pos->halfmove_clock < pos->ply ? pos->halfmove_clock : pos->ply;
    int count = 1;
    for (int i = 1; i <= back; i++)
        if (pos->undo[pos->ply - i].hash == pos->hash) count++;
    return count;
}

GameState game_state(const Position *pos)
{
    MoveList list;
    int n = gen_legal(pos, &list);
    if (n == 0) return in_check(pos) ? CHECKMATE : STALEMATE;
    if (insufficient_material(pos)) return INSUFFICIENT_MATERIAL;
    if (pos->halfmove_clock >= 100) return FIFTY_MOVES;
    if (repetition_count(pos) >= 3) return THREEFOLD_REPETITION;
    return ONGOING;
}

const char *game_state_string(GameState s)
{
    static const char *const text[GAME_STATE_NB] = {
        [ONGOING] = "ongoing", [CHECKMATE] = "checkmate", [STALEMATE] = "stalemate",
        [INSUFFICIENT_MATERIAL] = "insufficient-material", [FIFTY_MOVES] = "fifty-moves",
        [THREEFOLD_REPETITION] = "threefold-repetition",
    };
    assert(s >= 0 && s < GAME_STATE_NB);
    return text[s];
}

const char *game_result_string(const Position *pos, GameState s)
{
    if (s == ONGOING) return "*";
    if (s != CHECKMATE) return "1/2-1/2";
    return pos->side_to_move == WHITE ? "0-1" : "1-0";   /* the side to move got mated */
}
