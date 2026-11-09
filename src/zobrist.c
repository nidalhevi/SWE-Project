/* zobrist.c — random tables and the from-scratch hash (see zobrist.h). */
#include "zobrist.h"
#include "movegen.h"

uint64_t ZOB_PIECE[PIECE_NB][SQUARE_NB];
uint64_t ZOB_CASTLING[CASTLE_ALL + 1];
uint64_t ZOB_EP_FILE[8];
uint64_t ZOB_SIDE;

/* splitmix64: a tiny, well-known 64-bit generator. Good enough for hashing;
 * it is not meant to be unpredictable, only well spread. */
static uint64_t next_random(uint64_t *state)
{
    uint64_t z = (*state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

void zobrist_init(void)
{
    static bool done = false;
    if (done) return;
    done = true;
    uint64_t state = 0x6368657373ULL;   /* "chess" in ASCII; any constant works */
    for (Piece p = WP; p < PIECE_NB; p++)
        for (Square sq = 0; sq < SQUARE_NB; sq++) ZOB_PIECE[p][sq] = next_random(&state);
    for (int i = 0; i <= CASTLE_ALL; i++) ZOB_CASTLING[i] = next_random(&state);
    for (int f = 0; f < 8; f++) ZOB_EP_FILE[f] = next_random(&state);
    ZOB_SIDE = next_random(&state);
}

uint64_t zobrist_state_key(const Position *pos)
{
    uint64_t key = ZOB_CASTLING[pos->castling];
    if (pos->side_to_move == BLACK) key ^= ZOB_SIDE;
    if (pos->ep_square != NO_SQUARE && has_legal_en_passant(pos))
        key ^= ZOB_EP_FILE[sq_file(pos->ep_square)];
    return key;
}

uint64_t zobrist_hash(const Position *pos)
{
    uint64_t key = zobrist_state_key(pos);
    for (Square sq = 0; sq < SQUARE_NB; sq++) key ^= ZOB_PIECE[pos->board[sq]][sq];
    return key;
}
