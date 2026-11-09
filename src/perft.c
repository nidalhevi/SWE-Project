/* perft.c — count leaf nodes of the legal move tree (the correctness oracle).
 *
 * Depth 1 is "bulk counted": the number of legal moves is the answer, so no
 * make/unmake happens at the last ply. That alone makes perft several times
 * faster without changing any count.
 */
#include "perft.h"
#include "board.h"
#include "make.h"
#include "movegen.h"

#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

uint64_t perft(Position *pos, int depth)
{
    assert(depth >= 0 && depth < MAX_PLY - pos->ply);
    if (depth == 0) return 1;
    MoveList list;
    int n = gen_legal(pos, &list);
    if (depth == 1) return (uint64_t)n;

    uint64_t nodes = 0;
    for (int i = 0; i < n; i++) {
        make_move(pos, list.moves[i]);
        nodes += perft(pos, depth - 1);
        unmake_move(pos);
    }
    return nodes;
}

typedef struct { char uci[6]; uint64_t nodes; } RootEntry;

static int compare_root(const void *a, const void *b)
{
    return strcmp(((const RootEntry *)a)->uci, ((const RootEntry *)b)->uci);
}

uint64_t perft_divide(Position *pos, int depth)
{
    assert(depth >= 1);
    MoveList list;
    int n = gen_legal(pos, &list);
    RootEntry roots[MAX_MOVES];
    uint64_t total = 0;
    for (int i = 0; i < n; i++) {
        move_to_uci(list.moves[i], roots[i].uci);
        make_move(pos, list.moves[i]);
        roots[i].nodes = perft(pos, depth - 1);
        unmake_move(pos);
        total += roots[i].nodes;
    }
    qsort(roots, (size_t)n, sizeof roots[0], compare_root);
    for (int i = 0; i < n; i++) printf("%s %" PRIu64 "\n", roots[i].uci, roots[i].nodes);
    printf("total %" PRIu64 "\n", total);
    return total;
}
