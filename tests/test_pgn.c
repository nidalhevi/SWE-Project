/* test_pgn.c — PGN import/export: a real game with comments, variations and
 * glyphs; write->parse round trips; every error code; buffer safety. */
#include "board.h"
#include "fen.h"
#include "game.h"
#include "make.h"
#include "movegen.h"
#include "pgn.h"

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

static Position pos, back;   /* static: two Positions are 34 KB */
static char pgn[PGN_MAX_LEN];

static bool fen_is(const Position *p, const char *want)
{
    char fen[FEN_MAX_LEN];
    fen_write(p, fen, sizeof fen);
    CHECK(strcmp(fen, want) == 0, "got %s, want %s", fen, want);
    return strcmp(fen, want) == 0;
}

static void play(Position *p, const char *moves)
{
    char buf[512];
    snprintf(buf, sizeof buf, "%s", moves);
    for (char *tok = strtok(buf, " "); tok != NULL; tok = strtok(NULL, " ")) {
        Move m;
        if (move_from_uci(p, tok, &m) != 0) { CHECK(false, "illegal move %s", tok); return; }
        make_move(p, m);
    }
}

static void test_parse_real_game(void)
{
    const char *text =
        "[Event \"Test\"]\n[Site \"?\"]\n[Date \"2026.11.07\"]\n[Round \"?\"]\n"
        "[White \"A \\\"quoted\\\" name\"]\n[Black \"B\"]\n[Result \"1-0\"]\n\n"
        "1. e4 e5 2. Qh5 {Wayward queen} Nc6 3. Bc4 Nf6?? ; a line comment\n"
        "(3... g6 4. Qf3 Nf6 $14 (4... Nd4 {nested (parens) here})) 4. Qxf7# 1-0\n"
        "[Event \"second game, never read\"]\n1. d4 d5";
    int err = pgn_parse(&pos, text);
    CHECK(err == PGN_OK, "parse: %s", pgn_error_string(err));
    if (err != PGN_OK) return;
    CHECK(pos.ply == 7, "7 plies, got %d", pos.ply);
    fen_is(&pos, "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4");
    CHECK(game_state(&pos) == CHECKMATE, "ends in mate");

    /* Move numbers glued to moves, no tags, no result. */
    CHECK(pgn_parse(&pos, "1.e4 e5 2.Nf3 Nc6 3.Bb5") == PGN_OK && pos.ply == 5, "glued move numbers");
    /* Black-to-move start and '...' numbering. */
    CHECK(pgn_parse(&pos, "[FEN \"rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1\"]\n\n1... e5 2. Nf3") == PGN_OK
          && pos.ply == 2, "FEN tag start");
    /* A result token ends the game even if text follows. */
    CHECK(pgn_parse(&pos, "1. e4 1-0 e5 e6 e7") == PGN_OK && pos.ply == 1, "result ends the game");
    /* No moves at all is a legal, empty game. */
    CHECK(pgn_parse(&pos, "") == PGN_OK && pos.ply == 0 && fen_is(&pos, START_FEN), "empty text");
    CHECK(pgn_parse(&pos, "[Event \"x\"]\n\n*") == PGN_OK && pos.ply == 0, "tags only");
}

static void round_trip(const char *start_fen, const char *moves)
{
    if (fen_parse(&pos, start_fen) != FEN_OK) { CHECK(false, "bad start fen %s", start_fen); return; }
    play(&pos, moves);
    char want[FEN_MAX_LEN];
    fen_write(&pos, want, sizeof want);
    pgn_write(&pos, pgn, sizeof pgn);
    fen_parse(&back, START_FEN);
    int err = pgn_parse(&back, pgn);
    CHECK(err == PGN_OK, "re-parse of our own PGN: %s\n%s", pgn_error_string(err), pgn);
    CHECK(back.ply == pos.ply, "ply %d vs %d", back.ply, pos.ply);
    fen_is(&back, want);
    CHECK(pos.ply == 0 || strstr(pgn, "\n\n") != NULL, "blank line between tags and moves");
    for (char *line = pgn; line != NULL; line = strchr(line, '\n'), line = line ? line + 1 : NULL) {
        const char *end = strchr(line, '\n');
        size_t len = end ? (size_t)(end - line) : strlen(line);
        CHECK(len <= 80, "line longer than 80 columns: %.*s", (int)len, line);
    }
}

