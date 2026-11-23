/* search.c — negamax alpha-beta with iterative deepening and quiescence (see search.h).
 *
 * Negamax: a position's score for the side to move is the best of the
 * negated scores of the positions its moves lead to. alpha is the score the
 * side to move is already sure of, beta the score the opponent will not let
 * it exceed; once a move reaches beta the remaining moves cannot matter.
 * The clock is read every 1024 nodes; when time is up the search unwinds and
 * the result of the last depth that finished is kept.
 */
#define _POSIX_C_SOURCE 200809L   /* clock_gettime under -std=c17 on glibc (HURDLES.md 2026-11-10) */
#include "search.h"
#include "board.h"
#include "eval.h"
#include "game.h"
#include "make.h"
#include "movegen.h"

#include <assert.h>
#include <inttypes.h>
#include <time.h>

enum { MAX_QUIESCENCE_PLY = 32, CLOCK_CHECK_MASK = 1023 };

typedef struct {
    Position *pos;
    uint64_t  nodes;
    int64_t   deadline_ms;   /* 0 = no deadline */
    bool      stop;
} Search;

static int64_t now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* Count a node; every 1024 nodes look at the clock. Returns true once the search must stop. */
static bool visit(Search *s)
{
    s->nodes++;
    if (s->deadline_ms != 0 && (s->nodes & CLOCK_CHECK_MASK) == 0 && now_ms() >= s->deadline_ms)
        s->stop = true;
    return s->stop;
}

bool score_is_mate(int score)
{
    return score > MATE_SCORE - 1000 || score < -MATE_SCORE + 1000;
}

/* ------------------------------------------------------------- ordering -- */

/* MVV-LVA: captures first, the biggest victim first, and among equal victims
 * the cheapest attacker first. `first` (the best move of the previous
 * iteration) goes to the very front. Quiet moves keep their generation order. */
static int order_score(const Position *pos, Move m, const Move *first)
{
    if (first != NULL && m.from == first->from && m.to == first->to && m.promo == first->promo)
        return 1000000;
    int score = 0;
    if (m.flags & CAPTURE) {
        int victim = (m.flags & EN_PASSANT) ? PAWN : piece_type(pos->board[m.to]);
        score = 10000 + 10 * PIECE_VALUE[victim] - PIECE_VALUE[piece_type(pos->board[m.from])] / 10;
    }
    if (m.flags & PROMOTION) score += 9000 + PIECE_VALUE[m.promo];
    return score;
}

/* Insertion sort by order_score, highest first (lists are short and nearly sorted). */
static void order_moves(const Position *pos, MoveList *list, const Move *first)
{
    int score[MAX_MOVES];
    for (int i = 0; i < list->count; i++) score[i] = order_score(pos, list->moves[i], first);
    for (int i = 1; i < list->count; i++) {
        Move m = list->moves[i];
        int sc = score[i], j = i - 1;
        for (; j >= 0 && score[j] < sc; j--) {
            list->moves[j + 1] = list->moves[j];
            score[j + 1] = score[j];
        }
        list->moves[j + 1] = m;
        score[j + 1] = sc;
    }
}

/* ---------------------------------------------------------- quiescence -- */

/* Draws the search can see without generating moves. One earlier occurrence
 * is enough inside the tree: if the opponent can repeat once, it can repeat again. */
static bool is_draw(const Position *pos)
{
    return pos->halfmove_clock >= 100 || repetition_count(pos) >= 2 || insufficient_material(pos);
}

/* Search captures and promotions only, until nothing hangs. The side to move
 * may also "stand pat": decline every capture and take the static score.
 * In check there is no standing pat: every evasion is tried, and none means mate. */
static int quiesce(Search *s, int alpha, int beta, int ply, int qply)
{
    Position *pos = s->pos;
    if (visit(s)) return 0;
    bool check = in_check(pos);
    if (!check) {
        int stand = evaluate(pos);
        if (stand >= beta || qply >= MAX_QUIESCENCE_PLY || pos->ply >= MAX_PLY - 1) return stand;
        if (stand > alpha) alpha = stand;
    }
    MoveList list;
    int n = gen_legal(pos, &list);
    if (check && n == 0) return -MATE_SCORE + ply;
    if (check && (qply >= MAX_QUIESCENCE_PLY || pos->ply >= MAX_PLY - 1)) return evaluate(pos);
    order_moves(pos, &list, NULL);
    for (int i = 0; i < n && !s->stop; i++) {
        Move m = list.moves[i];
        if (!check && !(m.flags & (CAPTURE | PROMOTION))) continue;
        make_move(pos, m);
        int score = -quiesce(s, -beta, -alpha, ply + 1, qply + 1);
        unmake_move(pos);
        if (score >= beta) return score;
        if (score > alpha) alpha = score;
    }
    return alpha;
}

