/* test_san.c — SAN printing against a python-chess oracle, SAN parsing round
 * trips, and the error codes for bad input. */
#include "board.h"
#include "fen.h"
#include "movegen.h"
#include "san.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

static const struct { const char *fen, *uci, *san; } ORACLE[] = {
#include "san_oracle.inc"
};

/* Every legal move of every oracle position: our SAN must equal
 * python-chess's, and parsing that SAN must give the move back. */
static void test_oracle(void)
{
    for (size_t i = 0; i < sizeof ORACLE / sizeof ORACLE[0]; i++) {
        Position pos;
        int err = fen_parse(&pos, ORACLE[i].fen);
        CHECK(err == FEN_OK, "%s: %s", ORACLE[i].fen, fen_error_string(err));
        if (err != FEN_OK) continue;
        Move m, back;
        CHECK(move_from_uci(&pos, ORACLE[i].uci, &m) == 0, "%s is legal in %s", ORACLE[i].uci, ORACLE[i].fen);
        char san[SAN_MAX_LEN], fen_after[FEN_MAX_LEN];
        move_to_san(&pos, m, san);
        CHECK(strcmp(san, ORACLE[i].san) == 0, "%s in %s: got %s, want %s", ORACLE[i].uci, ORACLE[i].fen, san, ORACLE[i].san);
        fen_write(&pos, fen_after, sizeof fen_after);
        CHECK(strcmp(fen_after, ORACLE[i].fen) == 0, "move_to_san changed the position: %s", fen_after);
        int perr = move_from_san(&pos, ORACLE[i].san, &back);
        CHECK(perr == SAN_OK && memcmp(&back, &m, sizeof m) == 0, "parse %s -> %d", ORACLE[i].san, perr);
    }
}

static void test_parse_errors(void)
{
    static const struct { const char *fen, *san; int want; } T[] = {
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "Nf3", SAN_OK },
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "Nf3+", SAN_OK },      /* wrong suffix tolerated */
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "Ngf3", SAN_OK },      /* over-disambiguated */
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "Nf6", SAN_ERR_ILLEGAL },
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "exd5", SAN_ERR_ILLEGAL },
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "O-O", SAN_ERR_ILLEGAL },
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "", SAN_ERR_SYNTAX },
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e9", SAN_ERR_SYNTAX },
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "Z3", SAN_ERR_SYNTAX },
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e4e5", SAN_ERR_ILLEGAL },   /* reads as an over-disambiguated pawn move e4-e5 */
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "this is far too long to be a move", SAN_ERR_SYNTAX },
        { "5rk1/8/8/8/8/8/8/R4RK1 w - - 0 1", "Rd1", SAN_ERR_AMBIGUOUS },
        { "5rk1/8/8/8/8/8/8/R4RK1 w - - 0 1", "Rad1", SAN_OK },
        { "5rk1/8/8/8/8/8/8/R4RK1 w - - 0 1", "Rfd1", SAN_OK },
        { "4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1", "0-0", SAN_OK },
        { "4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1", "O-O-O+", SAN_OK },
        { "1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a8=Q", SAN_OK },
        { "1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a8Q", SAN_OK },         /* promotion without '=' */
        { "1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1", "axb8=N+", SAN_OK },
        { "1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a8", SAN_ERR_ILLEGAL },  /* promotion piece missing */
        { "1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a8=K", SAN_ERR_SYNTAX },
        { "8/8/8/KPp4r/8/8/8/4k3 w - c6 0 1", "bxc6", SAN_ERR_ILLEGAL }, /* ep exposes the king */
    };
    for (size_t i = 0; i < sizeof T / sizeof T[0]; i++) {
        Position pos;
        if (fen_parse(&pos, T[i].fen) != FEN_OK) { CHECK(false, "bad fen %s", T[i].fen); continue; }
        Move m;
        int got = move_from_san(&pos, T[i].san, &m);
        CHECK(got == T[i].want, "'%s' in %s: got %d, want %d", T[i].san, T[i].fen, got, T[i].want);
    }
    Move m;
    Position pos;
    fen_parse(&pos, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    CHECK(move_from_san(&pos, NULL, &m) == SAN_ERR_SYNTAX, "NULL string");
    CHECK(move_from_san(&pos, "e4", NULL) == SAN_ERR_SYNTAX, "NULL out");
}

int main(void)
{
    test_oracle();
    test_parse_errors();
    printf("test_san: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}
