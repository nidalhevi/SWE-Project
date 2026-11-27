"""Asynchronous Stockfish UCI transport using QProcess, separate from referee."""
from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from engine_protocol import LineBuffer, ProtocolError, UciSession


class EngineClient(QObject):
    ready = Signal()
    result_ready = Signal(object)   # Existing models.AnalysisResult
    finished = Signal(int)          # Request ID, when this search completes
    error = Signal(str)
    diagnostics = Signal(str)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.started.connect(self._on_started)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.errorOccurred.connect(self._on_error)
        self._process.finished.connect(self._on_finished)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._on_timeout)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._process.kill)
        self._buffer = LineBuffer()
        self._closing = False
        self._failed = False
        self._closed_emitted = False
        self._started_once = False
        self.session = UciSession(
            send=self._write, result=self.result_ready.emit, ready=self.ready.emit,
            finished=self.finished.emit, error=self._session_error,
            state_changed=self._arm_deadline,
        )

    def start(self, program, arguments=None):
        if self._started_once:
            raise RuntimeError('Create a new EngineClient to restart')
        self._started_once = True
        self._process.setProgram(program)
        self._process.setArguments(list(arguments or []))
        self._deadline.start(10000)
        self._process.start()

    def analyse(self, position, starting_position, moves=(), *, movetime_ms=1000, game_key=0):
        return self.session.analyse(position, starting_position, moves,
                                    movetime_ms=movetime_ms, game_key=game_key)

    def cancel(self):
        self.session.cancel()

    def _arm_deadline(self, state, timeout):
        self._deadline.stop()
        if timeout and not self._closing and not self._failed:
            self._deadline.start(timeout)

    def _on_started(self):
        if self._closing:
            self._process.kill()
        else:
            self.session.boot()

    def _write(self, command):
        if self._closing or self._failed:
            return
        payload = (command + '\n').encode('ascii')
        if self._process.write(payload) != len(payload):
            self.session.fail('Could not write the complete UCI command')

    def _read_stdout(self):
        data = bytes(self._process.readAllStandardOutput())
        if self._closing or self._failed:
            return
        try:
            for line in self._buffer.feed(data):
                self.session.line(line)
        except ProtocolError as error:
            self.session.fail(str(error))

    def _read_stderr(self):
        text = bytes(self._process.readAllStandardError()).decode('utf-8', errors='replace')
        if text:
            self.diagnostics.emit(text)

    def _on_timeout(self):
        self.session.fail(f'Analysis engine timed out during {self.session.state}')

    def _on_error(self, error):
        if not self._closing:
            self.session.fail(self._process.errorString())
        elif self._process.state() == QProcess.ProcessState.NotRunning:
            # FailedToStart has no finished signal. A close requested while
            # Starting must still release the window's shutdown wait.
            self._emit_closed()

    def _session_error(self, message):
        if self._failed:
            return
        self._failed = True
        self._deadline.stop()
        self.error.emit(message)
        if self._process.state() == QProcess.ProcessState.NotRunning:
            self._emit_closed()
        else:
            self._process.kill()

    def close(self):
        if self._closing:
            return
        self._closing = True
        self._deadline.stop()
        self.session.close()
        state = self._process.state()
        if state == QProcess.ProcessState.NotRunning:
            self._emit_closed()
        elif state == QProcess.ProcessState.Starting:
            self._process.kill()
        else:
            self._process.write(b'quit\n')
            self._process.closeWriteChannel()
            self._kill_timer.start(1000)

    def _on_finished(self, code, status):
        self._read_stdout()
        self._read_stderr()
        self._kill_timer.stop()
        if not self._closing and not self._failed:
            self.session.fail(f'Analysis engine exited unexpectedly (code {code})')
        self._emit_closed()

    def _emit_closed(self):
        if not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit()
