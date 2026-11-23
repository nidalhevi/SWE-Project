/* play.c — terminal play and the batch protocol (see play.h). */
#include "play.h"
#include "board.h"
#include "fen.h"
#include "game.h"
#include "make.h"
#include "movegen.h"
#include "pgn.h"
#include "san.h"
#include "search.h"

#include <stdlib.h>
#include <string.h>

#define START_FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
enum { ENGINE_MOVETIME_MS = 1000 };

/* Read one line without its newline; false at end of input. */
static bool read_line(FILE *in, char *buf, size_t n)
{
    if (fgets(buf, (int)n, in) == NULL) return false;
    buf[strcspn(buf, "\r\n")] = '\0';
    return true;
}

static int compare_strings(const void *a, const void *b) { return strcmp((const char *)a, (const char *)b); }

/* Print the legal moves in UCI, sorted, separated by sep. */
static void print_moves(const Position *pos, FILE *out, const char *sep)
{
    MoveList list;
    int n = gen_legal(pos, &list);
    char uci[MAX_MOVES][6];
    for (int i = 0; i < n; i++) move_to_uci(list.moves[i], uci[i]);
    qsort(uci, (size_t)n, sizeof uci[0], compare_strings);
    for (int i = 0; i < n; i++) fprintf(out, "%s%s", i ? sep : "", uci[i]);
    fputc('\n', out);
}

/* A move typed by a human: SAN first ("Nf3"), then UCI ("g1f3"). */
static bool parse_human_move(const Position *pos, const char *s, Move *m)
{
    return move_from_san(pos, s, m) == SAN_OK || move_from_uci(pos, s, m) == 0;
}

/* ----------------------------------------------------------------- play -- */

static void show(const Position *pos, FILE *out)
{
    board_print(pos, out);
    GameState state = game_state(pos);
    if (state != ONGOING)
        fprintf(out, "Game over: %s (%s)\n", game_state_string(state), game_result_string(pos, state));
    else
        fprintf(out, "%s to move%s\n", pos->side_to_move == WHITE ? "White" : "Black",
                in_check(pos) ? " (in check)" : "");
}

static void play_help(FILE *out)
{
    fputs("Type a move as SAN (Nf3, exd5, O-O, e8=Q) or UCI (g1f3, e7e8q).\n"
          "Commands: go (the engine plays this move)  moves  undo  fen  pgn  help  quit\n", out);
}

/* "go": let the engine choose and play the move for the side to move (one second of thought). */
static void engine_move(Position *pos, FILE *out)
{
    if (game_state(pos) != ONGOING || pos->ply >= MAX_PLY - MAX_SEARCH_DEPTH) {
        fputs("The game is over: undo or quit.\n", out);
        return;
    }
    SearchLimits limits = { 0, ENGINE_MOVETIME_MS };
    SearchResult r = search_position(pos, limits, NULL);
    char san[SAN_MAX_LEN];
    move_to_san(pos, r.best, san);
    fprintf(out, "Engine plays %s (depth %d, score %d)\n", san, r.depth, r.score);
    make_move(pos, r.best);
    show(pos, out);
}

void play_loop(Position *pos, FILE *in, FILE *out)
{
    char line[256];
    play_help(out);
    show(pos, out);
    for (;;) {
        fputs("> ", out);
        fflush(out);
        if (!read_line(in, line, sizeof line)) break;
        if (line[0] == '\0') continue;
        if (strcmp(line, "quit") == 0) break;
        if (strcmp(line, "help") == 0) { play_help(out); continue; }
        if (strcmp(line, "moves") == 0) { print_moves(pos, out, " "); continue; }
        if (strcmp(line, "go") == 0) { engine_move(pos, out); continue; }
        if (strcmp(line, "fen") == 0) { char fen[FEN_MAX_LEN]; fen_write(pos, fen, sizeof fen); fprintf(out, "%s\n", fen); continue; }
        if (strcmp(line, "pgn") == 0) { char pgn[PGN_MAX_LEN]; pgn_write(pos, pgn, sizeof pgn); fputs(pgn, out); continue; }
        if (strcmp(line, "undo") == 0) {
            if (pos->ply == 0) fputs("Nothing to undo.\n", out); else { unmake_move(pos); show(pos, out); }
            continue;
        }
        Move m;
        if (game_state(pos) != ONGOING) fputs("The game is over: undo or quit.\n", out);
        else if (pos->ply >= MAX_PLY) fputs("The game is too long to continue (undo stack full).\n", out);
        else if (!parse_human_move(pos, line, &m)) fprintf(out, "'%s' is not a legal move; type 'moves' to list them.\n", line);
        else { make_move(pos, m); show(pos, out); }
    }
}

/* ---------------------------------------------------------------- batch -- */

/* Answer one batch command on out. Returns false on "quit". */
static bool batch_command(Position *pos, char *line, FILE *out)
{
    char *arg = strchr(line, ' ');
    if (arg != NULL) *arg++ = '\0';
    Move m;
    if (strcmp(line, "quit") == 0) return false;
    else if (strcmp(line, "position") == 0) {
        int err = fen_parse(pos, arg != NULL ? arg : "");
        if (err == FEN_OK) fputs("ok\n", out); else fprintf(out, "error %s\n", fen_error_string(err));
    }
    else if (strcmp(line, "move") == 0) {
        if (arg == NULL || move_from_uci(pos, arg, &m) != 0 || pos->ply >= MAX_PLY) fputs("error illegal move\n", out);
        else { make_move(pos, m); fputs("ok\n", out); }
    }
    else if (strcmp(line, "undo") == 0) {
        if (pos->ply == 0) fputs("error nothing to undo\n", out); else { unmake_move(pos); fputs("ok\n", out); }
    }
    else if (strcmp(line, "moves") == 0) print_moves(pos, out, " ");
    else if (strcmp(line, "status") == 0) fprintf(out, "%s\n", game_state_string(game_state(pos)));
    else if (strcmp(line, "san") == 0) {
        char san[SAN_MAX_LEN];
        if (arg == NULL || move_from_uci(pos, arg, &m) != 0 || pos->ply >= MAX_PLY) fputs("error illegal move\n", out);
        else { move_to_san(pos, m, san); fprintf(out, "%s\n", san); }
    }
    else if (strcmp(line, "fen") == 0) { char fen[FEN_MAX_LEN]; fen_write(pos, fen, sizeof fen); fprintf(out, "%s\n", fen); }
    else fprintf(out, "error unknown command '%s'\n", line);
    fflush(out);
    return true;
}

int batch_loop(FILE *in, FILE *out)
{
    static Position pos;   /* static: 17 KB is a lot for the stack of a small loop */
    fen_parse(&pos, START_FEN);
    char line[FEN_MAX_LEN + 32];
    while (read_line(in, line, sizeof line))
        if (!batch_command(&pos, line, out)) break;
    return EXIT_SUCCESS;
}