static void test_round_trips(void)
{
    /* Castling both sides, en passant, promotion with capture, checks. */
    round_trip(START_FEN, "e2e4 d7d5 e4e5 f7f5 e5f6 g8f6 g1f3 b8c6 f1b5 c8d7 e1g1 e7e6 b5c6 d7c6 f3e5 d8d6 d2d4 e8c8 e5f7 d6d7 f7h8 f8d6 c1g5 d6h2 g1h2");
    round_trip("1n2k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7b8q e8e7 b8a8 e7f6 a8g8 f6e5");
    round_trip("4k3/8/8/8/8/8/8/R3K2R b KQ - 0 1", "e8d8 e1c1 d8e8 d1d7");   /* black starts */
    round_trip(START_FEN, "");                                               /* no moves */
    /* The start FEN shows up as a tag only when it is not the standard one. */
    fen_parse(&pos, START_FEN);
    pgn_write(&pos, pgn, sizeof pgn);
    CHECK(strstr(pgn, "[FEN") == NULL && strstr(pgn, "[Result \"*\"]") != NULL, "standard start: no FEN tag\n%s", pgn);
    fen_parse(&pos, "4k3/8/8/8/8/8/8/4KR2 w - - 99 60");
    play(&pos, "f1f2");
    pgn_write(&pos, pgn, sizeof pgn);
    CHECK(strstr(pgn, "[SetUp \"1\"]\n[FEN \"4k3/8/8/8/8/8/8/4KR2 w - - 99 60\"]") != NULL, "SetUp + FEN tags\n%s", pgn);
    CHECK(strstr(pgn, "60. Rf2 1/2-1/2") != NULL, "fifty-move result written\n%s", pgn);

    /* A long game wraps at 80 columns and survives the trip. */
    fen_parse(&pos, START_FEN);
    for (int i = 0; i < 40; i++) play(&pos, "g1f3 g8f6 f3g1 f6g8");
    pgn_write(&pos, pgn, sizeof pgn);
    fen_parse(&back, START_FEN);
    CHECK(pgn_parse(&back, pgn) == PGN_OK && back.ply == 160, "160-ply game round trip");
    CHECK(strstr(pgn, " 1/2-1/2\n") != NULL, "threefold result");
}

static void test_errors(void)
{
    static const struct { const char *text; int want; } T[] = {
        { "1. e4 e5 2. Nf9", PGN_ERR_MOVE },
        { "1. e4 e4", PGN_ERR_MOVE },
        { "1. e4 {never closed", PGN_ERR_UNTERMINATED },
        { "1. e4 (1. d4 (1. c4)", PGN_ERR_UNTERMINATED },
        { "[Event \"x\"", PGN_ERR_TAG },
        { "[Event x]", PGN_ERR_TAG },
        { "[\"x\"]", PGN_ERR_TAG },
        { "1. e4 [Event \"late\"]", PGN_ERR_TAG },
        { "[FEN \"garbage\"]\n1. e4", PGN_ERR_FEN },
        { "[FEN \"garbage\"]", PGN_ERR_FEN },
        { "1. e4 thisisnotamoveatallitisfartoolong", PGN_ERR_MOVE },
        { "1. e4 e5 ) } ] 2. Nf3", PGN_OK },      /* stray closers are ignored */
        { "1. e4 e5 $1 $200 2. Nf3", PGN_OK },
        { "1. e4 e5 ;only a comment", PGN_OK },
    };
    for (size_t i = 0; i < sizeof T / sizeof T[0]; i++) {
        fen_parse(&pos, "4k3/8/8/8/8/8/8/4K3 w - - 0 1");   /* a marker position */
        int got = pgn_parse(&pos, T[i].text);
        CHECK(got == T[i].want, "'%s': got %s, want %s", T[i].text, pgn_error_string(got), pgn_error_string(T[i].want));
        if (T[i].want != PGN_OK) fen_is(&pos, "4k3/8/8/8/8/8/8/4K3 w - - 0 1");   /* untouched on error */
    }
    CHECK(pgn_parse(NULL, "1. e4") == PGN_ERR_NULL && pgn_parse(&pos, NULL) == PGN_ERR_NULL, "NULL");

    /* 1026 plies of knight shuffling: one more than the undo stack holds. */
    static char text[PGN_MAX_LEN];
    size_t len = 0;
    for (int i = 0; i < 1026 / 4 + 1; i++)
        len += (size_t)snprintf(text + len, sizeof text - len, "Nf3 Nf6 Ng1 Ng8 ");
    CHECK(pgn_parse(&pos, text) == PGN_ERR_TOO_LONG, "too long");

    /* pgn_write must respect a tiny buffer. */
    fen_parse(&pos, START_FEN);
    play(&pos, "e2e4 e7e5");
    char small[24];
    memset(small, 'X', sizeof small);
    pgn_write(&pos, small, 20);
    CHECK(strlen(small) == 19 && small[20] == 'X', "truncated to 19 chars + NUL: '%s'", small);
    pgn_write(&pos, small, 0);   /* writes nothing, must not crash */
    pgn_write(&pos, small, 1);
    CHECK(small[0] == '\0', "n == 1 writes just the NUL");
}

int main(void)
{
    test_parse_real_game();
    test_round_trips();
    test_errors();
    printf("test_pgn: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}
