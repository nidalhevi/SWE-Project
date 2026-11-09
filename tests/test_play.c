/* test_play.c — the terminal loop and the batch protocol driven from memory
 * buffers (fmemopen), so the whole user-facing path runs under the sanitizers. */
#include "fen.h"
#include "play.h"

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

static char output[65536];

/* Feed `script` to the loop and capture what it prints. */
static void run_play(const char *fen, const char *script)
{
    static Position pos;
    fen_parse(&pos, fen);
    FILE *in = fmemopen((void *)script, strlen(script), "r");
    FILE *out = fmemopen(output, sizeof output - 1, "w");
    play_loop(&pos, in, out);
    fclose(in);
    fclose(out);   /* flushes and NUL-terminates */
}

static void run_batch(const char *script)
{
    FILE *in = fmemopen((void *)script, strlen(script), "r");
    FILE *out = fmemopen(output, sizeof output - 1, "w");
    batch_loop(in, out);
    fclose(in);
    fclose(out);
}

static void test_play(void)
{
    run_play("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
             "e4\ne5\nQh5\nNc6\nBc4\nNf6\nQxf7#\ne5\nundo\ng1f3\nnonsense\nmoves\nfen\npgn\nhelp\nquit\nnever read\n");
    CHECK(strstr(output, "Game over: checkmate (1-0)") != NULL, "mate announced\n%s", output);
    CHECK(strstr(output, "The game is over: undo or quit.") != NULL, "no moves after mate");
    CHECK(strstr(output, "'nonsense' is not a legal move") != NULL, "bad input rejected");
    CHECK(strstr(output, "White to move (in check)") == NULL && strstr(output, "Black to move\n") != NULL, "side-to-move line");
    CHECK(strstr(output, "4. Nf3") != NULL && strstr(output, "[Result \"*\"]") != NULL, "pgn command\n%s", output);
    CHECK(strstr(output, "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/5N2/PPPP1PPP/RNB1K2R b KQkq - 5 4") != NULL, "fen command\n%s", output);
    CHECK(strstr(output, "never read") == NULL, "quit stops reading");

    run_play("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "undo\n");
    CHECK(strstr(output, "Nothing to undo.") != NULL, "undo at the start");
    run_play("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "\n");   /* fmemopen rejects an empty buffer */
    CHECK(strstr(output, "Game over: stalemate (1/2-1/2)") != NULL, "stalemate start, EOF ends the loop");
    run_play("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", "e4\n");
    CHECK(strstr(output, "The game is over: undo or quit.") != NULL, "no moves in a finished position");
}

static void test_batch(void)
{
    run_batch("position 7k/5Q2/6K1/8/8/8/8/8 b - - 0 1\nstatus\nmoves\nmove a1a2\nundo\n"
              "position rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1\nsan e2e4\nmove e2e4\nfen\n"
              "san\nmove\nposition\nwhat\n\nquit\nstatus\n");
    const char *want =
        "ok\nstalemate\n\nerror illegal move\nerror nothing to undo\nok\ne4\nok\n"
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1\n"
        "error illegal move\nerror illegal move\nerror expected 6 fields: placement side castling ep halfmove fullmove\n"
        "error unknown command 'what'\nerror unknown command ''\n";
    CHECK(strcmp(output, want) == 0, "batch transcript differs:\n%s", output);
}

int main(void)
{
    test_play();
    test_batch();
    printf("test_play: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}
