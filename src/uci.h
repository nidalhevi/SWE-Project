/* uci.h — the Universal Chess Interface, the text protocol chess GUIs speak (pass 3).
 *
 * Supported: uci, isready, ucinewgame, position [startpos | fen <fen>] [moves ...],
 * go [depth n] [movetime ms] [wtime ms] [btime ms] [winc ms] [binc ms] [movestogo n] [infinite],
 * quit. The search runs in the thread that reads the commands, so "stop" cannot
 * interrupt it: every "go" is given a limit and answers by itself.
 */
#ifndef CHESS_UCI_H
#define CHESS_UCI_H

#include "search.h"
#include <stdio.h>

/* Pre: in/out open.  Post: every line of `in` was handled until "quit" or end
 * of input. Unknown or malformed commands are ignored, as the protocol asks;
 * no input crashes it. Returns EXIT_SUCCESS. */
int uci_loop(FILE *in, FILE *out);

/* Pre: args is the text after "go" (may be empty), white_to_move says whose clock counts.
 * Post: the limits that "go" line asks for. Exposed for the unit tests. */
SearchLimits uci_parse_go(const char *args, bool white_to_move);

#endif /* CHESS_UCI_H */
