/* test_movegen.c — hand-picked positions for castling, en passant,
 * promotion, pins and checks, plus make/unmake round trips and small perfts.
 * Every expected count and move list below was cross-checked with python-chess.
 */
#include "board.h"
#include "fen.h"
#include "make.h"
#include "movegen.h"
#include "perft.h"

#include <inttypes.h>
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

/* ------------------------------------------------------------ helpers -- */

static bool parse(Position *pos, const char *fen)
{
    int err = fen_parse(pos, fen);
    CHECK(err == FEN_OK, "'%s': %s", fen, fen_error_string(err));
    return err == FEN_OK;
}

static bool has_move(const MoveList *list, const char *uci)
{
    for (int i = 0; i < list->count; i++) {
        char buf[6];
        move_to_uci(list->moves[i], buf);
        if (strcmp(buf, uci) == 0) return true;
    }
    return false;
}

/* One row of the table below: a position, how many legal moves it has, and
 * space-separated moves that must / must not be in the list. */
typedef struct {
    const char *name, *fen;
    int count;
    const char *present, *absent;
} Case;

static const Case CASES[] = {
    { "start position", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
      20, "e2e4 g1f3 a2a4", "e1g1 e2e5" },
    /* castling */
    { "both castlings available", "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
      26, "e1g1 e1c1", "" },
    { "black both castlings", "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
      26, "e8g8 e8c8", "" },
    { "f1 attacked: no kingside", "r4rk1/8/8/8/8/8/8/R3K2R w KQ - 0 1",
      23, "e1c1", "e1g1" },
    { "b1 attacked: queenside still fine", "1r4k1/8/8/8/8/8/8/R3K2R w KQ - 0 1",
      26, "e1c1 e1g1", "" },
    { "in check: no castling", "4k3/8/8/8/8/8/4r3/R3K2R w KQ - 0 1",
      3, "e1d1 e1f1 e1e2", "e1g1 e1c1" },
    { "rights lost: no castling", "r3k2r/8/8/8/8/8/8/R3K2R w - - 0 1",
      24, "e1f1 e1d1", "e1g1 e1c1" },
    { "piece in the way", "r3k2r/8/8/8/8/8/8/RN2K2R w KQkq - 0 1",
      25, "e1g1", "e1c1" },
    /* en passant */
    { "ep capture available", "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
      31, "e5f6 e5e6", "e5d6" },
    { "ep capture would expose the king along the rank", "8/8/8/KPp4r/8/8/8/4k3 w - c6 0 1",
      4, "b5b6", "b5c6" },
    { "same without the rook: ep is legal", "8/8/8/KPp5/8/8/8/4k3 w - c6 0 1",
      5, "b5c6", "" },
    { "black ep capture", "4k3/8/8/8/3Pp3/8/8/4K3 b - d3 0 1",
      7, "e4d3 e4e3", "" },
    /* pins and checks */
    { "pinned knight cannot move", "4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1",
      4, "e1d1 e1f1 e1d2 e1f2", "e2c3 e2g3 e2d4" },
    { "check: capture or step aside", "4k3/8/8/8/8/8/4r3/4K3 w - - 0 1",
      3, "e1e2 e1d1 e1f1", "e1d2 e1f2" },
    { "pawn attacks restrict the king", "4k3/8/8/8/8/4p3/4P3/4K3 w - - 0 1",
      2, "e1d1 e1f1", "e1d2 e1f2 e2e3 e2e4" },
    /* promotion */
    { "four promotions", "4k3/P7/8/8/8/8/8/4K3 w - - 0 1",
      9, "a7a8q a7a8r a7a8b a7a8n", "a7a8" },
    { "promotion by push or capture", "1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1",
      13, "a7a8q a7b8q a7b8n", "" },
};

static void check_listed_moves(const MoveList *list, const char *moves, bool want, const char *name)
{
    char buf[128];
    snprintf(buf, sizeof buf, "%s", moves);
    for (char *tok = strtok(buf, " "); tok != NULL; tok = strtok(NULL, " "))
        CHECK(has_move(list, tok) == want, "%s: %s should %sbe legal", name, tok, want ? "" : "not ");
}

static void test_cases(void)
{
    for (size_t i = 0; i < sizeof CASES / sizeof CASES[0]; i++) {
        const Case *c = &CASES[i];
        Position pos;
        if (!parse(&pos, c->fen)) continue;
        MoveList list;
        int n = gen_legal(&pos, &list);
        CHECK(n == c->count, "%s: %d legal moves, expected %d", c->name, n, c->count);
        check_listed_moves(&list, c->present, true, c->name);
        check_listed_moves(&list, c->absent, false, c->name);
    }
}

