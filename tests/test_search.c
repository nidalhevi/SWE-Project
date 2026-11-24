/* test_search.c — evaluation, search and the UCI loop (pass 3).
 * Searches are shallow on purpose: this runs under ASan + UBSan.
 */
#include "board.h"
#include "eval.h"
#include "fen.h"
#include "game.h"
#include "make.h"
#include "movegen.h"
#include "search.h"
#include "uci.h"

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

static Position pos;   /* static: a Position is large */

/* Search `fen` to `depth`; the best move as UCI text in `uci` ("0000" if none). */
static SearchResult best(const char *fen, int depth, char uci[6])
{
    SearchLimits limits = { depth, 0 };
    int err = fen_parse(&pos, fen);
    CHECK(err == FEN_OK, "'%s': %s", fen, fen_error_string(err));
    SearchResult r = search_position(&pos, limits, NULL);
    strcpy(uci, "0000");
    if (r.has_move) move_to_uci(r.best, uci);
    return r;
}

static int eval_of(const char *fen)
{
    int err = fen_parse(&pos, fen);
    CHECK(err == FEN_OK, "'%s': %s", fen, fen_error_string(err));
    return evaluate(&pos);
}

/* ---------------------------------------------------------- evaluation -- */

static void test_evaluate(void)
{
    CHECK(eval_of(START_FEN) == 0, "the start position is balanced");
    /* The same position with colours swapped and the board flipped scores the same for the mover. */
    CHECK(eval_of("4k3/8/8/8/8/2N5/4P3/4K3 w - - 0 1") == eval_of("4k3/4p3/2n5/8/8/8/8/4K3 b - - 0 1"),
          "evaluation is symmetric");
    CHECK(eval_of("4k3/8/8/8/8/8/8/1N2K3 w - - 0 1") > 250, "a knight up is good for the side to move");
    CHECK(eval_of("4k3/8/8/8/8/8/8/1N2K3 b - - 0 1") < -250, "and bad for the other side");
    CHECK(eval_of("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1") > eval_of("4k3/8/8/8/8/8/8/N3K3 w - - 0 1"),
          "a knight in the centre beats a knight in the corner");
    CHECK(eval_of("8/8/8/3k4/8/8/8/R3K3 b - - 0 1") > eval_of("k7/8/8/8/8/8/8/R3K3 b - - 0 1"),
          "without queens the king belongs in the centre");
}

/* -------------------------------------------------------------- search -- */

static void test_mates(void)
{
    char uci[6];
    SearchResult r = best("6k1/5ppp/8/8/8/8/8/R6K w - - 0 1", 2, uci);
    CHECK(strcmp(uci, "a1a8") == 0 && r.score == MATE_SCORE - 1, "back-rank mate in 1, got %s %d", uci, r.score);
    r = best("r6k/8/8/8/8/8/5PPP/6K1 b - - 0 1", 2, uci);
    CHECK(strcmp(uci, "a8a1") == 0 && r.score == MATE_SCORE - 1, "the same for Black, got %s %d", uci, r.score);
    r = best("7k/8/8/8/8/8/R7/1R5K w - - 0 1", 3, uci);
    CHECK(r.score == MATE_SCORE - 3, "two-rook ladder is mate in 2 (3 plies), got %s %d", uci, r.score);
    CHECK(score_is_mate(r.score) && !score_is_mate(900), "score_is_mate");
    /* Qg6 would be stalemate (a draw); Qg7 is mate. */
    r = best("7k/8/5K2/6Q1/8/8/8/8 w - - 0 1", 2, uci);
    make_move(&pos, r.best);
    CHECK(game_state(&pos) == CHECKMATE, "mates instead of stalemating, played %s", uci);
    r = best("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3", 3, uci);
    CHECK(!r.has_move, "no move in a checkmated position");
}

static void test_tactics(void)
{
    char uci[6];
    best("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1", 2, uci);
    CHECK(strcmp(uci, "d1d5") == 0, "takes the hanging queen, got %s", uci);
    /* Quiescence: at depth 1 Qxd5 looks like a free pawn; the recapture cxd5 is one ply further. */
    best("4k3/8/2p5/3p4/8/8/8/3QK3 w - - 0 1", 1, uci);
    CHECK(strcmp(uci, "d1d5") != 0, "does not trade the queen for a defended pawn");
    best("4k3/8/8/8/8/2n5/1P6/4K3 w - - 0 1", 1, uci);
    CHECK(strcmp(uci, "b2c3") == 0, "captures with the pawn, got %s", uci);
    /* Three plies deep: Nc7+ forks king and rook, then the knight takes the rook. The pawn matters:
     * without it the line ends in K+N v K, which the search correctly scores as a draw (0). */
    SearchResult r = best("r3k3/8/8/1N6/8/8/4P3/4K3 w - - 0 1", 3, uci);
    CHECK(strcmp(uci, "b5c7") == 0 && r.score > 200, "finds the knight fork, got %s %d", uci, r.score);
    r = best("r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1", 3, uci);
    CHECK(r.score == 0, "winning the rook into K+N v K is only a draw, got %d", r.score);
}

