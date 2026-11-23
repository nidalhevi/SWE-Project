/* gen_magics.c — find the "magic" multipliers used by src/bitboard.c (pass 3, rung 3).
 *
 * For a rook on sq, only the pieces on its rays (edges excluded) decide where
 * it can go: at most 12 squares, so at most 4096 arrangements. A magic number
 * is a 64-bit constant such that (arrangement * magic) >> (64 - bits) maps
 * every arrangement of that square to its own slot (or to a slot holding the
 * same attack set). There is no formula: we try sparse random numbers until
 * one works, which takes well under a second for all 128.
 * Build and run:  cc -O2 -o /tmp/gen_magics tools/gen_magics.c && /tmp/gen_magics
 * The output is pasted into src/bitboard.c; the engine never searches for magics itself.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint64_t Bitboard;

static uint64_t state = 0x9E3779B97F4A7C15ULL;   /* fixed seed: the same magics every run */
static uint64_t rnd(void)
{
    state ^= state << 13; state ^= state >> 7; state ^= state << 17;
    return state;
}

static Bitboard ray(int sq, int df, int dr, Bitboard occ, int stop_before_edge)
{
    Bitboard out = 0;
    int f = (sq & 7) + df, r = (sq >> 3) + dr;
    for (; f >= 0 && f <= 7 && r >= 0 && r <= 7; f += df, r += dr) {
        int nf = f + df, nr = r + dr;
        if (stop_before_edge && (nf < 0 || nf > 7 || nr < 0 || nr > 7)) break;
        out |= 1ULL << (r * 8 + f);
        if (occ & (1ULL << (r * 8 + f))) break;
    }
    return out;
}

static Bitboard attacks(int sq, Bitboard occ, int rook, int mask_only)
{
    static const int D[2][4][2] = { {{1,1},{-1,1},{-1,-1},{1,-1}}, {{1,0},{0,1},{-1,0},{0,-1}} };
    Bitboard out = 0;
    for (int i = 0; i < 4; i++) out |= ray(sq, D[rook][i][0], D[rook][i][1], occ, mask_only);
    return out;
}

static uint64_t find_magic(int sq, int rook)
{
    static Bitboard occ[4096], att[4096], used[4096];
    Bitboard mask = attacks(sq, 0, rook, 1);
    int bits = __builtin_popcountll(mask), n = 1 << bits, i = 0;
    for (Bitboard sub = 0;; sub = (sub - mask) & mask) {   /* every subset of mask */
        occ[i] = sub; att[i] = attacks(sq, sub, rook, 0); i++;
        if (((sub - mask) & mask) == 0) break;
    }
    for (;;) {
        uint64_t magic = rnd() & rnd() & rnd();   /* few bits set works best */
        memset(used, 0, sizeof used[0] * (size_t)n);
        int ok = 1;
        for (i = 0; i < n && ok; i++) {
            int idx = (int)((occ[i] * magic) >> (64 - bits));
            if (used[idx] == 0) used[idx] = att[i];
            else if (used[idx] != att[i]) ok = 0;
        }
        if (ok) return magic;
    }
}

int main(void)
{
    for (int rook = 0; rook <= 1; rook++) {
        printf("static const uint64_t %s_MAGIC[64] = {\n", rook ? "ROOK" : "BISHOP");
        for (int sq = 0; sq < 64; sq++)
            printf("%s0x%016llXULL,%s", sq % 4 == 0 ? "    " : " ", (unsigned long long)find_magic(sq, rook), sq % 4 == 3 ? "\n" : "");
        printf("};\n");
    }
    return 0;
}
