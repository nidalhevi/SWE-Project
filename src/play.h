/* play.h — the two read-eval-print loops of the program (pass 2).
 *
 * play_loop is the terminal game for two humans. batch_loop is the same
 * engine behind a line protocol for tools (tools/diff_vs_python_chess.py):
 * one command per line in, one line out per command, always flushed. */
#ifndef CHESS_PLAY_H
#define CHESS_PLAY_H

#include "types.h"
#include <stdio.h>

/* Pre: board_consistent(pos), in/out open.
 * Post: a game was played interactively from pos; returns on "quit" or EOF. */
void play_loop(Position *pos, FILE *in, FILE *out);

/* Pre: in/out open.  Post: every line of `in` was answered on `out`:
 *   position <fen>   -> ok | error <why>
 *   move <uci>       -> ok | error illegal move
 *   undo             -> ok | error nothing to undo
 *   moves            -> the legal moves in UCI, sorted, space-separated
 *   status           -> ongoing | checkmate | stalemate | insufficient-material
 *                       | fifty-moves | threefold-repetition
 *   san <uci>        -> the SAN of that legal move | error illegal move
 *   fen              -> the FEN
 *   quit             -> (exits the loop)
 * Returns EXIT_SUCCESS. Never crashes on any input. */
int batch_loop(FILE *in, FILE *out);

#endif /* CHESS_PLAY_H */
