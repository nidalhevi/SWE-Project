/* cli.c — command-line entry point (SPEC.md §CLI).
 *
 *   chess perft <depth> [fen]            node count
 *   chess divide <depth> [fen]           "<uci> <nodes>" per root move, then "total <n>"
 *   chess moves [fen]                    legal moves, UCI, sorted, one per line
 *   chess perft-suite <file> <maxdepth>  PASS/FAIL per EPD line, exit 1 on any FAIL
 *   chess status [fen]                   ongoing | checkmate | stalemate | ... (pass 2)
 *   chess play [fen]                     two-player terminal game with undo (pass 2)
 *   chess pgn <file>                     replay a PGN file; print the final FEN and status (pass 2)
 *   chess batch                          line protocol on stdin for tools (see play.h) (pass 2)
 *   chess perft-copy <depth> [fen]       perft by copy-make instead of make/unmake (pass 3, docs/perf.md)
 *   chess perft-mt <threads> <depth> [fen]  perft with the root moves split over threads (pass 3)
 *   chess uci                            UCI protocol on stdin for chess GUIs (pass 3)
 *   chess search <depth> [fen]           best move at that depth: "bestmove <uci> score <cp> nodes <n>" (pass 3)
 *
 * Exit codes: 0 ok · 1 a test failed · 2 invalid FEN or argument · 3 not implemented.
 * A FEN may be one quoted argument or its six fields as separate arguments.
 */
#include "board.h"
#include "fen.h"
#include "movegen.h"
#include "perft.h"
#include "pgn.h"
#include "play.h"
#include "search.h"
#include "uci.h"
#include "game.h"

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define START_FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

static const char USAGE[] =
    "usage: chess perft <depth> [fen]\n"
    "       chess divide <depth> [fen]\n"
    "       chess moves [fen]\n"
    "       chess perft-suite <file> <maxdepth>\n"
    "       chess status [fen]\n"
    "       chess play [fen]\n"
    "       chess pgn <file>\n"
    "       chess batch\n"
    "       chess perft-copy <depth> [fen]\n"
    "       chess perft-mt <threads> <depth> [fen]\n"
    "       chess uci\n"
    "       chess search <depth> [fen]\n"
    "A FEN may be quoted as one argument or given as six separate arguments.\n";

/* Print a message and exit with EXIT_INVALID_INPUT. Never returns. */
static _Noreturn void fail(const char *fmt, const char *detail)
{
    fprintf(stderr, "chess: ");
    fprintf(stderr, fmt, detail);
    fputc('\n', stderr);
    exit(EXIT_INVALID_INPUT);
}

/* Strict decimal in [0, MAX_PLY). Anything else is a usage error. */
static int parse_depth(const char *s)
{
    char *end;
    errno = 0;
    long v = strtol(s, &end, 10);
    if (errno != 0 || end == s || *end != '\0' || v < 0 || v >= MAX_PLY)
        fail("depth must be a whole number between 0 and 1023, got '%s'", s);
    return (int)v;
}

/* Join argv[first..argc) with single spaces into buf (a FEN typed without
 * quotes arrives as six arguments). Too long -> usage error. */
static void join_args(int argc, char **argv, int first, char *buf, size_t n)
{
    size_t used = 0;
    buf[0] = '\0';
    for (int i = first; i < argc; i++) {
        size_t len = strlen(argv[i]);
        if (used + len + 2 > n) fail("FEN argument is too long (max %s characters)", "255");
        if (i > first) buf[used++] = ' ';
        memcpy(buf + used, argv[i], len + 1);
        used += len;
    }
}

/* Load the FEN given from argv[first] on, or the start position if none. */
static void load_position(Position *pos, int argc, char **argv, int first)
{
    char fen[256];
    if (first >= argc) strcpy(fen, START_FEN);
    else join_args(argc, argv, first, fen, sizeof fen);

    int err = fen_parse(pos, fen);
    if (err != FEN_OK) {
        fprintf(stderr, "chess: invalid FEN '%s'\n", fen);
        fail("  %s", fen_error_string(err));
    }
}

