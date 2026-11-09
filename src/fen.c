/* fen.c — FEN parsing and writing.
 *
 * fen_parse works on a local Position and copies it into *pos only when every
 * check passed, so a rejected string never leaves the caller's position half
 * written. The six fields are checked in order and the first problem wins.
 */
#include "fen.h"
#include "board.h"
#include "movegen.h"
#include "zobrist.h"

#include <assert.h>
#include <ctype.h>
#include <stdio.h>
#include <string.h>

/* ---------------------------------------------------------------- tokens -- */

static bool is_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }

/* Skip whitespace, point *tok at the next token, return its length (0 at end). */
static size_t next_token(const char *s, const char **tok)
{
    while (is_space(*s)) s++;
    *tok = s;
    while (*s != '\0' && !is_space(*s)) s++;
    return (size_t)(s - *tok);
}

/* ------------------------------------------------------------- placement -- */

/* Handle one character of the placement field at (file, rank). */
static int place_char(Position *p, char c, char prev, int *file, int *rank)
{
    if (c == '/') {
        if (*file != 8) return FEN_ERR_RANK_WIDTH;
        if (*rank == 0) return FEN_ERR_RANK_COUNT;   /* a 9th rank is starting */
        (*rank)--;
        *file = 0;
        return FEN_OK;
    }
    if (c >= '1' && c <= '8') {
        if (prev >= '1' && prev <= '8') return FEN_ERR_BAD_CHAR;   /* "44" */
        *file += c - '0';
        return *file > 8 ? FEN_ERR_RANK_WIDTH : FEN_OK;
    }
    Piece piece = char_to_piece(c);
    if (piece == EMPTY) return FEN_ERR_BAD_CHAR;
    if (*file >= 8) return FEN_ERR_RANK_WIDTH;
    board_set(p, make_square(*file, *rank), piece);
    (*file)++;
    return FEN_OK;
}

/* Field 1: ranks 8 down to 1, separated by '/'. */
static int parse_placement(Position *p, const char *tok, size_t len)
{
    int file = 0, rank = 7;
    char prev = '\0';
    for (size_t i = 0; i < len; i++) {
        int err = place_char(p, tok[i], prev, &file, &rank);
        if (err != FEN_OK) return err;
        prev = tok[i];
    }
    if (file != 8) return FEN_ERR_RANK_WIDTH;
    if (rank != 0) return FEN_ERR_RANK_COUNT;
    return FEN_OK;
}

/* Material sanity: one king each (not touching), no pawn on a back rank,
 * at most 8 pawns and 16 pieces per colour. */
static int check_pieces(const Position *p)
{
    int kings[2] = {0, 0}, pawns[2] = {0, 0}, total[2] = {0, 0};
    for (Square sq = 0; sq < SQUARE_NB; sq++) {
        Piece piece = p->board[sq];
        if (piece == EMPTY) continue;
        Color c = piece_color(piece);
        int type = piece_type(piece);
        total[c]++;
        if (type == KING) kings[c]++;
        if (type == PAWN) {
            pawns[c]++;
            if (sq_rank(sq) == 0 || sq_rank(sq) == 7) return FEN_ERR_PAWN_RANK;
        }
    }
    if (kings[WHITE] != 1 || kings[BLACK] != 1) return FEN_ERR_KINGS;
    if (pawns[WHITE] > 8 || pawns[BLACK] > 8) return FEN_ERR_PIECE_COUNT;
    if (total[WHITE] > 16 || total[BLACK] > 16) return FEN_ERR_PIECE_COUNT;

    int df = sq_file(p->king_sq[WHITE]) - sq_file(p->king_sq[BLACK]);
    int dr = sq_rank(p->king_sq[WHITE]) - sq_rank(p->king_sq[BLACK]);
    if (df >= -1 && df <= 1 && dr >= -1 && dr <= 1) return FEN_ERR_KINGS;
    return FEN_OK;
}

/* ---------------------------------------------------------- other fields -- */

static int parse_side(Position *p, const char *tok, size_t len)
{
    if (len != 1 || (tok[0] != 'w' && tok[0] != 'b')) return FEN_ERR_SIDE;
    p->side_to_move = tok[0] == 'w' ? WHITE : BLACK;
    return FEN_OK;
}

