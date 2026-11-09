"""EngineClient: one long-lived `chess batch` process, driven over stdin/stdout.

The protocol (src/play.h) is one line in, one flushed line out:
  position <fen> -> ok | error <why>        move <uci> -> ok | error illegal move
  undo           -> ok | error ...          moves      -> sorted UCI, space-separated
  status         -> ongoing|checkmate|...   san <uci>  -> SAN | error illegal move
  fen            -> the FEN                 quit
The engine is the single source of truth for legality, SAN and game state;
this module never reimplements any chess rule.
"""
from __future__ import annotations

import os
import subprocess
from typing import List, Optional

DEFAULT_BINARY = os.environ.get(
    "CHESS_BIN",
    os.path.join(os.path.dirname(__file__), "..", "..", "build", "release", "chess"),
)
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class EngineError(RuntimeError):
    """The engine answered `error ...` or died."""


class EngineClient:
    """Context manager around a `chess batch` subprocess.

    Precondition: `binary` is an executable built from this repo (`make release`).
    Postcondition on close(): the subprocess has exited.
    """

    def __init__(self, binary: Optional[str] = None):
        self.binary = os.path.abspath(binary or DEFAULT_BINARY)
        if not os.access(self.binary, os.X_OK):
            raise EngineError("engine binary not found or not executable: %s (run `make release`)" % self.binary)
        self._proc = subprocess.Popen(
            [self.binary, "batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    # -- low level --------------------------------------------------------
    def _ask(self, line: str) -> str:
        """Send one command, return the one reply line. Raises EngineError on `error`."""
        assert "\n" not in line
        p = self._proc
        if p.poll() is not None:
            raise EngineError("engine exited with code %d" % p.returncode)
        p.stdin.write(line + "\n")
        p.stdin.flush()
        reply = p.stdout.readline()
        if reply == "":
            err = p.stderr.read()
            raise EngineError("engine closed its output after %r: %s" % (line, err.strip()))
        reply = reply.rstrip("\n")
        if reply.startswith("error"):
            raise EngineError("%s -> %s" % (line, reply))
        return reply

    # -- protocol -----------------------------------------------------------
    def position(self, fen: str = START_FEN) -> None:
        """Replace the game with `fen` (history is cleared)."""
        self._ask("position " + fen.strip())

    def move(self, uci: str) -> None:
        """Play `uci`; raises EngineError if illegal."""
        self._ask("move " + uci)

    def undo(self) -> None:
        self._ask("undo")

    def moves(self) -> List[str]:
        """Legal moves in UCI, sorted."""
        reply = self._ask("moves")
        return reply.split() if reply else []

    def san(self, uci: str) -> str:
        """SAN for a legal move in the current position (does not play it)."""
        return self._ask("san " + uci)

    def fen(self) -> str:
        return self._ask("fen")

    def status(self) -> str:
        """ongoing | checkmate | stalemate | insufficient-material | fifty-moves | threefold-repetition."""
        return self._ask("status")

    def close(self) -> None:
        p = self._proc
        if p.poll() is None:
            try:
                p.stdin.write("quit\n")
                p.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()

    def __enter__(self) -> "EngineClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
