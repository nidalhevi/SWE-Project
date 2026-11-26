"""Standard algebraic notation (SAN) for engine lines: "Nf3" instead of "g1f3".

Stockfish speaks UCI coordinates. Turning a whole line into SAN needs the rules
(captures, disambiguation such as Nbd2, castling, check and mate), and the C
referee is this project's only source of rules, so the GUI does not reimplement
them. NotationService runs its OWN `chess batch` process: converting a line
plays its moves, which must never touch the referee that holds the game.

Analysis updates arrive several times per position. Only one line is converted
at a time; a newer request replaces any waiting one, and finished lines are
cached. If the helper process fails, `available` turns False and callers keep
showing UCI, so analysis never depends on it.
"""
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from models import Move, PositionSnapshot
from referee_client import RefereeClient

MAX_PLIES = 24      # longer engine lines are cut here: two round trips per ply
CACHE_SIZE = 128


@dataclass(frozen=True)
class NotationLine:
    """SAN for `ucis` played from `fen`. `sans` may be shorter than `ucis` if a
    move was rejected; the rest of the line has no SAN."""
    fen: str
    ucis: tuple[str, ...]
    sans: tuple[str, ...]


def format_line(fen: str, sans, ucis=()) -> str:
    """Numbered line from the position's move number and side to move.

    White to move: "12. Nf3 Nc6 13. Bb5". Black to move: "12... Nc6 13. Bb5".
    Moves without SAN (ucis beyond len(sans)) are appended in UCI.
    """
    fields = fen.split()
    white = fields[1] == 'w'
    number = int(fields[5])
    tokens = []
    moves = list(sans) + list(ucis[len(sans):])
    for i, san in enumerate(moves):
        if white:
            tokens.append(f'{number}. {san}')
        elif i == 0:
            tokens.append(f'{number}... {san}')
        else:
            tokens.append(san)
        if not white:
            number += 1
        white = not white
    return ' '.join(tokens)


@dataclass
class _Job:
    fen: str
    ucis: tuple[str, ...]
    ids: dict            # referee request id -> ('load' | 'san' | 'play', ply index)
    sans: list
    failed: bool = False


class NotationService(QObject):
    """Convert engine lines to SAN in the background.

    line_ready(NotationLine) answers request(); unavailable() tells the caller
    to fall back to UCI; closed() follows close() (or a failed start).
    """

    line_ready = Signal(object)
    unavailable = Signal()
    closed = Signal()

    def __init__(self, parent=None, timeout_ms: int = 5000):
        super().__init__(parent)
        self._referee = RefereeClient(self, timeout_ms=timeout_ms)
        self._referee.ready.connect(self._on_ready)
        self._referee.completed.connect(self._on_completed)
        self._referee.failed.connect(self._on_failed)
        self._referee.fatal_error.connect(self._on_fatal)
        self._referee.closed.connect(self._on_closed)
        self._ready = False
        self._available = True
        self._started = False
        self._closing = False
        self._closed = False
        self._job = None
        self._waiting = None      # (fen, ucis) to convert after the current job
        self._cache = OrderedDict()

    @property
    def available(self) -> bool:
        return self._available and not self._closing

    def start(self, program: str, arguments=None) -> None:
        self._started = True
        self._referee.start(program, arguments)

    def request(self, fen: str, moves) -> None:
        """Ask for the SAN of `moves` (Move objects) from `fen`; answered by line_ready."""
        ucis = tuple(move.uci for move in moves)[:MAX_PLIES]
        if not ucis or not self.available:
            return
        key = (fen, ucis)
        if key in self._cache:
            self._cache.move_to_end(key)
            self.line_ready.emit(NotationLine(fen, ucis, self._cache[key]))
            return
        if self._job is not None and (self._job.fen, self._job.ucis) == key:
            return
        self._waiting = key
        self._pump()

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._waiting = None
        if not self._started:
            self._emit_closed()
        else:
            self._referee.close()

    # -- internals ---------------------------------------------------------
    def _on_ready(self):
        self._ready = True
        self._pump()

    def _pump(self):
        if not self._ready or self._job is not None or self._waiting is None or not self.available:
            return
        fen, ucis = self._waiting
        self._waiting = None
        job = _Job(fen, ucis, {}, [])
        try:
            job.ids[self._referee.load_position(PositionSnapshot(fen))] = ('load', -1)
            for i, uci in enumerate(ucis):
                move = Move.from_uci(uci)
                job.ids[self._referee.san(move)] = ('san', i)
                job.ids[self._referee.play_move(move)] = ('play', i)
        except (RuntimeError, ValueError):
            self._on_fatal('could not queue the line')
            return
        self._job = job

    def _owner(self, request_id):
        job = self._job
        return (job, job.ids.pop(request_id)) if job is not None and request_id in job.ids else (None, None)

    def _on_completed(self, request_id, action, result):
        job, step = self._owner(request_id)
        if job is None:
            return
        kind, index = step
        if kind == 'san' and not job.failed and index == len(job.sans):
            job.sans.append(result)
        self._maybe_finish(job)

    def _on_failed(self, request_id, action, message):
        job, step = self._owner(request_id)
        if job is None:
            return
        job.failed = True   # the engine line went illegal here: keep the SAN found so far
        self._maybe_finish(job)

    def _maybe_finish(self, job):
        if job.ids:
            return
        self._job = None
        sans = tuple(job.sans)
        if not job.failed:
            self._cache[(job.fen, job.ucis)] = sans
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        self.line_ready.emit(NotationLine(job.fen, job.ucis, sans))
        self._pump()

    def _on_fatal(self, message):
        was = self._available
        self._available = False
        self._job = None
        self._waiting = None
        if was and not self._closing:
            self.unavailable.emit()

    def _on_closed(self):
        self._ready = False
        if not self._closing:
            self._on_fatal('closed')
        self._emit_closed()

    def _emit_closed(self):
        if not self._closed:
            self._closed = True
            self.closed.emit()
