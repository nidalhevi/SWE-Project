"""Real Qt/QProcess integration with a deterministic UCI process, not Stockfish."""
from pathlib import Path
import sys
import unittest
import tests_stage4.test_gui as stage4
from engine_client import EngineClient
from models import AnalysisResult, Move, PositionSnapshot, STARTING_FEN

START = PositionSnapshot(STARTING_FEN)
FAKE = str(Path(__file__).with_name('fake_uci.py'))


class EngineTransportTests(unittest.TestCase):
    def setUp(self):
        self.engine = EngineClient()
        self.results, self.finished, self.errors = [], [], []
        self.closed = False
        self.engine.result_ready.connect(self.results.append)
        self.engine.finished.connect(self.finished.append)
        self.engine.error.connect(self.errors.append)
        self.engine.closed.connect(lambda: setattr(self, 'closed', True))

    def boot(self):
        self.engine.start(sys.executable, [FAKE])
        stage4.wait_until(lambda: self.engine.session.state == 'idle')

    def tearDown(self):
        self.engine.close()
        stage4.wait_until(lambda: self.closed)
        self.engine.deleteLater()

    def test_handshake_and_streaming_results(self):
        self.boot()
        ident = self.engine.analyse(START, START, movetime_ms=100)
        stage4.wait_until(lambda: ident in self.finished)
        self.assertEqual(self.results[-1].request_id, ident)
        self.assertEqual(self.results[-1].score_cp, 34)
        self.assertFalse(self.errors)

    def test_rapid_replacement_discards_late_old_info(self):
        self.boot()
        old = self.engine.analyse(START, START, movetime_ms=100)
        # Replace before Qt dispatches replies, keeping this deterministic even
        # when an overloaded machine delivers several output lines together.
        index = len(self.results)
        new = self.engine.analyse(START, START, movetime_ms=100)
        stage4.wait_until(lambda: new in self.finished)
        self.assertTrue(all(result.request_id == new for result in self.results[index:]))
        self.assertNotIn(old, self.finished)
        self.assertNotIn(999, [result.score_cp for result in self.results])

    def test_failed_start_emits_error_and_closed(self):
        self.engine.start('/this-stockfish-does-not-exist')
        stage4.wait_until(lambda: self.closed)
        self.assertTrue(self.errors)

    def test_timeout_stops_engine(self):
        self.boot()
        self.engine._on_timeout()  # Fault injection; don't wait ten seconds.
        stage4.wait_until(lambda: self.closed)
        self.assertTrue(self.errors)

    def test_close_during_search(self):
        self.boot()
        self.engine.analyse(START, START, movetime_ms=100)
        self.engine.close()
        stage4.wait_until(lambda: self.closed)
        self.assertFalse(self.errors)


class AnalysisGuiTests(unittest.TestCase):
    # Reuse helper methods without inheriting and rerunning all stage-4 tests.
    ready = stage4.LegalMoveGuiTests.ready
    click = stage4.LegalMoveGuiTests.click
    play = stage4.LegalMoveGuiTests.play
    load = stage4.LegalMoveGuiTests.load

    def setUp(self):
        stage4.LegalMoveGuiTests.setUp(self)

    def tearDown(self):
        stage4.LegalMoveGuiTests.tearDown(self)

    def start_analysis(self, mode='normal'):
        self.window._start_engine(sys.executable, [FAKE, '--mode', mode])

    def complete(self):
        stage4.wait_until(lambda: self.window.engine_status.text() == 'Analysis complete')

    def test_evaluation_depth_bestmove_and_line(self):
        self.start_analysis()
        self.complete()
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: +0.34')
        self.assertEqual(self.window.depth_label.text(), 'Depth: 8')
        self.assertIn('e2', self.window.best_move_label.text())
        self.assertIn('e2e4', self.window.pv_view.toPlainText())

    def test_black_perspective_and_board_flip(self):
        self.start_analysis(); self.complete()
        self.play('e2e4'); self.complete()
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: -0.34')
        self.window.board.flip()
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: -0.34')
        self.assertIn('e7e5', self.window.pv_view.toPlainText())

    def test_old_request_and_wrong_fen_cannot_overwrite(self):
        self.start_analysis(); self.complete()
        old_id = self.window.analysis._expected_id
        self.play('e2e4'); self.complete()
        analysis = self.window.analysis
        before = self.window.evaluation_label.text()
        stale = AnalysisResult(old_id, START, 99, score_cp=999,
                               principal_variation=(Move.from_uci('e2e4'),))
        analysis._on_result(stale)
        wrong_fen = AnalysisResult(analysis._expected_id, START, 99, score_cp=999,
                                   principal_variation=(Move.from_uci('e2e4'),))
        analysis._on_result(wrong_fen)
        self.assertEqual(self.window.evaluation_label.text(), before)

    def test_pause_resume_and_time_change(self):
        self.start_analysis(); self.complete()
        self.window.analysis_toggle.click()
        self.assertEqual(self.window.engine_status.text(), 'Analysis paused')
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: —')
        self.window.analysis_time.setValue(200)
        self.window.analysis_toggle.click()
        self.complete()
        self.assertEqual(self.window.analysis.movetime_ms, 200)

    def test_engine_failure_does_not_disable_legal_moves(self):
        self.start_analysis('exit-on-go')
        stage4.wait_until(lambda: self.window._engine_stopped)
        self.assertIn('unavailable', self.window.engine_status.text())
        self.assertTrue(self.controller.can_move)
        self.play('e2e4')
        self.assertEqual(self.controller.position.pieces.get('e4'), 'P')

    def test_missing_engine_does_not_disable_referee(self):
        self.window._start_engine('/this-stockfish-does-not-exist', [])
        stage4.wait_until(lambda: self.window._engine_stopped)
        self.assertTrue(self.controller.can_move)
        self.play('e2e4')
        self.assertEqual(self.controller.position.turn, 'b')

    def test_terminal_position_clears_previous_analysis(self):
        self.start_analysis(); self.complete()
        self.load('7k/5K2/6Q1/8/8/8/8/8 b - - 0 1')
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: —')
        self.assertIn('Game finished', self.window.engine_status.text())
        self.assertIsNone(self.window.analysis._expected_id)

    def test_close_waits_for_both_processes(self):
        self.start_analysis()
        stage4.wait_until(lambda: self.window.analysis._expected_id is not None)
        self.window.close()
        stage4.wait_until(lambda: not self.window.isVisible())
        self.assertTrue(self.window._referee_stopped)
        self.assertTrue(self.window._engine_stopped)
