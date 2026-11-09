/* test_fen.c — FEN round-trips, field checks and malformed input.
 *
 * Tiny self-contained harness: CHECK() counts and prints failures, main()
 * returns 1 if anything failed. Runs under ASan + UBSan via `make test`.
 */
#include "board.h"
#include "fen.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int checks = 0, failures = 0;

#define CHECK(cond, ...)                                              \
    do {                                                              \
        checks++;                                                     \
        if (!(cond)) {                                                \
            failures++;                                               \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);               \
            printf(__VA_ARGS__);                                      \
            printf("\n");                                             \
        }                                                             \
    } while (0)

#define START_FEN "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
#define KIWIPETE  "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"

/* ------------------------------------------------------------ helpers -- */

static Square sq(const char *name) { return str_to_square(name); }

/* The fields a FEN describes; the undo stack is deliberately left out. */
static bool same_position(const Position *a, const Position *b)
{
    return memcmp(a->board, b->board, sizeof a->board) == 0 &&
           a->side_to_move == b->side_to_move && a->castling == b->castling &&
           a->ep_square == b->ep_square && a->halfmove_clock == b->halfmove_clock &&
           a->fullmove_number == b->fullmove_number &&
           a->king_sq[WHITE] == b->king_sq[WHITE] && a->king_sq[BLACK] == b->king_sq[BLACK];
}

/* ------------------------------------------------------- valid input -- */

static void test_start_position_fields(void)
{
    Position pos;
    CHECK(fen_parse(&pos, START_FEN) == FEN_OK, "start position must parse");
    CHECK(piece_at(&pos, sq("a1")) == WR, "a1 is a white rook");
    CHECK(piece_at(&pos, sq("e1")) == WK, "e1 is the white king");
    CHECK(piece_at(&pos, sq("d8")) == BQ, "d8 is the black queen");
    CHECK(piece_at(&pos, sq("e4")) == EMPTY, "e4 is empty");
    CHECK(piece_at(&pos, sq("h7")) == BP, "h7 is a black pawn");
    CHECK(pos.side_to_move == WHITE, "white to move");
    CHECK(pos.castling == CASTLE_ALL, "all four castling rights");
    CHECK(pos.ep_square == NO_SQUARE, "no ep square");
    CHECK(pos.halfmove_clock == 0 && pos.fullmove_number == 1, "counters 0 and 1");
    CHECK(pos.king_sq[WHITE] == 4 && pos.king_sq[BLACK] == 60, "king squares e1=4, e8=60");
    CHECK(pos.ply == 0, "undo stack empty after parse");
    CHECK(board_consistent(&pos), "parsed position is consistent");
}

static void test_square_helpers(void)
{
    char buf[3];
    CHECK(sq("a1") == 0 && sq("h1") == 7 && sq("a2") == 8 && sq("h8") == 63, "a1=0 h1=7 a2=8 h8=63");
    CHECK(sq("e4") == 28, "e4 = 28 (file fastest)");
    CHECK(sq("i1") == NO_SQUARE && sq("a9") == NO_SQUARE && sq("") == NO_SQUARE, "bad names rejected");
    CHECK(str_to_square(NULL) == NO_SQUARE, "NULL square name");
    square_to_str(28, buf);
    CHECK(strcmp(buf, "e4") == 0, "28 -> e4, got %s", buf);
    CHECK(char_to_piece('N') == WN && char_to_piece('q') == BQ && char_to_piece('x') == EMPTY, "piece letters");
    CHECK(piece_color(BP) == BLACK && piece_type(BQ) == QUEEN && piece_type(WQ) == QUEEN, "colour/type split");
    CHECK(make_piece(BLACK, ROOK) == BR && make_piece(WHITE, KING) == WK, "make_piece");
}

