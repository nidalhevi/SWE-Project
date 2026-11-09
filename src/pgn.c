/* pgn.c — PGN import/export (see pgn.h).
 *
 * The parser is one loop over the text that looks at the first character of
 * each token to decide what it is: '[' tag, '{' comment, ';' line comment,
 * '(' variation, '$' annotation glyph, digits a move number, a result token,
 * anything else a SAN move. Every move goes through move_from_san(), so the
 * text can never put an illegal move on the board.
 */
#include "pgn.h"
#include "board.h"
#include "fen.h"
#include "game.h"
#include "make.h"
#include "san.h"

#include <assert.h>
#include <ctype.h>
#include <stdio.h>
#include <string.h>

#define START_FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

/* -------------------------------------------------------------- parsing -- */

typedef struct {
    const char *s;                 /* cursor into the text */
    Position pos;                  /* the game being built */
    bool moves_started;
    char fen[FEN_MAX_LEN];         /* from a FEN tag, or "" */
} Parser;

static bool is_result(const char *tok)
{
    return strcmp(tok, "1-0") == 0 || strcmp(tok, "0-1") == 0 ||
           strcmp(tok, "1/2-1/2") == 0 || strcmp(tok, "*") == 0;
}

/* Skip to just past the matching close of a '{' comment or '(' variation.
 * Variations nest and may contain comments; comments contain anything. */
static int skip_bracketed(Parser *p)
{
    int depth = 0;
    do {
        char c = *p->s++;
        if (c == '\0') return PGN_ERR_UNTERMINATED;
        if (c == '{') { const char *end = strchr(p->s, '}'); if (end == NULL) return PGN_ERR_UNTERMINATED; p->s = end + 1; if (depth == 0) return PGN_OK; }
        else if (c == '(') depth++;
        else if (c == ')') depth--;
    } while (depth > 0);
    return PGN_OK;
}

/* [Key "value"]: only the FEN tag matters; the rest is checked for shape and dropped. */
static int parse_tag(Parser *p)
{
    if (p->moves_started) return PGN_ERR_TAG;
    p->s++;                                             /* '[' */
    while (*p->s == ' ') p->s++;
    const char *key = p->s;
    while (isalnum((unsigned char)*p->s) || *p->s == '_') p->s++;
    size_t key_len = (size_t)(p->s - key);
    while (*p->s == ' ') p->s++;
    if (key_len == 0 || *p->s != '"') return PGN_ERR_TAG;
    const char *val = ++p->s;
    while (*p->s != '"' && *p->s != '\0') p->s += (*p->s == '\\' && p->s[1] != '\0') ? 2 : 1;
    if (*p->s != '"') return PGN_ERR_TAG;
    size_t val_len = (size_t)(p->s - val);
    p->s++;
    while (*p->s == ' ') p->s++;
    if (*p->s++ != ']') return PGN_ERR_TAG;
    if (key_len == 3 && strncmp(key, "FEN", 3) == 0) {
        if (val_len >= sizeof p->fen) return PGN_ERR_FEN;
        memcpy(p->fen, val, val_len);
        p->fen[val_len] = '\0';
    }
    return PGN_OK;
}

/* The first move token: set up the start position (tags are complete now). */
static int start_moves(Parser *p)
{
    p->moves_started = true;
    return fen_parse(&p->pos, p->fen[0] != '\0' ? p->fen : START_FEN) == FEN_OK ? PGN_OK : PGN_ERR_FEN;
}

/* Apply one SAN move to the game. */
static int parse_move_token_san(Parser *p, const char *san)
{
    if (p->pos.ply >= MAX_PLY) return PGN_ERR_TOO_LONG;
    Move m;
    if (move_from_san(&p->pos, san, &m) != SAN_OK) return PGN_ERR_MOVE;
    make_move(&p->pos, m);
    return PGN_OK;
}

/* One token of movetext: a move number, a result, or a SAN move. Returns
 * PGN_OK, an error, or -1 when the result token ends the game. */
static int parse_move_token(Parser *p)
{
    char tok[SAN_MAX_LEN];
    size_t n = 0;
    while (*p->s != '\0' && !isspace((unsigned char)*p->s) && strchr("{};()[", *p->s) == NULL) {
        if (n + 1 >= sizeof tok) return PGN_ERR_MOVE;
        tok[n++] = *p->s++;
    }
    tok[n] = '\0';
    if (!p->moves_started) { int err = start_moves(p); if (err != PGN_OK) return err; }
    if (is_result(tok)) return -1;
    if (isdigit((unsigned char)tok[0])) {               /* "12." or "12..." : skip */
        size_t i = 0;
        while (isdigit((unsigned char)tok[i])) i++;
        while (tok[i] == '.') i++;
        if (tok[i] == '\0') return PGN_OK;
        return parse_move_token_san(p, tok + i);         /* "12.Nf3" glued together */
    }
    return parse_move_token_san(p, tok);
}