/* make_move followed by unmake_move must give back the identical FEN,
 * for every legal move of every test position, two plies deep. */
static void check_round_trip(Position *pos, int depth)
{
    char before[FEN_MAX_LEN], after[FEN_MAX_LEN];
    fen_write(pos, before, sizeof before);
    MoveList list;
    int n = gen_legal(pos, &list);
    for (int i = 0; i < n; i++) {
        make_move(pos, list.moves[i]);
        CHECK(board_consistent(pos), "inconsistent after make in %s", before);
        if (depth > 1) check_round_trip(pos, depth - 1);
        unmake_move(pos);
        fen_write(pos, after, sizeof after);
        char uci[6];
        move_to_uci(list.moves[i], uci);
        CHECK(strcmp(before, after) == 0, "%s then undo\n   before %s\n   after  %s", uci, before, after);
    }
}

static void test_make_unmake(void)
{
    for (size_t i = 0; i < sizeof CASES / sizeof CASES[0]; i++) {
        Position pos;
        if (parse(&pos, CASES[i].fen)) check_round_trip(&pos, 2);
    }
}

/* Clock, counters and ep square after specific moves. */
static void test_make_details(void)
{
    Position pos;
    Move m;
    char fen[FEN_MAX_LEN];
    if (!parse(&pos, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")) return;

    CHECK(move_from_uci(&pos, "e2e4", &m) == 0 && (m.flags & DOUBLE_PUSH), "e2e4 is a double push");
    make_move(&pos, m);
    fen_write(&pos, fen, sizeof fen);
    CHECK(strcmp(fen, "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1") == 0, "after e2e4: %s", fen);

    CHECK(move_from_uci(&pos, "g8f6", &m) == 0, "g8f6 legal");
    make_move(&pos, m);
    fen_write(&pos, fen, sizeof fen);
    CHECK(strcmp(fen, "rnbqkb1r/pppppppp/5n2/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2") == 0,
          "clock 1, fullmove 2, ep cleared: %s", fen);

    CHECK(move_from_uci(&pos, "e4e5", &m) == 0, "e4e5 legal");
    make_move(&pos, m);
    CHECK(pos.halfmove_clock == 0, "pawn move resets the clock");
    CHECK(move_from_uci(&pos, "e2e4", &m) != 0, "e2e4 is not legal anymore");
    CHECK(move_from_uci(&pos, "zzzz", &m) != 0 && move_from_uci(&pos, "", &m) != 0, "garbage UCI rejected");

    /* Castling moves the rook and drops both rights; capturing a rook drops one. */
    if (!parse(&pos, "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")) return;
    CHECK(in_check(&pos) == false, "not in check");
    CHECK(move_from_uci(&pos, "e1g1", &m) == 0 && (m.flags & CASTLE_K), "e1g1 is kingside castling");
    make_move(&pos, m);
    fen_write(&pos, fen, sizeof fen);
    CHECK(strcmp(fen, "r3k2r/8/8/8/8/8/8/R4RK1 b kq - 1 1") == 0, "after O-O: %s", fen);
    unmake_move(&pos);
    CHECK(move_from_uci(&pos, "a1a8", &m) == 0 && (m.flags & CAPTURE), "a1a8 captures");
    make_move(&pos, m);
    CHECK(pos.castling == (CASTLE_WK | CASTLE_BK), "a1xa8 drops WQ and BQ rights, got %d", pos.castling);
    CHECK(in_check(&pos), "black is in check from the rook on a8");
}

static void test_perft(void)
{
    static const struct { const char *fen; int depth; uint64_t nodes; } P[] = {
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 0, 1 },
        { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 3, 8902 },
        { "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 2, 2039 },
        { "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238 },
        { "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3, 9467 },
        { "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3, 62379 },
    };
    for (size_t i = 0; i < sizeof P / sizeof P[0]; i++) {
        Position pos;
        if (!parse(&pos, P[i].fen)) continue;
        char before[FEN_MAX_LEN], after[FEN_MAX_LEN];
        fen_write(&pos, before, sizeof before);
        uint64_t got = perft(&pos, P[i].depth);
        CHECK(got == P[i].nodes, "perft %d of %s = %" PRIu64 ", expected %" PRIu64,
              P[i].depth, P[i].fen, got, P[i].nodes);
        fen_write(&pos, after, sizeof after);
        CHECK(strcmp(before, after) == 0, "perft must leave the position unchanged");
    }
}

int main(void)
{
    test_cases();
    test_make_unmake();
    test_make_details();
    test_perft();
    printf("test_movegen: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}
