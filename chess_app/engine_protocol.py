"""Pure UCI state machine and parsing for a separate Stockfish process.

No Qt dependency. UCI has no request IDs in responses: never start a new
search until the old bestmove and a following readyok have been consumed.
"""
from dataclasses import dataclass
from models import AnalysisResult, Move, PositionSnapshot, STARTING_FEN


class ProtocolError(ValueError):
    pass


class LineBuffer:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        lines = []
        while b'\n' in self.buffer:
            line, _, rest = self.buffer.partition(b'\n')
            self.buffer = bytearray(rest)
            if len(line) > 1024 * 1024:
                raise ProtocolError('Engine output line is too long')
            lines.append(line.rstrip(b'\r').decode('utf-8', errors='replace'))
        if len(self.buffer) > 1024 * 1024:
            raise ProtocolError('Unterminated engine output exceeded the limit')
        return lines


@dataclass(frozen=True)
class SearchRequest:
    request_id: int
    position: PositionSnapshot
    starting_position: PositionSnapshot
    moves: tuple[Move, ...]
    movetime_ms: int
    game_key: int

    @property
    def command(self):
        root = self.starting_position.fen
        if any(char in root for char in '\r\n\0'):
            raise ProtocolError('Invalid starting FEN')
        command = 'position startpos' if root == STARTING_FEN else 'position fen ' + root
        if self.moves:
            command += ' moves ' + ' '.join(move.uci for move in self.moves)
        return command


def parse_info(line, request):
    """Parse primary exact-score updates; normalize cp/mate to White's view.

    Bound scores and secondary MultiPV lines are not exact main-line scores.
    Ignore search telemetry and malformed info rather than presenting it as eval.
    """
    words = line.split()
    if len(words) < 2 or words[:2] == ['info', 'string'] or words[0] != 'info':
        return None
    if 'lowerbound' in words or 'upperbound' in words:
        return None
    try:
        if 'multipv' in words and int(words[words.index('multipv') + 1]) != 1:
            return None
        depth = int(words[words.index('depth') + 1])
        score_at = words.index('score')
        kind, value = words[score_at + 1], int(words[score_at + 2])
        if kind not in ('cp', 'mate') or depth < 0:
            return None
        pv = tuple(Move.from_uci(token) for token in words[words.index('pv') + 1:]) if 'pv' in words else ()
        if not pv and not (kind == 'mate' and value == 0):
            return None
    except (ValueError, IndexError):
        return None
    value *= 1 if request.position.turn == 'w' else -1
    return AnalysisResult(
        request_id=request.request_id, position=request.position, depth=depth,
        score_cp=value if kind == 'cp' else None,
        mate_in=value if kind == 'mate' else None, principal_variation=pv,
    )


def format_score(result):
    if result is None:
        return '—'
    if result.mate_in is not None:
        if result.mate_in == 0:
            return 'Checkmate'
        side = 'White' if result.mate_in > 0 else 'Black'
        return f'{side} mates in {abs(result.mate_in)}'
    if result.score_cp is not None:
        return f'{result.score_cp / 100:+.2f}'
    return '—'


class UciSession:
    """Transport-independent session. Call line() for each completed stdout line.

    Callback state_changed(state, timeout_ms) lets the transport arm its timer.
    Only the newest requested position is retained while stopping an old search.
    """
    def __init__(self, *, send, result, ready, finished, error, state_changed):
        self.send = send
        self.on_result = result
        self.on_ready = ready
        self.on_finished = finished
        self.on_error = error
        self.on_state = state_changed
        self.state = 'new'
        self.latest_id = None
        self._counter = 0
        self._pending = None
        self._active = None
        self._last_result = None
        self._game_key = None

    def _state(self, value, timeout=0):
        self.state = value
        self.on_state(value, timeout)

    def boot(self):
        if self.state != 'new':
            raise RuntimeError('A UCI session starts once')
        self._state('uci', 10000)
        self.send('uci')

    def analyse(self, position, starting_position, moves=(), *, movetime_ms=1000, game_key=0):
        if self.state in ('new', 'failed', 'closing'):
            raise RuntimeError('Engine has not started or is unavailable')
        if not 1 <= movetime_ms <= 60000:
            raise ValueError('Analysis time must be 1..60000 ms')
        self._counter += 1
        request = SearchRequest(self._counter, position, starting_position,
                                tuple(moves), movetime_ms, game_key)
        request.command  # Validate before disturbing the current search.
        self.latest_id = request.request_id
        self._pending = request
        if self.state == 'search':
            self._state('stopping', 5000)
            self.send('stop')
        self._start_pending()
        return request.request_id

    def cancel(self):
        self.latest_id = None
        self._pending = None
        if self.state == 'search':
            self._state('stopping', 5000)
            self.send('stop')

    def _start_pending(self):
        if self.state != 'idle' or self._pending is None:
            return
        request = self._pending
        if request.game_key != self._game_key:
            self._game_key = request.game_key
            self._state('newgame_ready', 10000)
            self.send('ucinewgame')
            self.send('isready')
            return
        self._pending = None
        self._active = request
        self._last_result = None
        self._state('search', request.movetime_ms + 5000)
        self.send(request.command)
        self.send(f'go movetime {request.movetime_ms}')

    def line(self, line):
        if self.state in ('failed', 'closing', 'new'):
            return
        words = line.split()
        if not words:
            return
        if line.strip() == 'uciok' and self.state == 'uci':
            self._state('initial_ready', 10000)
            self.send('setoption name Threads value 1')
            self.send('setoption name Hash value 64')
            self.send('setoption name MultiPV value 1')
            self.send('isready')
        elif line.strip() == 'readyok' and self.state in ('initial_ready', 'newgame_ready', 'barrier'):
            initial = self.state == 'initial_ready'
            self._state('idle')
            if initial:
                self.on_ready()
            self._start_pending()
        elif words[0] == 'info' and self.state == 'search' and self._active is not None:
            result = parse_info(line, self._active)
            if result is not None and result.request_id == self.latest_id:
                self._last_result = result
                self.on_result(result)
        elif words[0] == 'bestmove' and self.state in ('search', 'stopping'):
            if len(words) < 2:
                self.fail('Engine returned an incomplete bestmove')
                return
            request = self._active
            publish = self.state == 'search' and request is not None and request.request_id == self.latest_id
            last = self._last_result
            best = None
            if len(words) > 1 and words[1] not in ('0000', '(none)'):
                try:
                    best = Move.from_uci(words[1])
                except ValueError:
                    self.fail('Engine returned an invalid bestmove')
                    return
            self._active = None
            self._last_result = None
            self._state('barrier', 10000)
            self.send('isready')
            if publish and request.request_id == self.latest_id:
                # Do not attach an earlier line's score to a different final move.
                if last is None or (last.best_move.uci if last.best_move else None) != (best.uci if best else None):
                    last = AnalysisResult(request.request_id, request.position,
                                          last.depth if last else 0,
                                          principal_variation=(best,) if best else ())
                    self.on_result(last)
                self.on_finished(request.request_id)

    def fail(self, message):
        if self.state in ('failed', 'closing'):
            return
        self.latest_id = None
        self._pending = self._active = self._last_result = None
        self._state('failed')
        self.on_error(message)

    def close(self):
        self.latest_id = None
        self._pending = self._active = self._last_result = None
        self._state('closing')
