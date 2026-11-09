/* fuzz_fen.c — libFuzzer target for fen_parse (see docs/FUZZING.md).
 * The fuzzer hands us arbitrary bytes; fen_parse must either reject them or
 * produce a consistent position that fen_write can turn back into text. */
#include "board.h"
#include "fen.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    char *text = malloc(size + 1);          /* fen_parse wants a NUL-terminated string */
    if (text == NULL) return 0;
    memcpy(text, data, size);
    text[size] = '\0';

    static Position pos;
    if (fen_parse(&pos, text) == FEN_OK) {
        if (!board_consistent(&pos)) abort();
        char out[FEN_MAX_LEN];
        fen_write(&pos, out, sizeof out);
        Position again;
        if (fen_parse(&again, out) != FEN_OK) abort();   /* what we write, we must read */
    }
    free(text);
    return 0;
}
