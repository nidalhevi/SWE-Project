/* san.c — SAN printing and parsing (see san.h).
 *
 * Printing never guesses: disambiguation is decided by looking at the other
 * legal moves of the same piece type to the same square. Parsing never
 * trusts the text either: it is reduced to a small pattern (piece, from-file,
 * from-rank, to, promotion) and the legal move list is searched for the one
 * move that fits, so an illegal SAN string can never produce a move.
 */
#include "san.h"
#include "board.h"
#include "make.h"
#include "movegen.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static const char PIECE_LETTERS[] = { [KNIGHT] = 'N', [BISHOP] = 'B', [ROOK] = 'R', [QUEEN] = 'Q', [KING] = 'K' };

/* ------------------------------------------------------------ printing -- */

/* "" , "e", "4" or "e4": the smallest prefix that singles out m.from among
 * the legal moves of the same piece type that also land on m.to. */
static void disambiguation(const Position *pos, const MoveList *legal, Move m, char out[3])
{
    int type = piece_type(pos->board[m.from]);
    bool other = false, same_file = false, same_rank = false;
    for (int i = 0; i < legal->count; i++) {
        Move o = legal->moves[i];
        if (o.to != m.to || o.from == m.from || piece_type(pos->board[o.from]) != type) continue;
        other = true;
        if (sq_file(o.from) == sq_file(m.from)) same_file = true;
        if (sq_rank(o.from) == sq_rank(m.from)) same_rank = true;
    }
    int n = 0;
    if (other && (!same_file || same_rank)) out[n++] = (char)('a' + sq_file(m.from));
    if (other && same_file) out[n++] = (char)('1' + sq_rank(m.from));
    out[n] = '\0';
}

/* '+' if the move gives check, '#' if it mates, else nothing. */
static const char *check_suffix(Position *pos, Move m)
{
    make_move(pos, m);
    const char *suffix = "";
    if (in_check(pos)) {
        MoveList replies;
        suffix = gen_legal(pos, &replies) == 0 ? "#" : "+";
    }
    unmake_move(pos);
    return suffix;
}

void move_to_san(Position *pos, Move m, char buf[SAN_MAX_LEN])
{
    assert(pos->ply < MAX_PLY);
    MoveList legal;
    gen_legal(pos, &legal);
    int type = piece_type(pos->board[m.from]);
    char to[3], dis[3] = "", promo[3] = "";
    square_to_str(m.to, to);

    if (m.flags & (CASTLE_K | CASTLE_Q)) {
        snprintf(buf, SAN_MAX_LEN, "%s%s", (m.flags & CASTLE_K) ? "O-O" : "O-O-O", check_suffix(pos, m));
        return;
    }
    if (type == PAWN) {
        /* A pawn capture is written with its file, never anything else. */
        if (m.flags & CAPTURE) { dis[0] = (char)('a' + sq_file(m.from)); dis[1] = '\0'; }
        if (m.flags & PROMOTION) { promo[0] = '='; promo[1] = PIECE_LETTERS[m.promo]; promo[2] = '\0'; }
        snprintf(buf, SAN_MAX_LEN, "%s%s%s%s%s", dis, (m.flags & CAPTURE) ? "x" : "", to, promo,
                 check_suffix(pos, m));
        return;
    }
    disambiguation(pos, &legal, m, dis);
    snprintf(buf, SAN_MAX_LEN, "%c%s%s%s%s", PIECE_LETTERS[type], dis, (m.flags & CAPTURE) ? "x" : "",
             to, check_suffix(pos, m));
}

/* ------------------------------------------------------------- parsing -- */

/* What a SAN string says about the move; -1 means "not given". */
typedef struct { int type, from_file, from_rank, promo, castle; Square to; bool capture; } Pattern;

static int letter_to_type(char c)
{
    for (int t = KNIGHT; t <= KING; t++)
        if (PIECE_LETTERS[t] == c) return t;
    return NO_TYPE;
}

/* Reduce s to a Pattern, or return SAN_ERR_SYNTAX. */
static int parse_pattern(const char *s, Pattern *p)
{
    char buf[SAN_MAX_LEN];
    if (strlen(s) >= sizeof buf) return SAN_ERR_SYNTAX;
    strcpy(buf, s);
    size_t len = strlen(buf);
    while (len > 0 && strchr("+#!?", buf[len - 1]) != NULL) buf[--len] = '\0';

    *p = (Pattern){ PAWN, -1, -1, NO_TYPE, 0, NO_SQUARE, false };
    if (strcmp(buf, "O-O") == 0 || strcmp(buf, "0-0") == 0) { p->castle = CASTLE_K; return SAN_OK; }
    if (strcmp(buf, "O-O-O") == 0 || strcmp(buf, "0-0-0") == 0) { p->castle = CASTLE_Q; return SAN_OK; }

    size_t i = 0;
    if (letter_to_type(buf[0]) != NO_TYPE) p->type = letter_to_type(buf[i++]);
    /* Promotion suffix: "=Q" or a bare "Q" after the square. */
    if (len >= 2 && buf[len - 2] == '=') { p->promo = letter_to_type(buf[len - 1]); len -= 2; }
    else if (p->type == PAWN && len > 2 && letter_to_type(buf[len - 1]) != NO_TYPE) p->promo = letter_to_type(buf[--len]);
    if (p->promo == KING || (len >= 2 && buf[len - 2] == '=')) return SAN_ERR_SYNTAX;
    buf[len] = '\0';

    if (len < i + 2) return SAN_ERR_SYNTAX;
    p->to = str_to_square(buf + len - 2);
    if (p->to == NO_SQUARE) return SAN_ERR_SYNTAX;
    for (; i < len - 2; i++) {                 /* what is left between piece and square */
        char c = buf[i];
        if (c == 'x') p->capture = true;
        else if (c >= 'a' && c <= 'h' && p->from_file < 0) p->from_file = c - 'a';
        else if (c >= '1' && c <= '8' && p->from_rank < 0) p->from_rank = c - '1';
        else return SAN_ERR_SYNTAX;
    }
    return SAN_OK;
}

static bool matches(const Position *pos, Move m, const Pattern *p)
{
    if (p->castle != 0) return (m.flags & p->castle) != 0;
    if (m.flags & (CASTLE_K | CASTLE_Q)) return false;
    if (piece_type(pos->board[m.from]) != p->type || m.to != p->to) return false;
    if (m.promo != p->promo) return false;
    if (p->from_file >= 0 && sq_file(m.from) != p->from_file) return false;
    if (p->from_rank >= 0 && sq_rank(m.from) != p->from_rank) return false;
    /* "d5" is a pawn push: a pawn capture is always written with its file. */
    if (p->type == PAWN && p->from_file < 0 && (m.flags & CAPTURE)) return false;
    return true;
}

int move_from_san(const Position *pos, const char *s, Move *out)
{
    if (s == NULL || out == NULL) return SAN_ERR_SYNTAX;
    Pattern p;
    int err = parse_pattern(s, &p);
    if (err != SAN_OK) return err;

    MoveList legal;
    int n = gen_legal(pos, &legal), found = 0;
    for (int i = 0; i < n; i++) {
        if (!matches(pos, legal.moves[i], &p)) continue;
        if (found++ == 0) *out = legal.moves[i];
    }
    if (found == 0) return SAN_ERR_ILLEGAL;
    return found == 1 ? SAN_OK : SAN_ERR_AMBIGUOUS;
}
