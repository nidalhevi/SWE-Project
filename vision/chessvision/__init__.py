"""chessvision: photo -> move -> PGN front end for the chess-c engine.

Pass V1 contains only the engine bridge, the legal-move decoder and the
pipeline that turns a sequence of per-square observations into a PGN.
"""
from .engine import EngineClient, EngineError
from .decoder import decode_move, Candidate
from .pipeline import decode_game, GameResult

__all__ = ["EngineClient", "EngineError", "decode_move", "Candidate", "decode_game", "GameResult"]
