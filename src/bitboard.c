/* bitboard.c — attack sets (see bitboard.h).
 *
 * Everything is computed once, by bb_init(), into tables (rungs 2 and 3 of
 * the ladder): one word per square for the leapers, magic-indexed tables for
 * the sliders. To build them, leapers shift the one-bit board of the square; the file masks stop a shift
 * from wrapping round the edge (h-file + 1 would land on the a-file).
 * and sliders walk each ray until they meet an occupied square.
 */
#include "bitboard.h"

Bitboard BB_KNIGHT[SQUARE_NB], BB_KING[SQUARE_NB], BB_PAWN[2][SQUARE_NB];

static Bitboard knight_attacks_slow(Square sq)
{
    Bitboard b = bb_of(sq);
    Bitboard l1 = (b >> 1) & ~BB_FILE_H, l2 = (b >> 2) & ~(BB_FILE_H | (BB_FILE_H >> 1));
    Bitboard r1 = (b << 1) & ~BB_FILE_A, r2 = (b << 2) & ~(BB_FILE_A | (BB_FILE_A << 1));
    Bitboard h1 = l1 | r1, h2 = l2 | r2;   /* one file away, two files away */
    return (h1 << 16) | (h1 >> 16) | (h2 << 8) | (h2 >> 8);
}

static Bitboard king_attacks_slow(Square sq)
{
    Bitboard b = bb_of(sq);
    Bitboard row = b | ((b >> 1) & ~BB_FILE_H) | ((b << 1) & ~BB_FILE_A);
    return (row | (row << 8) | (row >> 8)) & ~b;
}

static Bitboard pawn_attacks_slow(Color c, Square sq)
{
    Bitboard b = bb_of(sq);
    Bitboard sides = ((b >> 1) & ~BB_FILE_H) | ((b << 1) & ~BB_FILE_A);
    return c == WHITE ? sides << 8 : sides >> 8;
}

/* Squares from sq along (df, dr), stopping after the first occupied one.
 * With inner_only the last square before the edge is left out: whether it is
 * occupied never changes the attack set, so the magic masks do not include it. */
static Bitboard ray(Square sq, int df, int dr, Bitboard occ, bool inner_only)
{
    Bitboard out = 0;
    int f = sq_file(sq) + df, r = sq_rank(sq) + dr;
    for (; f >= 0 && f <= 7 && r >= 0 && r <= 7; f += df, r += dr) {
        bool last = f + df < 0 || f + df > 7 || r + dr < 0 || r + dr > 7;
        if (inner_only && last) break;
        Bitboard b = bb_of(make_square(f, r));
        out |= b;
        if (occ & b) break;
    }
    return out;
}

static Bitboard slider_attacks_slow(Square sq, Bitboard occ, bool rook, bool inner_only)
{
    static const int DIRS[2][4][2] = { {{1,1},{-1,1},{-1,-1},{1,-1}}, {{1,0},{0,1},{-1,0},{0,-1}} };
    Bitboard out = 0;
    for (int i = 0; i < 4; i++) out |= ray(sq, DIRS[rook][i][0], DIRS[rook][i][1], occ, inner_only);
    return out;
}

/* ------------------------------------------------------------- magics -- */

