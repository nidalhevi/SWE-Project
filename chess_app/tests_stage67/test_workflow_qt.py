"""Run with the Windows GUI Python: actual QProcess + actual C integration."""

import recognition_test_bootstrap
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from image_recognition_client import RecognitionClient
from image_recognition_setup import find_recognition_root
from image_import import RecognitionResult, SquareObservation

APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)
ROOT = find_recognition_root(Path(__file__).resolve().parents[1])
if ROOT is None:
    raise RuntimeError('Install the stage-6/7 package first')
sys.path.insert(0, str(ROOT))
from PIL import Image
from lichess_2d.adapter_2d import BUILTIN
from lichess_2d.board_locator_2d import BoardRect
from lichess_2d.workflow_dialog import ImageImportDialog2D
from lichess_2d.notation import parse_placement
from lichess_2d.profile_preferences import save_selection
from tests_lichess2d.fixtures import MIDDLE, render


def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Timed out waiting for the Qt process/workflow')
        QTest.qWait(10)


class ClientOptionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.image = Path(self.directory.name) / 'image ü.png'
        render(MIDDLE).save(self.image)
        self.client = RecognitionClient(timeout_ms=5000)
        self.results, self.errors, self.closed = [], [], []
        self.client.completed.connect(self.results.append)
        self.client.failed.connect(self.errors.append)
        self.client.closed.connect(lambda: self.closed.append(True))

    def tearDown(self):
        self.client.cancel()
        wait_until(lambda: bool(self.closed))
        self.client.deleteLater()
        APP.processEvents()
        self.directory.cleanup()

    def start(self, function='options'):
        self.client.start(self.image, request_id=14, backend='tests_stage67.fixture_backend:' + function,
                          profile_path='test-profile', board_rect=[1, 2, 128, 128])

    def test_options_travel_through_actual_qprocess(self):
        self.start()
        wait_until(lambda: bool(self.closed))
        self.assertFalse(self.errors)
        self.assertEqual(self.results[0].request_id, 14)
        self.assertIn('Options reached', self.results[0].message)

    def test_cancel_discards_pending_result_and_closes_once(self):
        self.start('slow')
        self.client.cancel()
        wait_until(lambda: bool(self.closed))
        self.assertEqual(len(self.closed), 1)
        self.assertFalse(self.results)
        self.assertFalse(self.errors)

    def test_timeout_cancels_worker(self):
        self.client.timeout_ms = 30
        self.start('slow')
        wait_until(lambda: bool(self.closed))
        self.assertIn('timed out', self.errors[0])
        self.assertFalse(self.results)

    def test_failed_start_can_close(self):
        with patch.object(sys, 'executable', str(Path(self.directory.name) / 'missing-python.exe')):
            self.start()
        wait_until(lambda: bool(self.closed))
        self.assertEqual(len(self.closed), 1)
        self.assertTrue(self.errors)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.path = self.base / 'board.png'
        render(MIDDLE, cell=64).save(self.path)
        self.preferences = self.base / 'settings/image_import.json'
        self.dialogs = []
        self.dialog = self.make_dialog()

    def make_dialog(self):
        dialog = ImageImportDialog2D(self.path, vision_path=ROOT, preferences_path=self.preferences)
        self.dialogs.append(dialog)
        dialog.show()
        return dialog

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.force_close()
            wait_until(lambda: not dialog.isVisible())
            dialog.deleteLater()
        APP.processEvents()
        self.directory.cleanup()

    def configure(self):
        self.dialog.profile.setCurrentIndex(self.dialog.profile.findData(BUILTIN))
        self.dialog._board_rect = BoardRect(0, 0, 512, 512)
        self.dialog.orientation.setCurrentIndex(1)

    def test_initially_unconfigured_no_unrelated_model_runs(self):
        self.assertIsNone(self.dialog.profile.currentData())
        self.dialog.recognize_button.click()
        self.assertIsNone(self.dialog._worker)
        self.assertIn('Choose a matching profile', self.dialog.message.text())

    def test_profile_selection_is_remembered_across_dialogs(self):
        self.configure()
        another = self.make_dialog()
        self.assertEqual(another.profile.currentData(), BUILTIN)

    def test_missing_remembered_profile_does_not_fall_back_to_builtin(self):
        save_selection(str(self.base / 'missing/profile.json'), self.preferences)
        another = self.make_dialog()
        self.assertIsNone(another.profile.currentData())
        self.assertIn('unavailable', another.message.text())

    def test_old_request_id_cannot_replace_draft(self):
        self.configure()
        before = self.dialog.draft.cells.copy()
        stale = RecognitionResult(self.dialog._request_id + 10, 'ok', (SquareObservation('e1', 'K', .9),))
        self.dialog._recognized(stale)
        self.assertEqual(self.dialog.draft.cells, before)

    def test_changed_inputs_cannot_apply_even_same_request_id(self):
        self.configure()
        before = self.dialog.draft.cells.copy()
        self.dialog._pending_inputs = self.dialog._fingerprint()
        self.dialog._board_rect = BoardRect(0, 0, 256, 256)
        stale = RecognitionResult(self.dialog._request_id, 'ok', (SquareObservation('e1', 'K', .9),))
        self.dialog._recognized(stale)
        self.assertEqual(self.dialog.draft.cells, before)
        self.assertIn('Ignored', self.dialog.message.text())

    def test_manual_position_requires_metadata_and_review(self):
        requested = []
        self.dialog.position_requested.connect(requested.append)
        self.dialog.manual_button.click()
        self.dialog.orientation.setCurrentIndex(1)
        self.dialog.placement.setText(MIDDLE)
        self.dialog.placement_button.click()
        self.dialog.import_button.click()
        self.assertFalse(requested)
        self.dialog.turn.setCurrentIndex(1)
        self.dialog.reviewed.setChecked(True)
        self.dialog.import_button.click()
        self.assertEqual(requested[0].fen, MIDDLE + ' w - - 0 1')

    def test_new_engine_result_never_auto_confirms_metadata(self):
        self.configure()
        self.dialog.recognize_button.click()
        wait_until(lambda: self.dialog._worker is None)
        self.assertEqual(self.dialog.draft.cells, parse_placement(MIDDLE))
        self.assertFalse(self.dialog.reviewed.isChecked())
        self.assertIsNone(self.dialog.turn.currentData())
        self.assertIn('not a probability', self.dialog.message.text())