static void test_round_trips(void)
{
    /* Every string here is one our own fen_write would produce (ep always written). */
    static const char *const fens[] = {
        START_FEN,
        KIWIPETE,
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",    /* ep, black to move */
        "rnbqkbnr/pp1ppppp/8/2pP4/8/8/PPP1PPPP/RNBQKBNR w KQkq c6 0 3",   /* ep, white to move */
        "4k3/8/8/8/8/8/8/4K2R w K - 0 1",                                 /* single right */
        "r3k3/8/8/8/8/8/8/4K3 b q - 0 1",
        "4k3/8/8/8/8/8/8/4K3 w - - 99 500",                               /* big counters */
        "4k3/8/8/8/8/8/8/4K3 b - - 9999 9999",
        "8/8/8/8/8/8/8/K6k w - - 0 1",                                    /* kings on the edge */
        "Q7/8/8/8/8/8/8/K6k b - - 0 1",                                   /* ex-pawn promoted */
        "4k3/8/8/8/8/8/8/r3K3 w - - 0 1",                                 /* side to move in check: fine */
    };
    for (size_t i = 0; i < sizeof fens / sizeof fens[0]; i++) {
        Position pos;
        char out[FEN_MAX_LEN];
        int err = fen_parse(&pos, fens[i]);
        CHECK(err == FEN_OK, "'%s' must parse, got %s", fens[i], fen_error_string(err));
        if (err != FEN_OK) continue;
        fen_write(&pos, out, sizeof out);
        CHECK(strcmp(out, fens[i]) == 0, "round trip\n   in : %s\n   out: %s", fens[i], out);
    }
}

/* Lenient whitespace: parse -> write -> parse must give the same position
 * even when the input is not in canonical form. */
