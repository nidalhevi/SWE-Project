"""Reuse recognition transport cancellation, limits, timeout and close semantics."""
import json
from pathlib import Path
import sys
from image_recognition_client import RecognitionClient
from .board_proposals import parse_proposals


class BoardProposalClient(RecognitionClient):
    def __init__(self, parent=None, *, timeout_ms=20000):
        super().__init__(parent, timeout_ms=timeout_ms)
        self.timer.timeout.disconnect()
        self.timer.timeout.connect(lambda: self._fail('Board search timed out; select the board manually'))

    def start(self, image_path, *, request_id, image_size):
        if self._started:
            raise RuntimeError('Use a new proposal client for each request')
        if type(request_id) is not int or request_id < 0:
            raise ValueError('Invalid proposal request ID')
        self._started = True
        self._request_id = request_id
        self._image_size = image_size
        request = dict(path=str(Path(image_path).resolve()), request_id=request_id)
        self.process.setProgram(sys.executable)
        self.process.setArguments([str(Path(__file__).with_name('proposal_worker.py')),
                                   '--request', json.dumps(request, ensure_ascii=True)])
        self.timer.start(self.timeout_ms)
        self.process.start()

    def _parse_response(self, raw):
        return parse_proposals(raw, self._request_id, self._image_size)
