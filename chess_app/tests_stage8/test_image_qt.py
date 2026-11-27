"""Qt image/editor/process checks and C-controller import/rollback integration."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import tests_stage4.test_gui as stage4
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QMessageBox
from image_import_dialog import ImageImportDialog
from image_recognition_client import RecognitionClient
from models import PositionSnapshot, STARTING_FEN

FIXTURES = str(Path(__file__).parent)


def image_file(directory):
    path = str(Path(directory) / 'board photo.png')
    image = QImage(256, 256, QImage.Format.Format_RGB32)
    image.fill(QColor('#EEEED2'))
    assert image.save(path)
    return path


class RecognitionQtTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = image_file(self.directory.name)
        self.client = RecognitionClient(timeout_ms=5000)
        self.results, self.errors, self.closes = [], [], []
        self.client.completed.connect(self.results.append)
        self.client.failed.connect(self.errors.append)
        self.client.closed.connect(lambda: self.closes.append(True))

    def tearDown(self):
        self.client.cancel()
        stage4.wait_until(lambda: bool(self.closes))
        self.client.deleteLater()
        stage4.APP.processEvents()
        self.directory.cleanup()

    def launch(self, function='recognize', **options):
        self.client.start(self.path, request_id=1, backend='fixture_recognizer:' + function,
                          vision_path=FIXTURES, **options)

    def test_real_qprocess_returns_typed_result(self):
        self.launch()
        stage4.wait_until(lambda: bool(self.closes))
        self.assertEqual(self.results[0].request_id, 1)
        self.assertFalse(self.errors)

    def test_missing_backend_is_explicit(self):
        self.client.start(self.path, request_id=1)
        stage4.wait_until(lambda: bool(self.closes))
        self.assertEqual(self.results[0].status, 'unavailable')

    def test_backend_error_does_not_return_predictions(self):
        self.launch('broken')
        stage4.wait_until(lambda: bool(self.closes))
        self.assertIn('Fixture model failed', self.errors[0])
        self.assertFalse(self.results)

    def test_cancel_discards_results_and_closes_once(self):
        self.launch('slow')
        self.client.cancel()
        stage4.wait_until(lambda: bool(self.closes))
        self.assertEqual(len(self.closes), 1)
        self.assertFalse(self.results)
        self.assertFalse(self.errors)

    def test_timeout_stops_worker(self):
        self.client.timeout_ms = 50
        self.launch('slow')
        stage4.wait_until(lambda: bool(self.closes))
        self.assertIn('timed out', self.errors[0])

    def test_output_limit_stops_worker(self):
        self.launch('oversized')
        stage4.wait_until(lambda: bool(self.closes))
        self.assertTrue(self.errors)
        self.assertFalse(self.results)


class ImageDialogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = image_file(self.directory.name)
        self.dialog = ImageImportDialog(self.path, backend='fixture_recognizer:recognize', vision_path=FIXTURES)
        self.dialog.show()
        self.requested = []
        self.dialog.position_requested.connect(self.requested.append)

    def tearDown(self):
        self.dialog.force_close()
        stage4.wait_until(lambda: not self.dialog.isVisible())
        self.dialog.deleteLater()
        stage4.APP.processEvents()
        self.directory.cleanup()

    def complete_manual(self):
        self.dialog.orientation.setCurrentIndex(1)
        self.dialog.placement.setText(STARTING_FEN.split()[0])
        self.dialog.placement_button.click()
        self.dialog.turn.setCurrentIndex(1)
        for checkbox in self.dialog.rights.values():
            checkbox.setChecked(True)
        self.dialog.reviewed.setChecked(True)

    def test_no_position_requested_with_unknown_squares(self):
        self.dialog.orientation.setCurrentIndex(1)
        self.dialog.import_button.click()
        self.assertIn('unknown', self.dialog.message.text())
        self.assertFalse(self.requested)

    def test_manual_confirmation_emits_full_fen(self):
        self.complete_manual()
        self.dialog.import_button.click()
        self.assertEqual(self.requested[0].fen, STARTING_FEN)

    def test_piece_edit_removes_review_confirmation(self):
        self.complete_manual()
        self.dialog.palette.setCurrentIndex(0)
        self.dialog._edit_square('a1')
        self.assertIsNone(self.dialog.draft.cells['a1'])
        self.assertFalse(self.dialog.reviewed.isChecked())

    def test_metadata_edit_requires_review_again(self):
        self.complete_manual()
        self.dialog.fullmove.setValue(42)
        self.assertFalse(self.dialog.reviewed.isChecked())

    def test_recognition_requires_orientation(self):
        self.dialog.recognize_button.click()
        self.assertIsNone(self.dialog._worker)
        self.assertIn('orientation', self.dialog.message.text())

    def test_recognition_populates_editable_draft(self):
        self.dialog.orientation.setCurrentIndex(1)
        self.dialog.recognize_button.click()
        stage4.wait_until(lambda: self.dialog._worker is None)
        self.assertFalse(self.dialog.draft.unknown_squares)
        self.assertIn('e2', self.dialog.draft.uncertain_squares)
        self.assertIsNone(self.dialog.turn.currentData())
        self.assertFalse(self.dialog.reviewed.isChecked())

    def test_orientation_flips_view_without_changing_assignments(self):
        self.complete_manual()
        before = self.dialog.draft.cells.copy()
        self.dialog.orientation.setCurrentIndex(2)
        self.assertTrue(self.dialog.board._flipped)
        self.assertEqual(self.dialog.draft.cells, before)

    def test_cancel_during_recognition_waits_for_worker(self):
        self.dialog.backend = 'fixture_recognizer:slow'
        self.dialog.orientation.setCurrentIndex(1)
        self.dialog.recognize_button.click()
        self.dialog.reject()
        stage4.wait_until(lambda: not self.dialog.isVisible())
        self.assertIsNone(self.dialog._worker)

    def test_invalid_image_rejected(self):
        bad = Path(self.directory.name) / 'bad.png'
        bad.write_text('not an image')
        with self.assertRaises(ValueError):
            ImageImportDialog(str(bad))


class ImageGuiTests(unittest.TestCase):
    ready = stage4.LegalMoveGuiTests.ready
    click = stage4.LegalMoveGuiTests.click
    play = stage4.LegalMoveGuiTests.play
    load = stage4.LegalMoveGuiTests.load

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = image_file(self.directory.name)
        stage4.LegalMoveGuiTests.setUp(self)

    def tearDown(self):
        stage4.LegalMoveGuiTests.tearDown(self)
        self.directory.cleanup()

    def open_dialog(self):
        self.window._open_image_path(self.path)
        self.assertIsNotNone(self.window._image_dialog)
        return self.window._image_dialog

    def submit(self, position):
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.window._confirm_image_position(position)
        self.ready()

    def test_accepted_image_replaces_tree_with_custom_root(self):
        self.play('e2e4')
        previous = self.controller.tree
        self.open_dialog()
        position = PositionSnapshot('7k/8/8/8/8/8/8/R6K b - - 19 42')
        self.submit(position)
        self.assertIsNot(self.controller.tree, previous)
        self.assertEqual(self.controller.position.fen, position.fen)
        self.assertEqual(len(self.controller.tree), 1)
        self.assertIsNone(self.window._image_dialog)

    def test_rejected_image_preserves_game_and_draft(self):
        self.play('e2e4')
        previous, fen = self.controller.tree, self.controller.position.fen
        dialog = self.open_dialog()
        dialog.draft.set_square('e1', 'K')
        self.submit(PositionSnapshot('8/8/8/8/8/8/8/8 w - - 0 1'))
        self.assertIs(self.controller.tree, previous)
        self.assertEqual(self.controller.position.fen, fen)
        self.assertIs(self.window._image_dialog, dialog)
        self.assertEqual(dialog.draft.cells['e1'], 'K')
        self.assertIn('rejected', dialog.message.text())
        self.assertIn('Image:', self.window.error_label.text())

    def test_rejection_restores_repetition_history(self):
        for move in ('g1f3', 'g8f6', 'f3g1', 'f6g8') * 2:
            self.play(move)
        previous = self.controller.tree
        self.open_dialog()
        self.submit(PositionSnapshot('8/8/8/8/8/8/8/8 w - - 0 1'))
        self.assertIs(self.controller.tree, previous)
        self.assertEqual(self.controller.game_status, 'threefold-repetition')

    def test_cancel_keeps_current_tree(self):
        previous = self.controller.tree
        self.open_dialog().reject()
        self.assertIs(self.controller.tree, previous)
        self.assertIsNone(self.window._image_dialog)

    def test_declining_replace_keeps_dialog_and_game(self):
        self.play('e2e4')
        previous = self.controller.tree
        dialog = self.open_dialog()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            self.window._confirm_image_position(PositionSnapshot(STARTING_FEN))
        self.assertIs(self.controller.tree, previous)
        self.assertFalse(dialog._validating)

    def test_retry_after_referee_rejection(self):
        dialog = self.open_dialog()
        self.submit(PositionSnapshot('8/8/8/8/8/8/8/8 w - - 0 1'))
        self.assertFalse(dialog._validating)
        self.submit(PositionSnapshot(STARTING_FEN))
        self.assertIsNone(self.window._image_dialog)
        self.assertEqual(self.controller.position.fen, STARTING_FEN)

    def test_close_window_during_recognition(self):
        self.window._image_recognizer = 'fixture_recognizer:slow'
        self.window._vision_path = FIXTURES

        dialog = self.open_dialog()
        dialog.orientation.setCurrentIndex(1)
        dialog.recognize_button.click()
        self.assertIsNotNone(dialog._worker)

        self.window.close()
        stage4.wait_until(lambda: not self.window.isVisible())
        self.assertIsNone(self.window._image_dialog)
        self.assertTrue(self.window._referee_stopped)

    def test_close_window_during_referee_validation(self):
        self.open_dialog()
        self.window._confirm_image_position(PositionSnapshot(STARTING_FEN))
        self.window.close()
        stage4.wait_until(lambda: not self.window.isVisible())
        self.assertIsNone(self.window._image_dialog)
        self.assertTrue(self.window._referee_stopped)
