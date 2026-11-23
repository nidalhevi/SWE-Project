"""A game decoded from photos, as the GUI shows it.

The vision side (vision/scripts/run_game.py --json) writes one JSON file per
game: the moves and the position after every move. This module only reads
that file. It does not import Qt, so it can be tested without a display.
Format: docs/GUI_INTEGRATION.md.
"""

import json
from dataclasses import dataclass

from models import Move, PositionSnapshot

SUPPORTED_VERSION = 1


@dataclass(frozen=True)
class PhotoPly:
    """One move of a photo game and the position it leads to.

    recovered: the photo was unreadable and the move was worked out from
    the next photo, so it deserves a second look.
    """

    number: int
    move: Move
    position: PositionSnapshot
    photo: str | None = None
    recovered: bool = False
    corrected: bool = False

    @property
    def label(self) -> str:
        """Move-list text: '1. e4', '1... e5', with '?' if recovered."""
        turn = (self.number + 1) // 2
        dots = "." if self.number % 2 == 1 else "..."
        return f"{turn}{dots} {self.move.san}" + (" ?" if self.recovered else "")


@dataclass(frozen=True)
class PhotoGame:
    """A whole photo game. Index 0 is the start; index n is after ply n."""

    start: PositionSnapshot
    plies: tuple[PhotoPly, ...]
    status: str
    pgn: str

    def position_at(self, index: int) -> PositionSnapshot:
        """Position after `index` plies. Requires 0 <= index <= len(plies)."""
        if not 0 <= index <= len(self.plies):
            raise IndexError("No such ply in this game.")
        return self.start if index == 0 else self.plies[index - 1].position


def game_from_record(record: dict) -> PhotoGame:
    """Build a PhotoGame from the parsed JSON. Raises ValueError if malformed."""
    try:
        if record["version"] != SUPPORTED_VERSION:
            raise ValueError(f"Unsupported game record version: {record['version']}")
        plies = []
        for expected, entry in enumerate(record["plies"], start=1):
            if entry["n"] != expected:
                raise ValueError("Plies are not numbered 1, 2, 3, ...")
            uci = Move.from_uci(entry["uci"])
            move = Move(uci.from_square, uci.to_square, uci.promotion, entry["san"])
            plies.append(PhotoPly(
                number=expected,
                move=move,
                position=PositionSnapshot(entry["fen_after"]),
                photo=entry.get("photo"),
                recovered=bool(entry.get("recovered", False)),
                corrected=bool(entry.get("corrected", False)),
            ))
        game = PhotoGame(
            start=PositionSnapshot(record["start_fen"]),
            plies=tuple(plies),
            status=str(record["status"]),
            pgn=str(record["pgn"]),
        )
        if game.position_at(len(plies)).fen != PositionSnapshot(record["final_fen"]).fen:
            raise ValueError("final_fen does not match the last ply.")
        return game
    except (KeyError, TypeError) as error:
        raise ValueError(f"Malformed game record: {error!r}") from error


def load_photo_game(path: str) -> PhotoGame:
    """Read a game record file. Raises ValueError or OSError."""
    with open(path, encoding="utf-8") as file:
        try:
            record = json.load(file)
        except json.JSONDecodeError as error:
            raise ValueError(f"Not a JSON file: {error}") from error
    if not isinstance(record, dict):
        raise ValueError("A game record must be a JSON object.")
    return game_from_record(record)
