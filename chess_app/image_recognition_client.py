"""One-shot QProcess worker. Cancellation discards output before killing it."""
import json
from pathlib import Path
import sys
from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from image_import import MAX_RESPONSE_BYTES, ImageImportError, parse_recognition


class RecognitionClient(QObject):
    completed = Signal(object)
    failed = Signal(str)
    closed = Signal()

    def __init__(self, parent=None, *, timeout_ms=60000):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.started.connect(self._on_started)
        self.process.readyReadStandardOutput.connect(self._stdout)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.errorOccurred.connect(self._error)
        self.process.finished.connect(self._finished)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self._fail('Recognition timed out; you can enter the position manually'))
        self.timeout_ms = timeout_ms
        self._started = False
        self._discard = False
        self._closed = False
        self._output = bytearray()
        self._errors = bytearray()
        self._request_id = None

    def start(self, image_path, *, request_id, white_bottom=True, backend=None, vision_path=None):
        if self._started:
            raise RuntimeError('Use a new recognition client for each request')
        self._started = True
        self._request_id = request_id
        request = dict(path=str(image_path), request_id=request_id, white_bottom=white_bottom,
                       backend=backend, vision_path=vision_path)
        worker = str(Path(__file__).with_name('image_recognition_worker.py'))
        self.process.setProgram(sys.executable)
        self.process.setArguments([worker, '--request', json.dumps(request, ensure_ascii=True)])
        self.timer.start(self.timeout_ms)
        self.process.start()

    def _stdout(self):
        data = bytes(self.process.readAllStandardOutput())
        if self._discard:
            return
        self._output.extend(data)
        if len(self._output) > MAX_RESPONSE_BYTES:
            self._fail('Recognition output exceeded the limit')

    def _stderr(self):
        # Keep a bounded tail for diagnostics; ML libraries may log extensively.
        data = bytes(self.process.readAllStandardError())
        self._errors = (self._errors + data)[-8192:]

    def _error(self, error):
        if not self._discard:
            self._fail(self.process.errorString())
        elif self.process.state() == QProcess.ProcessState.NotRunning:
            self._emit_closed()

    def _on_started(self):
        if self._discard:
            self.process.kill()

    def _fail(self, message):
        if self._discard:
            return
        self._discard = True
        self.timer.stop()
        self.failed.emit(message)
        self._stop()

    def cancel(self):
        self._discard = True
        self.timer.stop()
        self._stop()

    def _stop(self):
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._emit_closed()
        else:
            self.process.kill()

    def _finished(self, code, status):
        self._stdout()
        self._stderr()
        self.timer.stop()
        if not self._discard:
            self._discard = True
            if code != 0:
                detail = self._errors.decode('utf-8', errors='replace').strip()
                self.failed.emit(detail or f'Recognizer exited with code {code}')
            else:
                try:
                    result = parse_recognition(bytes(self._output), self._request_id)
                except ImageImportError as error:
                    self.failed.emit(str(error))
                else:
                    self.completed.emit(result)
        self._emit_closed()

    def _emit_closed(self):
        if not self._closed:
            self._closed = True
            self.closed.emit()