/* A right is only accepted if its king and rook are on their home squares. */
static bool right_is_plausible(const Position *p, int bit)
{
    switch (bit) {
    case CASTLE_WK: return p->board[E1] == WK && p->board[H1] == WR;
    case CASTLE_WQ: return p->board[E1] == WK && p->board[A1] == WR;
    case CASTLE_BK: return p->board[E8] == BK && p->board[H8] == BR;
    case CASTLE_BQ: return p->board[E8] == BK && p->board[A8] == BR;
    default:        return false;
    }
}

static const char CASTLING_LETTERS[] = "KQkq";   /* index i <-> bit 1 << i */

static int parse_castling(Position *p, const char *tok, size_t len)
{
    if (len == 1 && tok[0] == '-') return FEN_OK;
    if (len > 4) return FEN_ERR_CASTLING;
    for (size_t i = 0; i < len; i++) {
        const char *at = strchr(CASTLING_LETTERS, tok[i]);
        if (at == NULL || *at == '\0') return FEN_ERR_CASTLING;
        int bit = 1 << (at - CASTLING_LETTERS);
        if (p->castling & bit) return FEN_ERR_CASTLING;        /* repeated letter */
        if (!right_is_plausible(p, bit)) return FEN_ERR_CASTLING;
        p->castling |= bit;
    }
    return FEN_OK;
}

/* The ep square must be the one a double push just skipped: on rank 6 with
 * white to move (rank 3 with black), empty, with the pushed pawn in front of
 * it and the square it came from empty. */
static int parse_ep(Position *p, const char *tok, size_t len)
{
    if (len == 1 && tok[0] == '-') return FEN_OK;
    if (len != 2) return FEN_ERR_EP_SQUARE;
    Square ep = str_to_square(tok);
    if (ep == NO_SQUARE) return FEN_ERR_EP_SQUARE;

    bool white = p->side_to_move == WHITE;
    if (sq_rank(ep) != (white ? 5 : 2)) return FEN_ERR_EP_SQUARE;
    Square pawn_sq = white ? ep - 8 : ep + 8;   /* where the pushed pawn stands */
    Square from_sq = white ? ep + 8 : ep - 8;   /* where it came from */
    Piece pawn = white ? BP : WP;
    if (p->board[pawn_sq] != pawn) return FEN_ERR_EP_SQUARE;
    if (p->board[ep] != EMPTY || p->board[from_sq] != EMPTY) return FEN_ERR_EP_SQUARE;
    p->ep_square = ep;
    return FEN_OK;
}

/* Plain decimal, 1..6 digits, value in [lo, hi]. */
static int parse_counter(const char *tok, size_t len, int lo, int hi, int *out)
{
    if (len == 0 || len > 6) return FEN_ERR_COUNTER;
    int v = 0;
    for (size_t i = 0; i < len; i++) {
        if (!isdigit((unsigned char)tok[i])) return FEN_ERR_COUNTER;
        v = v * 10 + (tok[i] - '0');
    }
    if (v < lo || v > hi) return FEN_ERR_COUNTER;
    *out = v;
    return FEN_OK;
}

static int parse_counters(Position *p, const char *half, size_t hlen,
                          const char *full, size_t flen)
{
    int err = parse_counter(half, hlen, 0, 9999, &p->halfmove_clock);
    if (err != FEN_OK) return err;
    err = parse_counter(full, flen, 1, 9999, &p->fullmove_number);
    if (err != FEN_OK) return err;
    /* A double push is a pawn move, so the clock was just reset. */
    if (p->ep_square != NO_SQUARE && p->halfmove_clock != 0) return FEN_ERR_COUNTER;
    return FEN_OK;
}

/* ------------------------------------------------------------ public API -- */

