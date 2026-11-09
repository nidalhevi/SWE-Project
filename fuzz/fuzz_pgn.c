/* fuzz_pgn.c — libFuzzer target for pgn_parse (see docs/FUZZING.md).
 * Any bytes in; either an error code or a consistent position with a
 * re-parsable PGN out. Inputs are capped so one run stays fast. */
#include "board.h"
#include "fen.h"
#include "pgn.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    if (size > 4096) return 0;
    char *text = malloc(size + 1);
    if (text == NULL) return 0;
    memcpy(text, data, size);
    text[size] = '\0';

    static Position pos;
    static char out[PGN_MAX_LEN];
    fen_parse(&pos, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    if (pgn_parse(&pos, text) == PGN_OK) {
        if (!board_consistent(&pos)) abort();
        pgn_write(&pos, out, sizeof out);
        static Position again;
        if (pgn_parse(&again, out) != PGN_OK || again.ply != pos.ply) abort();
    }
    free(text);
    return 0;
}
