"""Real QProcess boundary failures, including close racing with failed startup."""
from pathlib import Path
import sys
import unittest
from tests.gui_support import WindowCase, stage4
from engine_client import EngineClient
from referee_client import RefereeClient
from models import PositionSnapshot, STARTING_FEN

HERE = Path(__file__).parent


class ProcessFailureTests(unittest.TestCase):
    def referee(self, mode=None):
        client = RefereeClient(timeout_ms=5000)
        self.prepare(client)
        client.ready.connect(lambda: setattr(self, 'ready', True))
        self.ready = False
        if mode:
            client.start(sys.executable, [str(HERE / 'fake_referee.py'), '--mode', mode])
            stage4.wait_until(lambda: self.ready)
        return client

    def prepare(self, client):
        self.client = client
        self.closed, self.errors, self.failed, self.completed = [], [], [], []
        client.closed.connect(lambda: self.closed.append(True))
        if isinstance(client, RefereeClient):
            client.fatal_error.connect(self.errors.append)
            client.failed.connect(lambda *args: self.failed.append(args))
            client.completed.connect(lambda *args: self.completed.append(args))
        else:
            client.error.connect(self.errors.append)

    def tearDown(self):
        if hasattr(self, 'client'):
            self.client.close()
            stage4.wait_until(lambda: bool(self.closed))
            self.client.deleteLater()
            stage4.APP.processEvents()

    def test_malformed_referee_reply_cancels_all_pending_requests(self):
        client = self.referee('malformed')
        ids = [client.get_position() for _ in range(3)]
        stage4.wait_until(lambda: bool(self.closed))
        self.assertEqual({item[0] for item in self.failed}, set(ids))
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(len(self.closed), 1)
        self.assertFalse(self.completed)

    def test_referee_timeout_closes_instead_of_reusing_uncertain_stream(self):
        client = self.referee('hang')
        ident = client.get_position()
        stage4.wait_until(lambda: client._active is not None)
        client._timer.start(50)  # Real timer; fixture never replies.
        stage4.wait_until(lambda: bool(self.closed))
        self.assertIn('timed out', self.errors[0])
        self.assertEqual([item[0] for item in self.failed], [ident])
        self.assertFalse(self.completed)

    def test_fragmented_fen_responses_keep_request_ids(self):
        client = self.referee('fragmented')
        ids = [client.get_position(), client.get_position()]
        stage4.wait_until(lambda: len(self.completed) == 2)
        self.assertEqual([item[0] for item in self.completed], ids)
        self.assertTrue(all(item[2].fen == STARTING_FEN for item in self.completed))
        self.assertFalse(self.errors)

    def test_referee_close_during_failed_start_still_emits_closed(self):
        client = self.referee()
        client.start('/this-referee-does-not-exist', ['batch'])
        client.close()
        stage4.wait_until(lambda: bool(self.closed))
        self.assertEqual(len(self.closed), 1)

    def test_engine_close_during_failed_start_still_emits_closed(self):
        client = EngineClient()
        self.prepare(client)
        client.start('/this-engine-does-not-exist')
        client.close()
        stage4.wait_until(lambda: bool(self.closed))
        self.assertEqual(len(self.closed), 1)

    def engine(self, mode):
        client = EngineClient()
        self.prepare(client)
        client.start(sys.executable, [str(HERE / 'fake_bad_uci.py'), '--mode', mode])
        stage4.wait_until(lambda: client.session.state == 'idle')
        start = PositionSnapshot(STARTING_FEN)
        client.analyse(start, start, movetime_ms=100)
        return client

    def test_invalid_engine_bestmove_closes_with_error(self):
        self.engine('invalid-bestmove')
        stage4.wait_until(lambda: bool(self.closed))
        self.assertIn('invalid bestmove', self.errors[0])

    def test_engine_that_ignores_stop_is_terminated(self):
        client = self.engine('hang-stop')
        stage4.wait_until(lambda: client.session._last_result is not None)
        client.cancel()
        self.assertEqual(client.session.state, 'stopping')
        client._deadline.start(50)  # Real timer; stop deliberately has no reply.
        stage4.wait_until(lambda: bool(self.closed))
        self.assertIn('timed out', self.errors[0])
        self.assertEqual(len(self.closed), 1)


class ActualRefereeFailureTests(WindowCase):
    def test_actual_referee_crash_disables_board_without_corrupting_display(self):
        self.controller.on_square_clicked('e2')
        self.controller.on_square_clicked('e4')
        self.window.referee._process.kill()
        stage4.wait_until(lambda: self.window._referee_stopped)
        self.assertFalse(self.controller.can_move)
        self.assertFalse(self.controller.can_load)
        self.assertFalse(self.window.board._interactive)
        self.assertEqual(self.window.board._pieces, self.controller.position.pieces)
        self.assertEqual(self.controller.tree.current.position.fen, self.controller.position.fen)
        self.assertTrue(self.window.error_label.text())