static void test_search_is_clean(void)
{
    char before[FEN_MAX_LEN], after[FEN_MAX_LEN], uci[6];
    fen_parse(&pos, "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1");
    fen_write(&pos, before, sizeof before);
    uint64_t hash = pos.hash;
    SearchLimits limits = { 3, 0 };
    SearchResult r = search_position(&pos, limits, NULL);
    fen_write(&pos, after, sizeof after);
    CHECK(strcmp(before, after) == 0 && pos.hash == hash && pos.ply == 0, "search leaves the position untouched");
    CHECK(r.has_move && r.depth == 3 && r.nodes > 0, "search reports depth and nodes");
    Move m;
    move_to_uci(r.best, uci);
    CHECK(move_from_uci(&pos, uci, &m) == 0, "the best move is legal: %s", uci);

    SearchLimits timed = { 0, 150 };   /* a time limit alone must come back with a move */
    r = search_position(&pos, timed, NULL);
    CHECK(r.has_move && r.depth >= 1, "a timed search returns a move (depth %d)", r.depth);
}

/* ----------------------------------------------------------------- UCI -- */

static void test_parse_go(void)
{
    SearchLimits l = uci_parse_go("depth 5", true);
    CHECK(l.depth == 5 && l.movetime_ms == 0, "go depth 5");
    l = uci_parse_go("movetime 1000", true);
    CHECK(l.depth == 0 && l.movetime_ms == 970, "go movetime keeps a safety margin, got %d", l.movetime_ms);
    l = uci_parse_go("wtime 60000 btime 30000 winc 1000 binc 0", true);
    CHECK(l.movetime_ms == 2750, "white: 60000/30 + 3/4 of the increment, got %d", l.movetime_ms);
    l = uci_parse_go("wtime 60000 btime 30000 winc 1000 binc 0", false);
    CHECK(l.movetime_ms == 1000, "black reads its own clock, got %d", l.movetime_ms);
    l = uci_parse_go("wtime 100 btime 100", true);
    CHECK(l.movetime_ms == 3, "almost no time left: still a positive budget, got %d", l.movetime_ms);
    l = uci_parse_go("wtime 1000 winc 5000", true);
    CHECK(l.movetime_ms == 500, "never more than half the clock, got %d", l.movetime_ms);
    l = uci_parse_go("", true);
    CHECK(l.depth == 0 && l.movetime_ms == 1000, "bare go gets the default time");
    l = uci_parse_go("infinite", true);
    CHECK(l.movetime_ms == 1000, "go infinite gets the default time");
    l = uci_parse_go("depth 999", true);
    CHECK(l.depth == MAX_SEARCH_DEPTH, "depth is capped");
    l = uci_parse_go("depth x movetime -5 wtime", true);
    CHECK(l.depth == 0 && l.movetime_ms == 1000, "garbage numbers fall back to the default");
}

/* Run the UCI loop over `script`; the whole answer is returned in a static buffer. */
static const char *run_uci(const char *script)
{
    static char answer[8192];
    FILE *in = tmpfile(), *out = tmpfile();
    if (in == NULL || out == NULL) { CHECK(false, "tmpfile failed"); return ""; }
    fputs(script, in);
    rewind(in);
    uci_loop(in, out);
    rewind(out);
    size_t n = fread(answer, 1, sizeof answer - 1, out);
    answer[n] = '\0';
    fclose(in);
    fclose(out);
    return answer;
}

static void test_uci_loop(void)
{
    const char *a = run_uci("uci\nisready\nposition fen 6k1/5ppp/8/8/8/8/8/R6K w - - 0 1\ngo depth 2\nquit\n");
    CHECK(strstr(a, "uciok") && strstr(a, "readyok"), "handshake");
    CHECK(strstr(a, "info depth 1 score mate 1") != NULL, "info line announces the mate");
    CHECK(strstr(a, "bestmove a1a8\n") != NULL, "bestmove for the mate in 1: %s", a);

    a = run_uci("position startpos moves e2e4 e7e5 g1f3\ngo depth 1\n");
    CHECK(strstr(a, "bestmove ") != NULL && strstr(a, "bestmove 0000") == NULL, "plays after a move list, no quit needed");
    a = run_uci("position startpos moves f2f3 e7e5 g2g4 d8h4\ngo depth 2\nquit\n");
    CHECK(strstr(a, "bestmove 0000") != NULL, "a finished game answers bestmove 0000");

    /* Nonsense must be ignored, a bad FEN must keep the old position, an illegal move stops the list. */
    a = run_uci("hello\n\nposition fen garbage\nposition\nposition startpos moves e2e5\ngo depth 1\ngo depth\n\x01\xff\nquit\n");
    CHECK(strstr(a, "info string invalid FEN") != NULL, "bad FEN is reported, not fatal");
    CHECK(strstr(a, "bestmove ") != NULL, "still answers after nonsense");

    static char script[40000];
    memset(script, 'x', 30000);   /* one line far longer than the buffer */
    strcpy(script + 30000, "\nisready\nquit\n");
    a = run_uci(script);
    CHECK(strcmp(a, "readyok\n") == 0, "an overlong line is dropped whole, got '%s'", a);
}

int main(void)
{
    test_evaluate();
    test_mates();
    test_tactics();
    test_search_is_clean();
    test_parse_go();
    test_uci_loop();
    printf("test_search: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}