static const uint64_t BISHOP_MAGIC[64] = {
    0x0008010804840080ULL, 0x0410020208420000ULL, 0x0010413A00200119ULL, 0x8008086109200404ULL,
    0x0001104042188410ULL, 0x0882021004481000ULL, 0x4C14010806100000ULL, 0x020022840C200600ULL,
    0x0840A11610020084ULL, 0x0044140408821200ULL, 0x400051080081005AULL, 0x1000440401880021ULL,
    0x1800540C20000000ULL, 0x40400A0804A51209ULL, 0x405024138808C800ULL, 0x04000205440C4460ULL,
    0x80C8022008100180ULL, 0x0220000801144082ULL, 0x0142000C08011900ULL, 0x2804028801401200ULL,
    0x04840082020A0104ULL, 0x0061008030021004ULL, 0x484C018100880400ULL, 0x0000418904008400ULL,
    0x08A0060610104208ULL, 0x0202020020082261ULL, 0x9000A40086040400ULL, 0x01400401004300A0ULL,
    0x0000848004002010ULL, 0x100100C042082010ULL, 0x40C404002B420201ULL, 0xA0024640110C0210ULL,
    0x01824841010C9040ULL, 0x0000901002288200ULL, 0x2400110481D00400ULL, 0x0500404800A28200ULL,
    0x0004010010640040ULL, 0x81600401000C9041ULL, 0x0082008100020800ULL, 0x0041010200002200ULL,
    0x8085012060001001ULL, 0x0001080134083000ULL, 0x8082104038011000ULL, 0x2000482011010800ULL,
    0x00400805004C0400ULL, 0x000510100080A442ULL, 0x80080240C2054400ULL, 0xA144040042401210ULL,
    0x01140404540C480BULL, 0x000201A208220006ULL, 0x10C0128400A20840ULL, 0x1000220020884001ULL,
    0x821200208C340000ULL, 0x0080302001070000ULL, 0x0020083001044008ULL, 0x00200400C2094300ULL,
    0x4017160201200809ULL, 0x0000202501101004ULL, 0x000080002C841009ULL, 0x62020C0212840440ULL,
    0x4000210070020203ULL, 0x0008405060A19100ULL, 0x0414200A44011C00ULL, 0x0086020808010044ULL,
};
static const uint64_t ROOK_MAGIC[64] = {
    0x1080022010C00084ULL, 0x0040200010004000ULL, 0x0500081100C12000ULL, 0x4700090084203000ULL,
    0x9200060068210410ULL, 0x0080020014000980ULL, 0x00801A0001005080ULL, 0x0900018021450002ULL,
    0x3000800220400480ULL, 0x2000400042201000ULL, 0x2201001020010940ULL, 0x8000801000800800ULL,
    0x09010008020C1100ULL, 0x0602001012000884ULL, 0x0441002402000100ULL, 0x0140800244802100ULL,
    0x9220608000C00090ULL, 0x0090054000C82000ULL, 0x0001010010406001ULL, 0x4801848018003000ULL,
    0x0404050010080100ULL, 0x0001010006040008ULL, 0x0900040048900621ULL, 0x000102000A81004CULL,
    0x1C0440008004208CULL, 0x1020100340042040ULL, 0x8D02002200348040ULL, 0x0000080080100080ULL,
    0x1084240080080280ULL, 0x14890C0080020080ULL, 0x0081284400223001ULL, 0x0100884600108114ULL,
    0x0002400020800880ULL, 0x0002814000802000ULL, 0x0020806000801004ULL, 0x800A002112004008ULL,
    0x02C2800400800803ULL, 0x0040800400800200ULL, 0x08408A2804000110ULL, 0x040280C582000104ULL,
    0x0080044460044004ULL, 0x6200A01000404001ULL, 0x0101002000450010ULL, 0x408A00C008120020ULL,
    0x0201002800110004ULL, 0x2002008084008002ULL, 0x0813000600110004ULL, 0x0801000040810002ULL,
    0xA001014024800500ULL, 0x02C0A08240090100ULL, 0x0C0A20001106C100ULL, 0x00A8000880100480ULL,
    0x200908020C008080ULL, 0x020200504804C200ULL, 0x01010042000C1100ULL, 0x000580010000D080ULL,
    0x0400209201048042ULL, 0x4A01015080400721ULL, 0x0702091020010045ULL, 0x0888100100082045ULL,
    0x0013001004080023ULL, 0xC022000425081002ULL, 0xC201000200008401ULL, 0xC0000510E4440082ULL,
};

/* Table sizes: the sum over all squares of 2^(mask bits). Fixed, so no heap. */
enum { BISHOP_TABLE_SIZE = 5248, ROOK_TABLE_SIZE = 102400 };
static Bitboard BISHOP_TABLE[BISHOP_TABLE_SIZE], ROOK_TABLE[ROOK_TABLE_SIZE];
BbMagic BB_BISHOP_MAGIC[SQUARE_NB], BB_ROOK_MAGIC[SQUARE_NB];

static int popcount(Bitboard b)
{
    int n = 0;
    for (; b != 0; b &= b - 1) n++;
    return n;
}

/* Fill one piece's tables: for every square, every subset of its mask gets its attack set. */
static void init_magics(BbMagic *magics, const uint64_t *numbers, Bitboard *table, bool rook)
{
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        BbMagic *m = &magics[sq];
        m->mask = slider_attacks_slow(sq, 0, rook, true);
        m->magic = numbers[sq];
        m->shift = 64 - popcount(m->mask);
        m->table = table;
        Bitboard sub = 0;
        do {   /* "carry-rippler": walks through every subset of mask, ending back at 0 */
            table[(sub * m->magic) >> m->shift] = slider_attacks_slow(sq, sub, rook, false);
            sub = (sub - m->mask) & m->mask;
        } while (sub != 0);
        table += 1ULL << popcount(m->mask);
    }
}

void bb_init(void)
{
    static bool done = false;
    if (done) return;
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        BB_KNIGHT[sq] = knight_attacks_slow(sq);
        BB_KING[sq] = king_attacks_slow(sq);
        BB_PAWN[WHITE][sq] = pawn_attacks_slow(WHITE, sq);
        BB_PAWN[BLACK][sq] = pawn_attacks_slow(BLACK, sq);
    }
    init_magics(BB_BISHOP_MAGIC, BISHOP_MAGIC, BISHOP_TABLE, false);
    init_magics(BB_ROOK_MAGIC, ROOK_MAGIC, ROOK_TABLE, true);
    done = true;
}