from tests.gui_support import WindowCase


class RefereeWorkflowTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.path = self.base / 'original screenshot ü.png'
        image = Image.new('RGB', (900, 700), '#262626')
        image.paste(render(MIDDLE, cell=64, white_bottom=False), (117, 83))
        image.save(self.path)

    def tearDown(self):
        super().tearDown()
        self.directory.cleanup()

    def open_recognition(self):
        # No backend, vision path or PYTHONPATH is configured on the window.
        self.window._open_image_path(str(self.path))
        dialog = self.window._image_dialog
        self.assertIsInstance(dialog, ImageImportDialog2D)
        dialog._preferences_path = self.base / 'preferences.json'
        dialog.profile.setCurrentIndex(dialog.profile.findData(BUILTIN))
        dialog._board_rect = BoardRect(117, 83, 512, 512)
        dialog.orientation.setCurrentIndex(2)
        dialog.recognize_button.click()
        return dialog

    def test_profile_crop_worker_review_referee_and_analysis_roundtrip(self):
        old_search = self.add_analysis()
        dialog = self.open_recognition()
        wait_until(lambda: dialog._worker is None)
        self.assertEqual(dialog.draft.cells, parse_placement(MIDDLE))
        dialog.turn.setCurrentIndex(1)
        dialog.reviewed.setChecked(True)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            dialog.import_button.click()
        wait_until(lambda: self.window._image_dialog is None)
        self.ready()
        expected = MIDDLE + ' w - - 0 1'
        self.assertEqual(self.controller.position.fen, expected)
        wait_until(lambda: self.engine.requests[-1].position.fen == expected)
        newest = self.engine.requests[-1]
        self.engine.publish(old_search, 'e2e4', 9900)
        self.engine.publish(newest, self.controller.legal_moves[0].uci, 24)
        self.assertEqual(self.window.evaluation_label.text(), 'Evaluation: +0.24')

    def test_window_close_waits_for_recognition_and_referee(self):
        dialog = self.open_recognition()
        self.assertIsNotNone(dialog._worker)
        self.window.close()
        wait_until(lambda: not self.window.isVisible())
        self.assertIsNone(self.window._image_dialog)
        self.assertTrue(self.window._referee_stopped)