int pgn_parse(Position *pos, const char *text)
{
    if (pos == NULL || text == NULL) return PGN_ERR_NULL;
    Parser p = { text, *pos, false, "" };
    int err = PGN_OK;
    while (err == PGN_OK) {
        while (isspace((unsigned char)*p.s)) p.s++;
        char c = *p.s;
        if (c == '\0') break;
        else if (c == '[') err = parse_tag(&p);
        else if (c == '{' || c == '(') err = skip_bracketed(&p);
        else if (c == ';') { const char *nl = strchr(p.s, '\n'); p.s = nl ? nl : p.s + strlen(p.s); }
        else if (c == '$') { p.s++; while (isdigit((unsigned char)*p.s)) p.s++; }
        else if (c == ')' || c == '}' || c == ']') p.s++;   /* stray closer: ignore */
        else err = parse_move_token(&p);
    }
    if (err == -1) err = PGN_OK;
    if (err == PGN_OK && !p.moves_started) err = start_moves(&p);   /* tags only: an empty game */
    if (err != PGN_OK) return err;
    *pos = p.pos;
    return PGN_OK;
}

/* -------------------------------------------------------------- writing -- */

typedef struct { char *buf; size_t n, len, column; } Writer;

/* Append s, wrapping to a new line first if it would pass column 80.
 * Output is silently truncated when the buffer is full. */
static void emit(Writer *w, const char *s, bool wrap)
{
    size_t len = strlen(s);
    if (wrap && w->column + len > 79 && w->column > 0) { emit(w, "\n", false); w->column = 0; }
    if (w->len + len >= w->n) len = w->n > w->len + 1 ? w->n - w->len - 1 : 0;
    memcpy(w->buf + w->len, s, len);
    w->len += len;
    w->buf[w->len] = '\0';
    w->column = strchr(s, '\n') ? 0 : w->column + len;
}

static void emit_tag(Writer *w, const char *key, const char *value)
{
    char line[FEN_MAX_LEN + 32];
    snprintf(line, sizeof line, "[%s \"%s\"]\n", key, value);
    emit(w, line, false);
}

void pgn_write(const Position *pos, char *buf, size_t n)
{
    assert(board_consistent(pos));
    if (n == 0) return;
    Writer w = { buf, n, 0, 0 };
    buf[0] = '\0';

    Position game = *pos;                       /* rewind a copy to the start */
    while (game.ply > 0) unmake_move(&game);
    char fen[FEN_MAX_LEN], text[SAN_MAX_LEN + 8];
    fen_write(&game, fen, sizeof fen);
    const char *result = game_result_string(pos, game_state(pos));

    static const char *const ROSTER[][2] = { {"Event", "?"}, {"Site", "?"}, {"Date", "????.??.??"},
                                             {"Round", "?"}, {"White", "?"}, {"Black", "?"} };
    for (size_t i = 0; i < sizeof ROSTER / sizeof ROSTER[0]; i++) emit_tag(&w, ROSTER[i][0], ROSTER[i][1]);
    emit_tag(&w, "Result", result);
    if (strcmp(fen, START_FEN) != 0) { emit_tag(&w, "SetUp", "1"); emit_tag(&w, "FEN", fen); }
    emit(&w, "\n", false);

    for (int i = 0; i < pos->ply; i++) {
        Move m = pos->undo[i].move;
        char san[SAN_MAX_LEN];
        move_to_san(&game, m, san);
        if (game.side_to_move == WHITE) snprintf(text, sizeof text, "%d. %s", game.fullmove_number, san);
        else if (i == 0) snprintf(text, sizeof text, "%d... %s", game.fullmove_number, san);
        else snprintf(text, sizeof text, "%s", san);
        if (w.column > 0) emit(&w, " ", false);
        emit(&w, text, true);
        make_move(&game, m);
    }
    if (w.column > 0) emit(&w, " ", false);
    emit(&w, result, true);
    emit(&w, "\n", false);
}

const char *pgn_error_string(int err)
{
    static const char *const text[PGN_ERR_COUNT] = {
        [PGN_OK] = "ok",
        [PGN_ERR_NULL] = "no PGN text given",
        [PGN_ERR_TAG] = "malformed [Tag \"value\"] pair, or a tag after the moves began",
        [PGN_ERR_FEN] = "the FEN tag is not a valid position",
        [PGN_ERR_MOVE] = "a move is not a legal SAN move in its position",
        [PGN_ERR_TOO_LONG] = "the game has more plies than the undo stack holds",
        [PGN_ERR_UNTERMINATED] = "a { comment or ( variation is never closed",
    };
    if (err < 0 || err >= PGN_ERR_COUNT) return "unknown PGN error";
    return text[err];
}
