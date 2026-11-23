"""Asynchronous adapter for this repository's `chess batch` protocol.

Requires the stage-2 models.py beside this file. Use only from the Qt thread
that owns the client. One client instance starts once; create another to restart.
"""
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from models import Move, PositionSnapshot


@dataclass
class _Request:
    request_id: int
    action: str
    commands: tuple[str, ...]
    step: int = 0


class RefereeClient(QObject):
    """Serialize requests to one long-lived referee process.

    completed(id, action, result):
        load_position/get_position/play_move/undo -> PositionSnapshot
        legal_moves -> tuple[Move, ...]
        status/san -> str
    failed(id, action, message): a rejected request or cancelled request.
    fatal_error(message): transport failure; state may be unknown.
    closed(): process has stopped, including failed startup.

    Request methods return IDs, not results. Connect signals before start().
    """

    ready = Signal()
    completed = Signal(int, str, object)
    failed = Signal(int, str, str)
    fatal_error = Signal(str)
    diagnostics = Signal(str)
    closed = Signal()

    def __init__(self, parent=None, timeout_ms: int = 5000):
        super().__init__(parent)
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self._timeout_ms = timeout_ms
        self._process = QProcess(self)
        self._process.started.connect(self._on_started)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.errorOccurred.connect(self._on_error)
        self._process.finished.connect(self._on_finished)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._process.kill)
        self._queue = deque()
        self._active = None
        self._buffer = bytearray()
        self._next_id = 1
        self._started_once = False
        self._running = False
        self._stopping = False
        self._closed_emitted = False

    def start(self, program: str, arguments=None) -> None:
        """Launch program with arguments; defaults to ['batch'].

        Native example: start('/path/to/chess').
        Windows -> WSL example:
            start('wsl.exe', ['--exec', '/home/user/project/build/release/chess',
                              'batch'])
        Pass arguments separately, never as a shell command string.
        """
        if self._started_once:
            raise RuntimeError("Create a new RefereeClient to restart")
        self._started_once = True
        self._process.setProgram(program)
        self._process.setArguments(
            ['batch'] if arguments is None else list(arguments)
        )
        self._timer.start(self._timeout_ms)
        self._process.start()

    def load_position(self, position: PositionSnapshot) -> int:
        """Load FEN (clearing referee history), then fetch accepted FEN."""
        return self._enqueue('load_position', ('position ' + position.fen, 'fen'))

    def get_position(self) -> int:
        return self._enqueue('get_position', ('fen',))

    def legal_moves(self) -> int:
        return self._enqueue('legal_moves', ('moves',))

    def play_move(self, move: Move) -> int:
        """Apply a legal move, then fetch the resulting position."""
        return self._enqueue('play_move', ('move ' + move.uci, 'fen'))

    def undo(self) -> int:
        return self._enqueue('undo', ('undo', 'fen'))

    def status(self) -> int:
        return self._enqueue('status', ('status',))

    def san(self, move: Move) -> int:
        """Request notation without playing the move."""
        return self._enqueue('san', ('san ' + move.uci,))

    def _enqueue(self, action: str, commands: tuple[str, ...]) -> int:
        if not self._running or self._stopping:
            raise RuntimeError("Wait for ready before sending requests")
        for command in commands:
            if '\n' in command or '\r' in command or '\0' in command:
                raise ValueError("Commands cannot contain line breaks or NUL")
            # Stay below the C reader's fixed-size line buffer.
            if len(command.encode('ascii')) > 158:
                raise ValueError("Command exceeds the supported length")
        request_id = self._next_id
        self._next_id += 1
        self._queue.append(_Request(request_id, action, commands))
        # Defer dispatch until callers have received the request ID.
        QTimer.singleShot(0, self._pump)
        return request_id

    def _pump(self) -> None:
        if self._stopping or self._active is not None or not self._queue:
            return
        self._active = self._queue.popleft()
        self._send_current()

    def _send_current(self) -> None:
        request = self._active
        payload = (request.commands[request.step] + '\n').encode('ascii')
        self._timer.start(self._timeout_ms)
        if self._process.write(payload) != len(payload):
            self._fatal('Could not queue the complete command for writing')

    def _on_started(self) -> None:
        if self._stopping:
            self._process.kill()
            return
        self._timer.stop()
        self._running = True
        self.ready.emit()

    def _read_stdout(self) -> None:
        # A readyRead signal can contain half a line or several lines.
        data = bytes(self._process.readAllStandardOutput())
        if self._stopping:
            return
        self._buffer.extend(data)
        while b'\n' in self._buffer:
            line, _, remainder = self._buffer.partition(b'\n')
            self._buffer = bytearray(remainder)
            try:
                reply = line.rstrip(b'\r').decode('ascii')
            except UnicodeDecodeError:
                self._fatal('Non-ASCII data in protocol response')
                return
            self._handle_reply(reply)
            if self._stopping:
                return
        if len(self._buffer) > 65536:
            self._fatal('Response exceeded the buffer limit')

    def _handle_reply(self, reply: str) -> None:
        request = self._active
        if request is None:
            self._fatal('Unexpected response without an active request')
            return
        self._timer.stop()
        if reply == 'error' or reply.startswith('error '):
            self._active = None
            self.failed.emit(request.request_id, request.action, reply)
            QTimer.singleShot(0, self._pump)
            return

        if request.step < len(request.commands) - 1:
            if reply != 'ok':
                self._fatal('Expected ok, received: ' + reply)
                return
            # Keep this compound request active until its FEN arrives.
            request.step += 1
            self._send_current()
            return

        try:
            if request.action in ('load_position', 'get_position', 'play_move', 'undo'):
                result = PositionSnapshot(reply)
            elif request.action == 'legal_moves':
                # An empty line is a valid response: no legal moves.
                result = tuple(Move.from_uci(item) for item in reply.split())
            elif request.action == 'status':
                if reply not in {
                    'ongoing', 'checkmate', 'stalemate', 'insufficient-material',
                    'fifty-moves', 'threefold-repetition',
                }:
                    raise ValueError('Unknown game status')
                result = reply
            else:
                if not reply:
                    raise ValueError('Empty SAN response')
                result = reply
        except ValueError as error:
            self._fatal(f'Malformed response: {error}')
            return
        self._active = None
        self.completed.emit(request.request_id, request.action, result)
        QTimer.singleShot(0, self._pump)

    def _read_stderr(self) -> None:
        data = bytes(self._process.readAllStandardError())
        if data:
            self.diagnostics.emit(data.decode('utf-8', errors='replace'))

    def _on_timeout(self) -> None:
        # Continuing after timeout could associate a late reply with another
        # request. Stop instead; mutations might already have happened.
        self._fatal('Referee timed out; reconnect and reload a known position')

    def _on_error(self, error) -> None:
        if not self._stopping:
            self._fatal(self._process.errorString())

    def _cancel_requests(self, message: str) -> None:
        pending = list(self._queue)
        self._queue.clear()
        if self._active is not None:
            pending.insert(0, self._active)
            self._active = None
        for request in pending:
            self.failed.emit(request.request_id, request.action, message)

    def _fatal(self, message: str) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._running = False
        self._timer.stop()
        self._cancel_requests(message)
        self.fatal_error.emit(message)
        if self._process.state() == QProcess.ProcessState.NotRunning:
            self._emit_closed()
        else:
            self._process.kill()

    def close(self) -> None:
        """Cancel outstanding work and stop asynchronously. Wait for closed."""
        if self._stopping:
            return
        self._stopping = True
        self._running = False
        self._timer.stop()
        self._cancel_requests('Client closed; request cancelled')
        if self._process.state() == QProcess.ProcessState.NotRunning:
            self._emit_closed()
        elif self._process.state() == QProcess.ProcessState.Starting:
            self._process.kill()
        else:
            # quit deliberately has no response and never enters the queue.
            self._process.write(b'quit\n')
            self._process.closeWriteChannel()
            self._kill_timer.start(1000)

    def _on_finished(self, exit_code, exit_status) -> None:
        self._read_stdout()
        self._read_stderr()
        self._kill_timer.stop()
        if not self._stopping:
            self._fatal(f'Referee exited unexpectedly (code {exit_code})')
        self._emit_closed()

    def _emit_closed(self) -> None:
        if not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit()
