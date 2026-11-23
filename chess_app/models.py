"""Shared data records for the chess application.

These classes contain data and perform basic format checks.
Chess legality remains the C referee's responsibility.

Requires Python 3.10 or newer.
"""

from dataclasses import dataclass


FILES = "abcdefgh"
PIECE_CODES = "PNBRQKpnbrqk"

STARTING_FEN = (
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    " w KQkq - 0 1"
)


def is_square(value: str) -> bool:
    """Return whether value is a coordinate such as 'e4'."""
    return (
        len(value) == 2
        and value[0] in FILES
        and value[1] in "12345678"
    )


def _parse_placement(placement: str) -> dict[str, str]:
    """Convert the first FEN field into square -> piece entries.

    Checks the board's encoding, not whether the position is legal.
    """
    ranks = placement.split("/")

    if len(ranks) != 8:
        raise ValueError("FEN piece placement must contain eight ranks.")

    pieces = {}

    for row, encoded_rank in enumerate(ranks):
        file_index = 0
        previous_was_digit = False

        for character in encoded_rank:
            if character in "12345678":
                if previous_was_digit:
                    raise ValueError(
                        "Consecutive empty-square digits are invalid."
                    )

                file_index += int(character)
                previous_was_digit = True

            elif character in PIECE_CODES:
                if file_index >= 8:
                    raise ValueError("A FEN rank exceeds eight squares.")

                square = f"{FILES[file_index]}{8 - row}"
                pieces[square] = character
                file_index += 1
                previous_was_digit = False

            else:
                raise ValueError(
                    f"Invalid FEN piece-placement character: {character!r}"
                )

            if file_index > 8:
                raise ValueError("A FEN rank exceeds eight squares.")

        if file_index != 8:
            raise ValueError("Each FEN rank must describe eight squares.")

    return pieces


@dataclass(frozen=True)
class PositionSnapshot:
    """A standard-chess position encoded by all six FEN fields.

    Construct a new snapshot whenever the accepted position changes.
    Selection, highlights, and board orientation are GUI state and
    do not belong here.

    FEN does not contain the move history needed to detect repetition.
    That history will live in the game tree.
    """

    fen: str

    def __post_init__(self) -> None:
        fields = self.fen.split()

        if len(fields) != 6:
            raise ValueError("A complete FEN must contain six fields.")

        placement, turn, castling, en_passant, halfmove, fullmove = fields

        _parse_placement(placement)

        if turn not in ("w", "b"):
            raise ValueError("FEN active color must be 'w' or 'b'.")

        if castling != "-":
            # Standard chess uses this order and allows each right once.
            expected = "".join(c for c in "KQkq" if c in castling)

            if castling != expected:
                raise ValueError("Invalid standard-chess castling field.")

        if en_passant != "-":
            if not is_square(en_passant) or en_passant[1] not in "36":
                raise ValueError(
                    "En passant target must be '-' or a rank 3/6 square."
                )

        for value in (halfmove, fullmove):
            if not value or any(c not in "0123456789" for c in value):
                raise ValueError("FEN counters must be decimal integers.")

        if int(fullmove) < 1:
            raise ValueError("Fullmove number must be at least 1.")

        # Normalize whitespace once during construction.
        object.__setattr__(self, "fen", " ".join(fields))

    @property
    def pieces(self) -> dict[str, str]:
        """Return a fresh display dictionary.

        Mutating this dictionary cannot change the snapshot.
        Uppercase pieces are White; lowercase pieces are Black.
        """
        return _parse_placement(self.fen.split()[0])

    @property
    def turn(self) -> str:
        """'w' for White or 'b' for Black."""
        return self.fen.split()[1]

    @property
    def turn_name(self) -> str:
        return "White" if self.turn == "w" else "Black"

    @property
    def castling_rights(self) -> str:
        return self.fen.split()[2]

    @property
    def en_passant_target(self) -> str | None:
        value = self.fen.split()[3]
        return None if value == "-" else value

    @property
    def halfmove_clock(self) -> int:
        return int(self.fen.split()[4])

    @property
    def fullmove_number(self) -> int:
        return int(self.fen.split()[5])


@dataclass(frozen=True)
class Move:
    """A standard-chess move description.

    This records a proposed or accepted move; construction alone does
    not establish legality.

    promotion uses lowercase UCI letters: q, r, b, or n.
    san is optional because the referee may supply it after acceptance.
    """

    from_square: str
    to_square: str
    promotion: str | None = None
    san: str | None = None

    def __post_init__(self) -> None:
        if not is_square(self.from_square):
            raise ValueError("Invalid origin square.")

        if not is_square(self.to_square):
            raise ValueError("Invalid destination square.")

        if self.from_square == self.to_square:
            raise ValueError("Origin and destination must differ.")

        if self.promotion not in (None, "q", "r", "b", "n"):
            raise ValueError("Promotion must be q, r, b, n, or None.")

    @property
    def uci(self) -> str:
        """Examples: 'e2e4', 'e7e8q'."""
        return self.from_square + self.to_square + (self.promotion or "")

    @classmethod
    def from_uci(cls, text: str) -> "Move":
        """Construct a move from standard UCI coordinate notation."""
        if len(text) not in (4, 5):
            raise ValueError("A UCI move must contain four or five characters.")

        return cls(
            from_square=text[:2],
            to_square=text[2:4],
            promotion=text[4] if len(text) == 5 else None,
        )


@dataclass(frozen=True)
class AnalysisResult:
    """One engine analysis update for a particular request.

    Score convention: always White's perspective.
        score_cp = 125 means +1.25 pawns for White.
        mate_in = 3 means White can force mate in three moves.
        mate_in = -3 means Black can force mate in three moves.

    None means that information has not been supplied.
    The engine adapter must normalize the engine's score perspective.

    request_id distinguishes separate analysis requests, even when
    the same position is analyzed again.
    """

    request_id: int
    position: PositionSnapshot
    depth: int
    score_cp: int | None = None
    mate_in: int | None = None
    principal_variation: tuple[Move, ...] = ()

    def __post_init__(self) -> None:
        if self.request_id < 0:
            raise ValueError("Request ID cannot be negative.")

        if self.depth < 0:
            raise ValueError("Search depth cannot be negative.")

        if self.score_cp is not None and self.mate_in is not None:
            raise ValueError(
                "Supply a centipawn score or a mate score, not both."
            )

    @property
    def best_move(self) -> Move | None:
        """The first move of the suggested continuation, if available."""
        if self.principal_variation:
            return self.principal_variation[0]

        return None