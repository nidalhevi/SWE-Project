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
#include <pthread.h>
#include <stdatomic.h>
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

/* ------------------------------------------------------------ copy-make -- */

uint64_t perft_copy(const Position *pos, int depth)
{
    if (depth == 0) return 1;
    MoveList list;
    int n = gen_legal(pos, &list);
    if (depth == 1) return (uint64_t)n;

    Position child;   /* one per level of the recursion; only its first ~500 bytes are ever written */
    uint64_t nodes = 0;
    for (int i = 0; i < n; i++) {
        position_copy_head(&child, pos);
        make_move(&child, list.moves[i]);
        nodes += perft_copy(&child, depth - 1);
    }
    return nodes;
}

/* ------------------------------------------------------------ root split -- */

/* What the threads share: the root moves and the index of the next one to take.
 * The index is atomic, so two threads can never take the same move, and a
 * thread that finishes a small subtree simply takes the next move: no thread
 * waits while another still has work. Each thread sums into its own counter. */
typedef struct {
    const Position *root;
    const MoveList *moves;
    int             depth;
    atomic_int      next;
} SplitJob;

typedef struct { SplitJob *job; Position *pos; uint64_t nodes; } SplitWorker;

static void *split_worker(void *arg)
{
    SplitWorker *w = arg;
    position_copy_head(w->pos, w->job->root);
    for (;;) {
        int i = atomic_fetch_add(&w->job->next, 1);
        if (i >= w->job->moves->count) break;
        make_move(w->pos, w->job->moves->moves[i]);
        w->nodes += perft(w->pos, w->job->depth - 1);
        unmake_move(w->pos);
    }
    return NULL;
}

uint64_t perft_threads(const Position *pos, int depth, int threads)
{
    assert(threads >= 1 && threads <= PERFT_MAX_THREADS);
    static Position copies[PERFT_MAX_THREADS];   /* static: 50 KB each is too much for thread stacks */
    if (depth == 0) return 1;
    MoveList list;
    int n = gen_legal(pos, &list);
    if (depth == 1) return (uint64_t)n;

    SplitJob job = { pos, &list, depth, 0 };
    SplitWorker workers[PERFT_MAX_THREADS];
    pthread_t ids[PERFT_MAX_THREADS];
    bool started[PERFT_MAX_THREADS];
    for (int t = 0; t < threads; t++) {
        workers[t] = (SplitWorker){ &job, &copies[t], 0 };
        /* Worker 0 is this thread itself, so a failed pthread_create only means less help. */
        started[t] = t > 0 && pthread_create(&ids[t], NULL, split_worker, &workers[t]) == 0;
    }
    split_worker(&workers[0]);
    uint64_t nodes = 0;
    for (int t = 0; t < threads; t++) {
        if (started[t]) pthread_join(ids[t], NULL);
        nodes += workers[t].nodes;
    }
    return nodes;
}
