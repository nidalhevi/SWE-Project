/* uci.c — UCI command loop (see uci.h).
 *
 * Time management is one line: spend 1/30 of the remaining clock plus most of
 * the increment, never more than half of what is left. `go` with no limit at
 * all (or `infinite`, which we cannot honour without a second thread) thinks
 * for DEFAULT_MOVETIME_MS.
 */
#include "uci.h"
#include "fen.h"
#include "make.h"
#include "movegen.h"

#include <stdlib.h>
#include <string.h>

#define START_FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
enum { LINE_MAX_LEN = 16384, DEFAULT_MOVETIME_MS = 1000, SAFETY_MS = 30 };

/* Value of the number after `key` in args, or `missing` if key is absent or has no number. */
static long go_value(const char *args, const char *key, long missing)
{
    size_t len = strlen(key);
    for (const char *p = strstr(args, key); p != NULL; p = strstr(p + 1, key)) {
        bool starts_word = p == args || p[-1] == ' ';
        if (!starts_word || p[len] != ' ') continue;
        char *end;
        long v = strtol(p + len, &end, 10);
        return end == p + len || v < 0 ? missing : v;
    }
    return missing;
}

SearchLimits uci_parse_go(const char *args, bool white_to_move)
{
    SearchLimits lim = { 0, 0 };
    long depth = go_value(args, "depth", 0), movetime = go_value(args, "movetime", 0);
    long left = go_value(args, white_to_move ? "wtime" : "btime", 0);
    long inc = go_value(args, white_to_move ? "winc" : "binc", 0);
    long togo = go_value(args, "movestogo", 0);
    if (depth > 0) lim.depth = depth < MAX_SEARCH_DEPTH ? (int)depth : MAX_SEARCH_DEPTH;
    if (movetime > 0) {
        lim.movetime_ms = movetime > SAFETY_MS + 1 ? (int)(movetime - SAFETY_MS) : 1;
    } else if (left > 0) {
        long budget = left / (togo > 0 ? togo + 1 : 30) + inc * 3 / 4;
        if (budget > left / 2) budget = left / 2;
        lim.movetime_ms = budget > 1 ? (int)budget : 1;
    }
    if (lim.depth == 0 && lim.movetime_ms == 0) lim.movetime_ms = DEFAULT_MOVETIME_MS;
    return lim;
}

/* Play the space-separated UCI moves in `moves` on pos. Stops at the first illegal one. */
static void play_moves(Position *pos, char *moves)
{
    for (char *tok = strtok(moves, " "); tok != NULL; tok = strtok(NULL, " ")) {
        Move m;
        if (pos->ply >= MAX_PLY - MAX_SEARCH_DEPTH || move_from_uci(pos, tok, &m) != 0) return;
        make_move(pos, m);
    }
}

/* "position startpos|fen <fen> [moves ...]". A bad FEN leaves the position as it was. */
static void cmd_position(Position *pos, char *args, FILE *out)
{
    static Position next;   /* static: a Position is too big for the stack of a small function */
    char *moves = strstr(args, "moves");
    if (moves != NULL) { *moves = '\0'; moves += strlen("moves"); }
    const char *fen = START_FEN;
    if (strncmp(args, "fen ", 4) == 0) fen = args + 4;
    else if (strncmp(args, "startpos", 8) != 0) return;
    int err = fen_parse(&next, fen);
    if (err != FEN_OK) { fprintf(out, "info string invalid FEN: %s\n", fen_error_string(err)); return; }
    if (moves != NULL) play_moves(&next, moves);
    *pos = next;
}

static void cmd_go(Position *pos, const char *args, FILE *out)
{
    SearchResult r = search_position(pos, uci_parse_go(args, pos->side_to_move == WHITE), out);
    char uci[6] = "0000";   /* the protocol's "no move": the game is already over */
    if (r.has_move) move_to_uci(r.best, uci);
    fprintf(out, "bestmove %s\n", uci);
}

/* Handle one command line. Returns false on "quit". */
static bool uci_command(Position *pos, char *line, FILE *out)
{
    char *args = strchr(line, ' ');
    if (args != NULL) { *args++ = '\0'; while (*args == ' ') args++; }
    else args = line + strlen(line);
    if (strcmp(line, "quit") == 0) return false;
    if (strcmp(line, "uci") == 0) fputs("id name chess-c\nid author SWE-Project team\nuciok\n", out);
    else if (strcmp(line, "isready") == 0) fputs("readyok\n", out);
    else if (strcmp(line, "ucinewgame") == 0) fen_parse(pos, START_FEN);
    else if (strcmp(line, "position") == 0) cmd_position(pos, args, out);
    else if (strcmp(line, "go") == 0) cmd_go(pos, args, out);
    fflush(out);
    return true;
}

int uci_loop(FILE *in, FILE *out)
{
    static Position pos;
    static char line[LINE_MAX_LEN];
    fen_parse(&pos, START_FEN);
    while (fgets(line, sizeof line, in) != NULL) {
        size_t len = strcspn(line, "\r\n");
        bool whole = line[len] != '\0' || feof(in);
        line[len] = '\0';
        if (!whole) {   /* longer than any real command: drop the rest of it and ignore it */
            for (int c = fgetc(in); c != '\n' && c != EOF; c = fgetc(in)) { }
            continue;
        }
        if (!uci_command(&pos, line, out)) break;
    }
    return EXIT_SUCCESS;
}