static int cmd_perft(int argc, char **argv)
{
    if (argc < 3) fail("perft needs a depth%s", "");
    int depth = parse_depth(argv[2]);
    Position pos;
    load_position(&pos, argc, argv, 3);
    printf("%" PRIu64 "\n", perft(&pos, depth));
    return EXIT_SUCCESS;
}

static int cmd_perft_copy(int argc, char **argv)
{
    if (argc < 3) fail("perft-copy needs a depth%s", "");
    int depth = parse_depth(argv[2]);
    if (depth >= MAX_SEARCH_DEPTH) fail("perft-copy needs a depth below 64, got '%s'", argv[2]);
    static Position pos;
    load_position(&pos, argc, argv, 3);
    printf("%" PRIu64 "\n", perft_copy(&pos, depth));
    return EXIT_SUCCESS;
}

static int cmd_perft_mt(int argc, char **argv)
{
    if (argc < 4) fail("perft-mt needs <threads> <depth>%s", "");
    int threads = parse_depth(argv[2]), depth = parse_depth(argv[3]);
    if (threads < 1 || threads > PERFT_MAX_THREADS) fail("threads must be between 1 and 64, got '%s'", argv[2]);
    static Position pos;
    load_position(&pos, argc, argv, 4);
    printf("%" PRIu64 "\n", perft_threads(&pos, depth, threads));
    return EXIT_SUCCESS;
}

static int cmd_divide(int argc, char **argv)
{
    if (argc < 3) fail("divide needs a depth%s", "");
    int depth = parse_depth(argv[2]);
    if (depth < 1) fail("divide needs a depth of at least 1%s", "");
    Position pos;
    load_position(&pos, argc, argv, 3);
    perft_divide(&pos, depth);
    return EXIT_SUCCESS;
}

static int compare_uci(const void *a, const void *b)
{
    return strcmp((const char *)a, (const char *)b);
}

static int cmd_moves(int argc, char **argv)
{
    Position pos;
    load_position(&pos, argc, argv, 2);
    MoveList list;
    int n = gen_legal(&pos, &list);

    char uci[MAX_MOVES][6];
    for (int i = 0; i < n; i++) move_to_uci(list.moves[i], uci[i]);
    qsort(uci, (size_t)n, sizeof uci[0], compare_uci);
    for (int i = 0; i < n; i++) puts(uci[i]);
    return EXIT_SUCCESS;
}

/* One EPD line: "<fen> ;D1 <n> ;D2 <n> ...". Runs every Dk with k <= maxdepth.
 * Returns the number of failed depths; exits 2 if the line is malformed. */
static int run_suite_line(char *line, int maxdepth, int lineno)
{
    char *semi = strchr(line, ';');
    if (semi == NULL) fail("perft_suite line %s has no ;D entries", line);
    *semi = '\0';

    Position pos;
    int err = fen_parse(&pos, line);
    if (err != FEN_OK) {
        fprintf(stderr, "chess: line %d: %s\n", lineno, fen_error_string(err));
        fail("invalid FEN in suite: %s", line);
    }

    int failures = 0;
    for (char *p = semi + 1; p != NULL; p = strchr(p, ';'), p = p ? p + 1 : NULL) {
        int depth;
        unsigned long long want;
        if (sscanf(p, " D%d %llu", &depth, &want) != 2)
            fail("malformed ;D entry on suite line '%s'", line);
        if (depth > maxdepth) continue;
        uint64_t got = perft(&pos, depth);
        bool ok = got == (uint64_t)want;
        printf("%s D%d %" PRIu64 "%s  %s\n", ok ? "PASS" : "FAIL", depth, got,
               ok ? "" : " (expected differs)", line);
        if (!ok) failures++;
    }
    return failures;
}

