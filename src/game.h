/* game.h — is the game over, and why (pass 2).
 *
 * The verdicts and their precedence mirror python-chess, which the
 * differential test uses as the oracle: checkmate, stalemate, insufficient
 * material, fifty-move rule, threefold repetition. The first that applies
 * wins. Draws are reported as soon as they apply (nobody has to "claim").
 */
#ifndef CHESS_GAME_H
#define CHESS_GAME_H

#include "types.h"

typedef enum {
    ONGOING = 0,
    CHECKMATE,
    STALEMATE,
    INSUFFICIENT_MATERIAL,
    FIFTY_MOVES,
    THREEFOLD_REPETITION,
    GAME_STATE_NB
} GameState;

/* Pre: board_consistent(pos), side not to move is not in check.
 * Post: the verdict for the side to move, with the precedence above. */
GameState game_state(const Position *pos);

/* Pre: board_consistent(pos).  Post: how many times the current position
 * (same pieces, side, castling rights and legal en-passant chance) has
 * occurred since the last pawn move or capture, counting this one. */
int repetition_count(const Position *pos);

/* Pre: board_consistent(pos).  Post: true iff neither side can ever deliver
 * mate, judged by material only (python-chess's has_insufficient_material). */
bool insufficient_material(const Position *pos);

/* Pre: 0 <= s < GAME_STATE_NB.  Post: "ongoing", "checkmate", "stalemate",
 * "insufficient-material", "fifty-moves" or "threefold-repetition". */
const char *game_state_string(GameState s);

/* Pre: s is the verdict for pos.  Post: "1-0", "0-1", "1/2-1/2" or "*". */
const char *game_result_string(const Position *pos, GameState s);

#endif /* CHESS_GAME_H */
