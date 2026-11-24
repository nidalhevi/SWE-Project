/* test_perft_variants.c — the pass-3 perft variants must count exactly what perft counts.
 * perft itself is checked against tests/perft_suite.epd; here copy-make and the
 * threaded root split are checked against perft, on positions that exercise
 * castling, en passant, promotion and check.
 */
#include "fen.h"
#include "perft.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

static int checks = 0, failures = 0;

#define CHECK(cond, ...)                                              \
    do {                                                              \
        checks++;                                                     \
        if (!(cond)) {                                                \
            failures++;                                               \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);               \
            printf(__VA_ARGS__);                                      \
            printf("\n");                                             \
        }                                                             \
    } while (0)

static const char *const FENS[] = {
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
};

int main(void)
{
    static Position pos;
    for (size_t i = 0; i < sizeof FENS / sizeof FENS[0]; i++) {
        CHECK(fen_parse(&pos, FENS[i]) == FEN_OK, "bad FEN %s", FENS[i]);
        for (int depth = 0; depth <= 3; depth++) {
            uint64_t want = perft(&pos, depth);
            uint64_t copy = perft_copy(&pos, depth);
            CHECK(copy == want, "perft_copy depth %d: %" PRIu64 " != %" PRIu64 "  %s", depth, copy, want, FENS[i]);
            for (int threads = 1; threads <= 8; threads += 3) {
                uint64_t mt = perft_threads(&pos, depth, threads);
                CHECK(mt == want, "perft_threads(%d) depth %d: %" PRIu64 " != %" PRIu64 "  %s",
                      threads, depth, mt, want, FENS[i]);
            }
        }
        CHECK(pos.ply == 0, "the variants leave the position untouched");
    }
    printf("test_perft_variants: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}