static int cmd_perft_suite(int argc, char **argv)
{
    if (argc != 4) fail("perft-suite needs <file> <maxdepth>%s", "");
    int maxdepth = parse_depth(argv[3]);
    FILE *f = fopen(argv[2], "r");
    if (f == NULL) fail("cannot open suite file '%s'", argv[2]);

    char line[1024];
    int lineno = 0, failures = 0, positions = 0;
    while (fgets(line, sizeof line, f) != NULL) {
        lineno++;
        line[strcspn(line, "\r\n")] = '\0';
        if (line[0] == '\0' || line[0] == '#') continue;
        failures += run_suite_line(line, maxdepth, lineno);
        positions++;
    }
    fclose(f);
    printf("perft-suite: %d positions up to depth %d, %d failure(s)\n",
           positions, maxdepth, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}

static int cmd_status(int argc, char **argv)
{
    Position pos;
    load_position(&pos, argc, argv, 2);
    puts(game_state_string(game_state(&pos)));
    return EXIT_SUCCESS;
}

static int cmd_play(int argc, char **argv)
{
    static Position pos;   /* static: keeps 17 KB off the stack */
    load_position(&pos, argc, argv, 2);
    play_loop(&pos, stdin, stdout);
    return EXIT_SUCCESS;
}

/* Read a whole file into a fixed buffer; a file that does not fit is a usage error. */
static void read_file(const char *path, char *buf, size_t n)
{
    FILE *f = fopen(path, "r");
    if (f == NULL) fail("cannot open PGN file '%s'", path);
    size_t len = fread(buf, 1, n - 1, f);
    bool too_long = fgetc(f) != EOF;
    fclose(f);
    buf[len] = '\0';
    if (too_long) fail("PGN file '%s' is too long", path);
}

static int cmd_pgn(int argc, char **argv)
{
    if (argc != 3) fail("pgn needs a file%s", "");
    static char text[PGN_MAX_LEN];
    static Position pos;
    read_file(argv[2], text, sizeof text);
    int err = pgn_parse(&pos, text);
    if (err != PGN_OK) fail("invalid PGN: %s", pgn_error_string(err));
    char fen[FEN_MAX_LEN];
    fen_write(&pos, fen, sizeof fen);
    printf("%s\n%s\n", fen, game_state_string(game_state(&pos)));
    return EXIT_SUCCESS;
}

static int cmd_search(int argc, char **argv)
{
    if (argc < 3) fail("search needs a depth%s", "");
    int depth = parse_depth(argv[2]);
    if (depth < 1 || depth > MAX_SEARCH_DEPTH) fail("search needs a depth between 1 and 64, got '%s'", argv[2]);
    static Position pos;
    load_position(&pos, argc, argv, 3);
    SearchLimits limits = { depth, 0 };
    SearchResult r = search_position(&pos, limits, NULL);
    char uci[6] = "0000";
    if (r.has_move) move_to_uci(r.best, uci);
    printf("bestmove %s score %d nodes %" PRIu64 "\n", uci, r.score, r.nodes);
    return EXIT_SUCCESS;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fputs(USAGE, stderr);
        return EXIT_INVALID_INPUT;
    }
    const char *cmd = argv[1];
    if (strcmp(cmd, "perft") == 0)       return cmd_perft(argc, argv);
    if (strcmp(cmd, "perft-copy") == 0)  return cmd_perft_copy(argc, argv);
    if (strcmp(cmd, "perft-mt") == 0)    return cmd_perft_mt(argc, argv);
    if (strcmp(cmd, "divide") == 0)      return cmd_divide(argc, argv);
    if (strcmp(cmd, "moves") == 0)       return cmd_moves(argc, argv);
    if (strcmp(cmd, "perft-suite") == 0) return cmd_perft_suite(argc, argv);
    if (strcmp(cmd, "status") == 0)      return cmd_status(argc, argv);
    if (strcmp(cmd, "play") == 0)        return cmd_play(argc, argv);
    if (strcmp(cmd, "pgn") == 0)         return cmd_pgn(argc, argv);
    if (strcmp(cmd, "batch") == 0)       return batch_loop(stdin, stdout);
    if (strcmp(cmd, "uci") == 0)         return uci_loop(stdin, stdout);
    if (strcmp(cmd, "search") == 0)      return cmd_search(argc, argv);
    fputs(USAGE, stderr);
    fail("unknown subcommand '%s'", cmd);
}