static void test_reparse_equivalence(void)
{
    static const char *const fens[] = {
        "  rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR   w\tKQkq -  0 1  ",
        START_FEN "\n",
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w qkQK - 0 1",   /* any order of rights */
        "4k3/8/8/8/8/8/8/4K3 w - - 007 0001",                        /* leading zeros */
    };
    for (size_t i = 0; i < sizeof fens / sizeof fens[0]; i++) {
        Position a, b;
        char out[FEN_MAX_LEN];
        int err = fen_parse(&a, fens[i]);
        CHECK(err == FEN_OK, "'%s' must parse, got %s", fens[i], fen_error_string(err));
        if (err != FEN_OK) continue;
        fen_write(&a, out, sizeof out);
        CHECK(fen_parse(&b, out) == FEN_OK, "our own output must parse: %s", out);
        CHECK(same_position(&a, &b), "reparse differs for '%s' -> '%s'", fens[i], out);
    }
    Position pos;
    CHECK(fen_parse(&pos, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w qkQK - 0 1") == FEN_OK &&
          pos.castling == CASTLE_ALL, "rights in any order still set all bits");
}

static void test_ep_fields(void)
{
    Position pos;
    CHECK(fen_parse(&pos, "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1") == FEN_OK, "ep e3");
    CHECK(pos.ep_square == sq("e3"), "ep_square is e3 (%d)", pos.ep_square);
    CHECK(pos.side_to_move == BLACK, "black to move");
    CHECK(fen_parse(&pos, "rnbqkbnr/pp1ppppp/8/2pP4/8/8/PPP1PPPP/RNBQKBNR w KQkq c6 0 3") == FEN_OK, "ep c6");
    CHECK(pos.ep_square == sq("c6"), "ep_square is c6 (%d)", pos.ep_square);
}

/* ----------------------------------------------------- malformed input -- */

typedef struct { const char *fen; int want; const char *why; } BadFen;

static const BadFen BAD[] = {
    /* structure */
    { "",                                                                  FEN_ERR_FIELDS,      "empty string" },
    { "garbage",                                                           FEN_ERR_FIELDS,      "one word" },
    { "   \t\n ",                                                          FEN_ERR_FIELDS,      "only whitespace" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -",              FEN_ERR_FIELDS,      "missing both counters" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0",            FEN_ERR_FIELDS,      "missing fullmove" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1 extra",    FEN_ERR_TRAILING,    "trailing garbage" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1 ;D1 20",   FEN_ERR_TRAILING,    "EPD tail not stripped" },
    /* placement */
    { "rnbqkbnr/pppppppp/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",            FEN_ERR_RANK_COUNT,  "7 ranks" },
    { "rnbqkbnr/pppppppp/8/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",        FEN_ERR_RANK_COUNT,  "9 ranks" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR/ w KQkq - 0 1",         FEN_ERR_RANK_COUNT,  "trailing slash" },
    { "rnbqkbnr/ppppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",         FEN_ERR_RANK_WIDTH,  "9 pawns in one rank" },
    { "rnbqkbnr/ppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",           FEN_ERR_RANK_WIDTH,  "7 squares in one rank" },
    { "rnbqkbnr/pppppppp/7/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",          FEN_ERR_RANK_WIDTH,  "digit 7 on an empty rank" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR1 w KQkq - 0 1",         FEN_ERR_RANK_WIDTH,  "extra square at the end" },
    { "/rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",         FEN_ERR_RANK_WIDTH,  "leading slash" },
    { "rnbqkbnr//pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",         FEN_ERR_RANK_WIDTH,  "double slash" },
    { "rnbqkbnr/pppppppp/9/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",          FEN_ERR_BAD_CHAR,    "digit 9" },
    { "rnbqkbnr/pppppppp/0/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",          FEN_ERR_BAD_CHAR,    "digit 0" },
    { "rnbqkbnr/pppppppp/44/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",         FEN_ERR_BAD_CHAR,    "two digits in a row" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKXNR w KQkq - 0 1",          FEN_ERR_BAD_CHAR,    "unknown letter X" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQK BNR w KQkq - 0 1",         FEN_ERR_TRAILING,    "space inside placement (= 7 fields)" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQ\xe2\x99\x94" "BNR w KQkq - 0 1", FEN_ERR_BAD_CHAR,  "UTF-8 chess glyph" },
    /* kings and pawns */
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKKNR w KQkq - 0 1",          FEN_ERR_KINGS,       "two white kings" },
    { "rnbq1bnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",          FEN_ERR_KINGS,       "no black king" },
    { "8/8/8/8/8/8/8/8 w - - 0 1",                                         FEN_ERR_KINGS,       "empty board" },
    { "8/8/8/3kK3/8/8/8/8 w - - 0 1",                                      FEN_ERR_KINGS,       "kings touching" },
    { "8/8/8/3k4/4K3/8/8/8 w - - 0 1",                                     FEN_ERR_KINGS,       "kings touching diagonally" },
    { "P3k3/8/8/8/8/8/8/4K3 w - - 0 1",                                    FEN_ERR_PAWN_RANK,   "white pawn on rank 8" },
    { "4k3/8/8/8/8/8/8/p3K3 w - - 0 1",                                    FEN_ERR_PAWN_RANK,   "black pawn on rank 1" },
    { "4k3/8/8/8/8/P7/PPPPPPPP/4K3 w - - 0 1",                             FEN_ERR_PIECE_COUNT, "nine white pawns" },
    { "4k3/8/8/8/8/RRRRRRRR/RRRRRRRR/4K3 w - - 0 1",                       FEN_ERR_PIECE_COUNT, "17 white pieces" },
    /* side to move */
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR x KQkq - 0 1",          FEN_ERR_SIDE,        "side x" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR W KQkq - 0 1",          FEN_ERR_SIDE,        "upper-case W" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR wb KQkq - 0 1",         FEN_ERR_SIDE,        "two letters" },
    /* castling */
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkqK - 0 1",         FEN_ERR_CASTLING,    "five letters" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KK - 0 1",            FEN_ERR_CASTLING,    "repeated letter" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQxq - 0 1",          FEN_ERR_CASTLING,    "letter x" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w -- - 0 1",            FEN_ERR_CASTLING,    "double dash" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBKQBNR w KQkq - 0 1",          FEN_ERR_CASTLING,    "rights but king on d1" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBN1 w KQkq - 0 1",          FEN_ERR_CASTLING,    "K right but no rook on h1" },
    { "1nbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",          FEN_ERR_CASTLING,    "q right but no rook on a8" },
    /* en passant */
    { "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e9 0 1",       FEN_ERR_EP_SQUARE,   "ep e9" },
    { "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e 0 1",        FEN_ERR_EP_SQUARE,   "ep one char" },
    { "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e33 0 1",      FEN_ERR_EP_SQUARE,   "ep three chars" },
    { "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e4 0 1",       FEN_ERR_EP_SQUARE,   "ep on rank 4" },
    { "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e3 0 1",       FEN_ERR_EP_SQUARE,   "ep rank 3 with white to move" },
    { "rnbqkbnr/pp1ppppp/8/2pP4/8/8/PPP1PPPP/RNBQKBNR b KQkq c6 0 3",      FEN_ERR_EP_SQUARE,   "ep rank 6 with black to move" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq e3 0 1",         FEN_ERR_EP_SQUARE,   "ep but no pawn on e4" },
    { "rnbqkbnr/pppppppp/8/8/4P3/4N3/PPPP1PPP/R1BQKBNR b KQkq e3 0 1",     FEN_ERR_EP_SQUARE,   "ep square occupied" },
    { "rnbqkbnr/pppppppp/8/8/4P3/8/PPPPNPPP/RNBQKB1R b KQkq e3 0 1",       FEN_ERR_EP_SQUARE,   "ep but origin square e2 not empty" },
    /* counters */
    { "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 5 1",       FEN_ERR_COUNTER,     "ep set but halfmove 5" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - -1 1",         FEN_ERR_COUNTER,     "negative halfmove" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - abc 1",        FEN_ERR_COUNTER,     "halfmove not a number" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0x1 1",        FEN_ERR_COUNTER,     "hex halfmove" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 1.5 1",        FEN_ERR_COUNTER,     "fractional halfmove" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 99999999999999999999 1", FEN_ERR_COUNTER, "halfmove overflows int" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 10000 1",      FEN_ERR_COUNTER,     "halfmove above 9999" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 0",          FEN_ERR_COUNTER,     "fullmove 0" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1x",         FEN_ERR_COUNTER,     "letter glued to fullmove" },
    { "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 99999999999999999999", FEN_ERR_COUNTER, "fullmove overflows int" },
    /* the side that is not to move may not be in check */
    { "4k3/8/8/8/8/8/8/r3K3 b - - 0 1",                                    FEN_ERR_IN_CHECK,    "black to move, white king attacked by rook" },
    { "4k3/8/8/8/8/8/3p4/4K3 b - - 0 1",                                   FEN_ERR_IN_CHECK,    "black to move, white king attacked by pawn" },
    { "4k3/8/5N2/8/8/8/8/4K3 w - - 0 1",                                   FEN_ERR_IN_CHECK,    "white to move, black king attacked by knight" },
};

static void test_malformed(void)
{
    size_t n = sizeof BAD / sizeof BAD[0];
    CHECK(n >= 20, "need at least 20 malformed FENs, have %zu", n);
    for (size_t i = 0; i < n; i++) {
        Position pos;
        board_init(&pos);
        int err = fen_parse(&pos, BAD[i].fen);
        CHECK(err != FEN_OK, "accepted malformed FEN (%s): '%s'", BAD[i].why, BAD[i].fen);
        CHECK(err == BAD[i].want, "%s: '%s'\n   want %s\n   got  %s", BAD[i].why, BAD[i].fen,
              fen_error_string(BAD[i].want), fen_error_string(err));
    }
    printf("     %zu malformed FENs rejected\n", n);
}

/* A rejected FEN must leave the caller's position untouched. */
static void test_failure_leaves_position_alone(void)
{
    Position pos, before;
    CHECK(fen_parse(&pos, KIWIPETE) == FEN_OK, "kiwipete parses");
    before = pos;
    CHECK(fen_parse(&pos, "8/8/8/8/8/8/8/8 w - - 0 1") != FEN_OK, "empty board rejected");
    CHECK(fen_parse(&pos, START_FEN " trailing") != FEN_OK, "trailing garbage rejected");
    CHECK(same_position(&pos, &before), "position changed by a failed parse");
}

/* Fill big[0..HUGE) with `c`, then overwrite the start with `head` and the
 * end with `tail` (both may be ""). Result is NUL-terminated. */
enum { HUGE = 1 << 20 };   /* 1 MiB */

static void fill(char *big, char c, const char *head, const char *tail)
{
    memset(big, c, HUGE);
    big[HUGE] = '\0';
    memcpy(big, head, strlen(head));
    memcpy(big + HUGE - strlen(tail), tail, strlen(tail));
}

static void test_null_and_huge_input(void)
{
    Position pos;
    CHECK(fen_parse(NULL, START_FEN) == FEN_ERR_NULL, "NULL position");
    CHECK(fen_parse(&pos, NULL) == FEN_ERR_NULL, "NULL string");

    char *big = malloc(HUGE + 1);
    if (big == NULL) { CHECK(false, "malloc failed"); return; }

    fill(big, 'r', "", "");
    CHECK(fen_parse(&pos, big) == FEN_ERR_FIELDS, "1 MiB of rooks and nothing else");
    fill(big, 'r', "", " w - - 0 1");
    CHECK(fen_parse(&pos, big) == FEN_ERR_RANK_WIDTH, "1 MiB-wide first rank");
    fill(big, '/', "", " w - - 0 1");
    CHECK(fen_parse(&pos, big) == FEN_ERR_RANK_WIDTH, "1 MiB of slashes");
    fill(big, '1', "", " w - - 0 1");
    CHECK(fen_parse(&pos, big) == FEN_ERR_BAD_CHAR, "1 MiB of digits");
    fill(big, ' ', "", "");
    CHECK(fen_parse(&pos, big) == FEN_ERR_FIELDS, "1 MiB of spaces");
    fill(big, '9', "4k3/8/8/8/8/8/8/4K3 w - - ", " 1");
    CHECK(fen_parse(&pos, big) == FEN_ERR_COUNTER, "1 MiB-digit halfmove clock");
    fill(big, 'K', "4k3/8/8/8/8/8/8/4K3 w ", " - 0 1");
    CHECK(fen_parse(&pos, big) == FEN_ERR_CASTLING, "1 MiB castling field");

    /* A valid FEN followed by a megabyte of whitespace is still valid. */
    fill(big, ' ', START_FEN, "");
    CHECK(fen_parse(&pos, big) == FEN_OK, "valid FEN + 1 MiB of spaces");
    fill(big, ' ', START_FEN, "x");
    CHECK(fen_parse(&pos, big) == FEN_ERR_TRAILING, "valid FEN + 1 MiB of spaces + garbage");
    free(big);
}

static void test_write_truncation(void)
{
    Position pos;
    char buf[FEN_MAX_LEN];
    CHECK(fen_parse(&pos, KIWIPETE) == FEN_OK, "kiwipete parses");

    memset(buf, 'X', sizeof buf);
    fen_write(&pos, buf, 0);
    CHECK(buf[0] == 'X', "n == 0 must not write anything");

    fen_write(&pos, buf, 1);
    CHECK(buf[0] == '\0', "n == 1 writes just the terminator");

    fen_write(&pos, buf, 10);
    CHECK(strlen(buf) == 9 && strncmp(buf, KIWIPETE, 9) == 0, "n == 10 keeps 9 chars + NUL, got '%s'", buf);

    fen_write(&pos, buf, sizeof buf);
    CHECK(strcmp(buf, KIWIPETE) == 0, "full write, got '%s'", buf);
}

static void test_error_strings(void)
{
    for (int e = 0; e < FEN_ERR_COUNT; e++)
        CHECK(fen_error_string(e) != NULL && fen_error_string(e)[0] != '\0', "message for code %d", e);
    CHECK(strcmp(fen_error_string(-1), "unknown FEN error") == 0, "negative code");
    CHECK(strcmp(fen_error_string(FEN_ERR_COUNT), "unknown FEN error") == 0, "code out of range");
}

int main(void)
{
    test_start_position_fields();
    test_square_helpers();
    test_round_trips();
    test_reparse_equivalence();
    test_ep_fields();
    test_malformed();
    test_failure_leaves_position_alone();
    test_null_and_huge_input();
    test_write_truncation();
    test_error_strings();

    printf("test_fen: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_TEST_FAILURE;
}
