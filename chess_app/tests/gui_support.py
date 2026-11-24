"""Shared Qt integration helpers; controlled analysis is explicitly a test double."""
from dataclasses import dataclass
from unittest.mock import patch
import unittest
import tests_stage4.test_gui as stage4
from PySide6.QtCore import QObject, QTimer, Signal
from models import AnalysisResult, Move


@dataclass(frozen=True)
class RecordedSearch:
    request_id: int
    position: object
    root: object
    moves: tuple
    game_key: int


class ControlledEngine(QObject):
    """Allow a test to deliver old/new responses in a chosen event order.

    No chess search and no OS process. Separate process tests exercise QProcess.
    """
    ready = Signal()
    result_ready = Signal(object)
    finished = Signal(int)
    error = Signal(str)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.requests = []
        self.cancellations = 0
        self.stopped = False

    def start(self, program, arguments=None):
        QTimer.singleShot(0, self.ready.emit)

    def analyse(self, position, starting_position, moves=(), *, movetime_ms=1000, game_key=0):
        ident = len(self.requests) + 1
        self.requests.append(RecordedSearch(ident, position, starting_position, tuple(moves), game_key))
        return ident

    def cancel(self):
        self.cancellations += 1

    def publish(self, request, best, cp, *, finish=True):
        result = AnalysisResult(request.request_id, request.position, 12, score_cp=cp,
                                principal_variation=(Move.from_uci(best),))
        self.result_ready.emit(result)
        if finish:
            self.finished.emit(request.request_id)

    def close(self):
        if not self.stopped:
            self.stopped = True
            QTimer.singleShot(0, self.closed.emit)


class WindowCase(unittest.TestCase):
    ready = stage4.LegalMoveGuiTests.ready
    click = stage4.LegalMoveGuiTests.click
    play = stage4.LegalMoveGuiTests.play
    load = stage4.LegalMoveGuiTests.load

    def setUp(self):
        stage4.LegalMoveGuiTests.setUp(self)

    def tearDown(self):
        stage4.LegalMoveGuiTests.tearDown(self)

    def add_analysis(self):
        with patch('main_window.EngineClient', ControlledEngine):
            self.window._start_engine('controlled-test-engine')
        self.engine = self.window.engine
        stage4.wait_until(lambda: bool(self.engine.requests))
        return self.engine.requests[-1]

    def next_search(self, action):
        before = len(self.engine.requests)
        action()
        self.ready()
        stage4.wait_until(lambda: len(self.engine.requests) > before)
        request = self.engine.requests[-1]
        self.assertEqual(request.position.fen, self.controller.position.fen)
        return request

    def publish_current(self, cp=34):
        request = self.engine.requests[-1]
        best = self.controller.legal_moves[0].uci
        self.engine.publish(request, best, cp)
        self.assertEqual(self.window.evaluation_label.text(), f'Evaluation: {cp / 100:+.2f}')
        return request
