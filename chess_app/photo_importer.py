"""Run the photo reader as a separate process and hand back a PhotoGame.

The reader (vision/scripts/run_game.py) needs PyTorch and OpenCV. Running it
as its own process keeps those out of the GUI and keeps the window
responsive: reading a 100-photo game takes about 20 seconds.

Which Python runs the reader: the CHESSVISION_PYTHON environment variable if
set, otherwise the Python that runs the GUI. Set it when the vision packages
live in a different Python than PySide6.
"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTemporaryDir, Signal

from photo_game import load_photo_game

REPO_ROOT = Path(__file__).resolve().parent.parent
READER_SCRIPT = REPO_ROOT / "vision" / "scripts" / "run_game.py"


class PhotoImporter(QObject):
    """Decode one folder of photos at a time.

    progress(text): one line per photo and per move, for a status bar.
    finished(game): a PhotoGame; the reader's PGN replayed in the referee.
    failed(message): the reader could not be started or reported an error.
    """

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(REPO_ROOT))
        self._process.readyReadStandardError.connect(self._read_progress)
        self._process.errorOccurred.connect(self._on_error)
        self._process.finished.connect(self._on_finished)
        self._output_dir = None
        self._log = ""
        self._reported = True

    @property
    def busy(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def start(self, folder: str) -> None:
        """Start reading the photos in folder. Requires not busy."""
        if self.busy:
            raise RuntimeError("A photo game is already being read")
        # A fresh temporary folder per run; it is deleted with this object.
        self._output_dir = QTemporaryDir()
        if not self._output_dir.isValid():
            self.failed.emit("Could not create a temporary folder")
            return
        self._log = ""
        self._reported = False
        python = os.environ.get("CHESSVISION_PYTHON") or sys.executable
        # Arguments are passed separately, never as a shell command string.
        self._process.start(python, [
            str(READER_SCRIPT), folder,
            "-o", self._output_dir.filePath("game.pgn"),
            "--json", self._output_dir.filePath("game.json"),
        ])

    def cancel(self) -> None:
        """Stop reading; nothing is reported. Waits briefly so the process is gone before Qt deletes it."""
        if self.busy:
            self._reported = True
            self._process.kill()
            self._process.waitForFinished(2000)

    def _read_progress(self) -> None:
        text = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        self._log += text
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            self.progress.emit(lines[-1])

    def _fail(self, message: str) -> None:
        if not self._reported:
            self._reported = True
            self.failed.emit(message)

    def _on_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._fail("Could not start the photo reader: " + self._process.errorString())

    def _on_finished(self, exit_code, exit_status) -> None:
        self._read_progress()
        if self._reported:
            return
        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            # The reader's last line says what went wrong (no photos, no board, missing package).
            last = self._log.strip().splitlines()[-1] if self._log.strip() else "no output"
            self._fail(f"Photo reader failed (code {exit_code}): {last}")
            return
        try:
            game = load_photo_game(self._output_dir.filePath("game.json"))
        except (OSError, ValueError) as error:
            self._fail(f"Could not read the result: {error}")
            return
        self._reported = True
        self.finished.emit(game)
