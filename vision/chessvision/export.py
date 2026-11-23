"""game_record: a decoded game as one plain dictionary, for programs that are not Python (the GUI).

The GUI runs `run_game.py --json game.json` as a subprocess and reads the file. It needs the
position after every ply, not only the moves, so that it can show any point of the game without
replaying it. Format (version 1):

    {"version": 1, "start_fen": ..., "final_fen": ..., "status": "ongoing" | "checkmate" | ...,
     "pgn": "...",
     "plies": [{"n": 1, "san": "e4", "uci": "e2e4", "fen_after": ..., "photo": "IMG_0001.jpg" | null,
                "confidence": 12.3, "recovered": false, "corrected": false}, ...]}

`recovered`: the photo for this ply was unreadable and the ply was worked out from the next photo.
`corrected`: a person chose this move at the correction prompt.
"""
from __future__ import annotations

import json
from typing import List, Optional, Sequence

from .engine import START_FEN, EngineClient
from .pipeline import GameResult

VERSION = 1


def game_record(result: GameResult, engine: EngineClient, start_fen: str = START_FEN,
                photos: Optional[Sequence[Optional[str]]] = None, headers: Optional[dict] = None) -> dict:
    """Describe `result` as a dictionary (see the module docstring).

    Precondition: `engine` is open; `result` was decoded from `start_fen`; `photos`, if given, has
    one entry per ply. Postcondition: the engine holds the final position of the game again.
    Raises ValueError if replaying the moves does not end in `result.final_fen`.
    """
    if photos is not None and len(photos) != len(result.plies):
        raise ValueError("photos must have one entry per ply")
    engine.position(start_fen)
    plies: List[dict] = []
    for i, ply in enumerate(result.plies):
        engine.move(ply.uci)
        plies.append({"n": i + 1, "san": ply.san, "uci": ply.uci, "fen_after": engine.fen(),
                      "photo": photos[i] if photos is not None else None,
                      "confidence": round(float(ply.confidence), 2),
                      "recovered": bool(ply.recovered), "corrected": bool(ply.asked)})
    final = plies[-1]["fen_after"] if plies else engine.fen()
    if final != result.final_fen:
        raise ValueError("replayed game ends in %s, decoder reported %s" % (final, result.final_fen))
    return {"version": VERSION, "start_fen": start_fen, "final_fen": final, "status": result.status,
            "pgn": result.pgn(headers), "plies": plies}


def write_game_record(path: str, record: dict) -> None:
    """Write `record` as JSON to `path`."""
    with open(path, "w") as f:
        json.dump(record, f, indent=1)
        f.write("\n")