/* -------------------------------------------------------------- negamax -- */

/* Score of the position for the side to move, searching `depth` more plies.
 * A check extends the search by one ply: forced sequences are where shallow
 * searches go wrong. Mate is scored by distance so the shortest mate wins. */
static int negamax(Search *s, int depth, int alpha, int beta, int ply)
{
    Position *pos = s->pos;
    if (is_draw(pos)) return 0;
    bool check = in_check(pos);
    if (check && ply < MAX_SEARCH_DEPTH) depth++;
    if (depth <= 0 || pos->ply >= MAX_PLY - 1) return quiesce(s, alpha, beta, ply, 0);
    if (visit(s)) return 0;

    MoveList list;
    int n = gen_legal(pos, &list);
    if (n == 0) return check ? -MATE_SCORE + ply : 0;
    order_moves(pos, &list, NULL);
    for (int i = 0; i < n && !s->stop; i++) {
        make_move(pos, list.moves[i]);
        int score = -negamax(s, depth - 1, -beta, -alpha, ply + 1);
        unmake_move(pos);
        if (score >= beta) return score;
        if (score > alpha) alpha = score;
    }
    return alpha;
}

/* One iteration at the root: like negamax, but it remembers which move was best.
 * Returns false if the clock ran out before the iteration finished. */
static bool search_root(Search *s, int depth, MoveList *list, Move *best, int *best_score)
{
    int alpha = -SCORE_INF;
    Move found = list->moves[0];
    for (int i = 0; i < list->count; i++) {
        make_move(s->pos, list->moves[i]);
        int score = -negamax(s, depth - 1, -SCORE_INF, -alpha, 1);
        unmake_move(s->pos);
        if (s->stop) return false;
        if (score > alpha) { alpha = score; found = list->moves[i]; }
    }
    *best = found;
    *best_score = alpha;
    return true;
}

static void print_info(FILE *info, const SearchResult *r, int64_t elapsed_ms)
{
    char uci[6];
    move_to_uci(r->best, uci);
    fprintf(info, "info depth %d score ", r->depth);
    if (score_is_mate(r->score)) {
        int plies = MATE_SCORE - (r->score > 0 ? r->score : -r->score);
        fprintf(info, "mate %d", r->score > 0 ? (plies + 1) / 2 : -(plies / 2));
    } else {
        fprintf(info, "cp %d", r->score);
    }
    fprintf(info, " nodes %" PRIu64 " time %" PRId64 " pv %s\n", r->nodes, elapsed_ms, uci);
    fflush(info);
}

SearchResult search_position(Position *pos, SearchLimits limits, FILE *info)
{
    assert(limits.depth > 0 || limits.movetime_ms > 0);
    int64_t start = now_ms();
    Search s = { pos, 0, limits.movetime_ms > 0 ? start + limits.movetime_ms : 0, false };
    SearchResult r = { {0, 0, NO_TYPE, NORMAL}, false, 0, 0, 0 };
    MoveList list;
    if (gen_legal(pos, &list) == 0) return r;
    r.best = list.moves[0];
    r.has_move = true;

    int max_depth = limits.depth > 0 && limits.depth < MAX_SEARCH_DEPTH ? limits.depth : MAX_SEARCH_DEPTH;
    for (int depth = 1; depth <= max_depth; depth++) {
        order_moves(pos, &list, depth > 1 ? &r.best : NULL);
        Move best;
        int score;
        if (!search_root(&s, depth, &list, &best, &score)) break;
        r.best = best; r.score = score; r.depth = depth; r.nodes = s.nodes;
        if (info != NULL) print_info(info, &r, now_ms() - start);
        if (score_is_mate(score)) break;   /* a forced mate does not get better with depth */
        /* The next depth costs several times this one: do not start it with half the time gone. */
        if (s.deadline_ms != 0 && 2 * (now_ms() - start) >= limits.movetime_ms) break;
    }
    r.nodes = s.nodes;
    return r;
}
