/* test_game.c — Zobrist hashing and game-over verdicts.
 * Every verdict below was cross-checked with python-chess (is_checkmate,
 * is_stalemate, is_insufficient_material, is_fifty_moves, is_repetition(3)).
 */
#include "board.h"
#include "fen.h"
#include "game.h"
#include "make.h"
#include "movegen.h"
#include "zobrist.h"

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

#define START_FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

static bool parse(Position *pos, const char *fen)
{
    int err = fen_parse(pos, fen);
    CHECK(err == FEN_OK, "'%s': %s", fen, fen_error_string(err));
    return err == FEN_OK;
}

/* Play space-separated UCI moves; returns false (and fails) on an illegal one. */
static bool play(Position *pos, const char *moves)
{
    char buf[256];
    snprintf(buf, sizeof buf, "%s", moves);
    for (char *tok = strtok(buf, " "); tok != NULL; tok = strtok(NULL, " ")) {
        Move m;
        if (move_from_uci(pos, tok, &m) != 0) { CHECK(false, "illegal move %s", tok); return false; }
        make_move(pos, m);
    }
    return true;
}

/* ------------------------------------------------------------ verdicts -- */

static void test_verdicts(void)
{
    static const struct { const char *fen; GameState want; } T[] = {
        { "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3", CHECKMATE },  /* fool's mate */
        { "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", STALEMATE },
        { "4k3/8/8/8/8/8/8/4K3 w - - 0 1", INSUFFICIENT_MATERIAL },      /* K v K */
        { "4k3/8/8/8/8/8/8/4KB2 w - - 0 1", INSUFFICIENT_MATERIAL },     /* KB v K */
        { "4k3/8/8/8/8/8/8/4KN2 w - - 0 1", INSUFFICIENT_MATERIAL },     /* KN v K */
        { "4k3/8/8/8/8/8/8/3NKN2 w - - 0 1", ONGOING },                  /* KNN v K can mate */
        { "4kn2/8/8/8/8/8/8/4KN2 w - - 0 1", ONGOING },                  /* KN v KN: self-mate possible */
        { "2b1k3/8/8/8/8/8/8/4KB2 w - - 0 1", INSUFFICIENT_MATERIAL },   /* bishops on the same colour */
        { "3bk3/8/8/8/8/8/8/4KB2 w - - 0 1", ONGOING },                  /* opposite-coloured bishops */
        { "4k3/8/8/8/8/8/8/4KR2 w - - 0 1", ONGOING },
        { "4k3/8/8/8/8/8/8/4K3 w - - 100 60", INSUFFICIENT_MATERIAL },   /* material beats the clock */
        { "4k3/8/8/8/8/8/8/4KR2 w - - 100 60", FIFTY_MOVES },
        { "4k3/8/8/8/8/8/8/4KR2 w - - 99 60", ONGOING },
        { "7k/5Q2/6K1/8/8/8/8/8 b - - 100 60", STALEMATE },              /* stalemate beats the clock */
    };
    for (size_t i = 0; i < sizeof T / sizeof T[0]; i++) {
        Position pos;
        if (!parse(&pos, T[i].fen)) continue;
        GameState got = game_state(&pos);
        CHECK(got == T[i].want, "%s: got %s, want %s", T[i].fen,
              game_state_string(got), game_state_string(T[i].want));
    }
    Position pos;
    if (parse(&pos, "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"))
        CHECK(strcmp(game_result_string(&pos, CHECKMATE), "0-1") == 0, "white is mated: 0-1");
    if (parse(&pos, "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")) {
        CHECK(strcmp(game_result_string(&pos, STALEMATE), "1/2-1/2") == 0, "stalemate is a draw");
        CHECK(strcmp(game_result_string(&pos, ONGOING), "*") == 0, "ongoing is *");
    }
}

/* ---------------------------------------------------------- repetition -- */

static void test_repetition(void)
{
    Position pos;
    if (!parse(&pos, START_FEN)) return;
    uint64_t start = pos.hash;

    /* Knights out and back: the start position comes round every 4 plies. */
    play(&pos, "g1f3 g8f6 f3g1 f6g8");
    CHECK(pos.hash == start, "same position, same hash");
    CHECK(repetition_count(&pos) == 2, "second occurrence, got %d", repetition_count(&pos));
    CHECK(game_state(&pos) == ONGOING, "twice is not yet a draw");
    play(&pos, "g1f3 g8f6 f3g1");
    CHECK(game_state(&pos) == ONGOING, "ply 7: not a draw");
    play(&pos, "f6g8");
    CHECK(repetition_count(&pos) == 3, "third occurrence");
    CHECK(game_state(&pos) == THREEFOLD_REPETITION, "ply 8: threefold");
    unmake_move(&pos);
    CHECK(game_state(&pos) == ONGOING, "undo takes the draw back");

    /* The ep square alone must not make a position "different" when no
     * en-passant capture is legal: after 1.e4 the position (ep e3) counts as
     * the same as the one reached after 1.e4 Nf6 2.Nf3 Ng8 3.Ng1. */
    if (!parse(&pos, START_FEN)) return;
    play(&pos, "e2e4");
    uint64_t after_e4 = pos.hash;
    play(&pos, "g8f6 g1f3 f6g8 f3g1");
    CHECK(pos.hash == after_e4, "ep square without a legal capture is not hashed");
    CHECK(repetition_count(&pos) == 2, "ply 5: second occurrence");
    play(&pos, "g8f6 g1f3 f6g8 f3g1");
    CHECK(game_state(&pos) == THREEFOLD_REPETITION, "ply 9: threefold");

    /* But when an en-passant capture IS legal, the position is different. */
    if (!parse(&pos, START_FEN)) return;
    play(&pos, "e2e4 d7d5 e4e5 f7f5");
    CHECK(has_legal_en_passant(&pos), "e5xf6 is legal");
    uint64_t with_ep = pos.hash;
    play(&pos, "g1f3 g8h6 f3g1 h6g8");
    CHECK(pos.hash != with_ep, "legal ep chance is part of the hash");
    CHECK(repetition_count(&pos) == 1, "ply 8: first occurrence without the ep chance");
    play(&pos, "g1f3 g8h6 f3g1 h6g8");
    CHECK(repetition_count(&pos) == 2 && game_state(&pos) == ONGOING, "ply 12: only twice");
}

/* ------------------------------------------------------------- hashing -- */

static void test_hash(void)
{
    Position a, b;
    if (!parse(&a, START_FEN) || !parse(&b, START_FEN)) return;
    play(&a, "g1f3 d7d5 b1c3");
    play(&b, "b1c3 d7d5 g1f3");
    CHECK(a.hash == b.hash, "transposition: same position by a different move order");

    if (!parse(&a, START_FEN) || !parse(&b, START_FEN)) return;
    play(&a, "e2e4 e7e5");
    play(&b, "e2e3 e7e6 e3e4 e6e5");
    CHECK(a.hash == b.hash, "same position, different clocks: still equal");
    CHECK(a.hash != b.undo[0].hash, "different positions differ");

    /* Castling rights are part of the key. */
    if (!parse(&a, "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1") ||
        !parse(&b, "r3k2r/8/8/8/8/8/8/R3K2R w - - 0 1")) return;
    CHECK(a.hash != b.hash, "castling rights change the key");
    if (!parse(&a, START_FEN) || !parse(&b, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1")) return;
    CHECK(a.hash != b.hash, "side to move changes the key");
    CHECK(a.hash == zobrist_hash(&a), "incremental hash equals the from-scratch hash");
}

int main(void)
{
    test_verdicts();
    test_repetition();
    test_hash();
    printf("test_game: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}