int fen_parse(Position *pos, const char *fen)
{
    if (pos == NULL || fen == NULL) return FEN_ERR_NULL;

    const char *tok[6];
    size_t len[6];
    const char *s = fen;
    for (int i = 0; i < 6; i++) {
        len[i] = next_token(s, &tok[i]);
        if (len[i] == 0) return FEN_ERR_FIELDS;
        s = tok[i] + len[i];
    }
    const char *rest;
    if (next_token(s, &rest) != 0) return FEN_ERR_TRAILING;

    Position p;
    board_init(&p);
    int err;
    if ((err = parse_placement(&p, tok[0], len[0])) != FEN_OK) return err;
    if ((err = check_pieces(&p)) != FEN_OK) return err;
    if ((err = parse_side(&p, tok[1], len[1])) != FEN_OK) return err;
    if ((err = parse_castling(&p, tok[2], len[2])) != FEN_OK) return err;
    if ((err = parse_ep(&p, tok[3], len[3])) != FEN_OK) return err;
    if ((err = parse_counters(&p, tok[4], len[4], tok[5], len[5])) != FEN_OK) return err;
    /* The side that just moved may not have left its own king in check. */
    Color them = p.side_to_move == WHITE ? BLACK : WHITE;
    if (is_square_attacked(&p, p.king_sq[them], p.side_to_move)) return FEN_ERR_IN_CHECK;

    p.hash = zobrist_hash(&p);   /* pieces were hashed by board_set; add castling/side/ep */
    assert(board_consistent(&p));
    *pos = p;
    return FEN_OK;
}

/* Writes the placement field; returns the number of characters written. */
static size_t write_placement(const Position *pos, char *out)
{
    size_t n = 0;
    for (int rank = 7; rank >= 0; rank--) {
        int empty = 0;
        for (int file = 0; file < 8; file++) {
            Piece p = pos->board[make_square(file, rank)];
            if (p == EMPTY) { empty++; continue; }
            if (empty > 0) { out[n++] = (char)('0' + empty); empty = 0; }
            out[n++] = piece_to_char(p);
        }
        if (empty > 0) out[n++] = (char)('0' + empty);
        if (rank > 0) out[n++] = '/';
    }
    out[n] = '\0';
    return n;
}

void fen_write(const Position *pos, char *buf, size_t n)
{
    assert(board_consistent(pos));
    char tmp[FEN_MAX_LEN];
    size_t len = write_placement(pos, tmp);

    char castling[5] = "-";
    if (pos->castling != 0) {
        int k = 0;
        for (int bit = 0; bit < 4; bit++)
            if (pos->castling & (1 << bit)) castling[k++] = CASTLING_LETTERS[bit];
        castling[k] = '\0';
    }
    char ep[3] = "-";
    if (pos->ep_square != NO_SQUARE) square_to_str(pos->ep_square, ep);

    snprintf(tmp + len, sizeof tmp - len, " %c %s %s %d %d",
             pos->side_to_move == WHITE ? 'w' : 'b', castling, ep,
             pos->halfmove_clock, pos->fullmove_number);
    snprintf(buf, n, "%s", tmp);   /* truncates safely; n == 0 writes nothing */
}

const char *fen_error_string(int err)
{
    static const char *const text[FEN_ERR_COUNT] = {
        [FEN_OK]              = "ok",
        [FEN_ERR_NULL]        = "no FEN given",
        [FEN_ERR_FIELDS]      = "expected 6 fields: placement side castling ep halfmove fullmove",
        [FEN_ERR_TRAILING]    = "unexpected text after the fullmove number",
        [FEN_ERR_RANK_COUNT]  = "placement must have exactly 8 ranks separated by '/'",
        [FEN_ERR_RANK_WIDTH]  = "a rank does not describe exactly 8 squares",
        [FEN_ERR_BAD_CHAR]    = "placement has a character that is not a piece letter or a digit 1-8",
        [FEN_ERR_KINGS]       = "each side needs exactly one king, and the kings may not touch",
        [FEN_ERR_PAWN_RANK]   = "a pawn is on rank 1 or rank 8",
        [FEN_ERR_PIECE_COUNT] = "more than 8 pawns or more than 16 pieces for one side",
        [FEN_ERR_SIDE]        = "side to move must be 'w' or 'b'",
        [FEN_ERR_CASTLING]    = "castling field must be '-' or letters from KQkq whose king and rook are at home",
        [FEN_ERR_EP_SQUARE]   = "en-passant square is malformed or does not match the position",
        [FEN_ERR_COUNTER]     = "halfmove/fullmove counters must be plain numbers in range (fullmove >= 1)",
        [FEN_ERR_IN_CHECK]    = "the side not to move is in check",
    };
    if (err < 0 || err >= FEN_ERR_COUNT) return "unknown FEN error";
    return text[err];
}
