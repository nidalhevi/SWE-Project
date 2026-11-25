"""Qt + actual worker + actual C checks; requires the existing GUI/test folders.

Run enable_lichess_2d.py first. Run this separately from the non-Qt suite.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox
import tests_stage4.test_gui as stage4
from lichess_2d.board_locator import BoardRect
from lichess_2d.crop_dialog import BoardCropDialog
from lichess_2d.dialog import LichessImageImportDialog
from lichess_2d.integration import image_import_dialog
from lichess_2d.notation import parse_placement
from image_import_dialog import ImageImportDialog
from tests_lichess2d.fixtures import END, render


class CropTests(unittest.TestCase):
    def test_preview_coordinates_map_to_original_pixels(self):
        dialog = BoardCropDialog(QPixmap(1000, 800), (2000, 1600))
        canvas = dialog.canvas
        canvas.resize(1000, 1000)
        point = canvas.source_point(QPointF(500, 500))
        self.assertEqual((point.x(), point.y()), (1000, 800))

    def test_invalid_crop_cannot_be_confirmed(self):
        dialog = BoardCropDialog(QPixmap(700, 600), (700, 600))
        button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(button.isEnabled())
        dialog.set_rectangle(BoardRect(100, 80, 512, 512))
        self.assertTrue(button.isEnabled())
        dialog.set_rectangle(BoardRect(300, 80, 512, 512))
        self.assertFalse(button.isEnabled())

    def test_other_backends_keep_original_editor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'board.png'
            render().save(path)
            dialog = image_import_dialog(path, backend='fixture_recognizer:recognize')
            self.assertIs(type(dialog), ImageImportDialog)
            dialog.force_close()


class RecognitionGuiTests(unittest.TestCase):
    ready = stage4.LegalMoveGuiTests.ready
    play = stage4.LegalMoveGuiTests.play
    click = stage4.LegalMoveGuiTests.click

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'Lichess ü screenshot.png'
        image = Image.new('RGB', (720, 650), '#262626')
        image.paste(render(END, cell=64, white_bottom=False), (72, 70))
        image.save(self.path)
        stage4.LegalMoveGuiTests.setUp(self)
        self.window._image_recognizer = 'lichess_2d.adapter:recognize'
        self.window._open_image_path(str(self.path))
        self.dialog = self.window._image_dialog
        self.assertIsInstance(self.dialog, LichessImageImportDialog,
                              'Run python enable_lichess_2d.py before these tests')

    def tearDown(self):
        stage4.LegalMoveGuiTests.tearDown(self)
        self.directory.cleanup()

    def recognize(self):
        self.dialog._board_rect = BoardRect(72, 70, 512, 512)
        self.dialog.orientation.setCurrentIndex(2)
        self.dialog.recognize_button.click()
        stage4.wait_until(lambda: self.dialog._worker is None)

    def test_screenshot_worker_review_referee_board_roundtrip(self):
        self.recognize()
        self.assertEqual(self.dialog.draft.cells, parse_placement(END))
        self.assertIsNone(self.dialog.turn.currentData())
        self.assertFalse(self.dialog.reviewed.isChecked())
        self.dialog.turn.setCurrentIndex(1)
        self.dialog.reviewed.setChecked(True)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            self.dialog.import_button.click()
        stage4.wait_until(lambda: self.window._image_dialog is None)
        self.ready()
        self.assertEqual(self.controller.position.fen, END + ' w - - 0 1')
        self.assertEqual(len(self.controller.tree), 1)

    def test_crop_cancellation_does_not_start_worker(self):
        self.dialog.orientation.setCurrentIndex(1)
        with patch.object(self.dialog, '_choose_board', return_value=False):
            self.dialog.recognize_button.click()
        self.assertIsNone(self.dialog._worker)

    def test_close_during_real_recognition_cleans_temporary_crop(self):
        self.dialog._board_rect = BoardRect(72, 70, 512, 512)
        self.dialog.orientation.setCurrentIndex(2)
        temporary = Path(self.dialog._crop_files.name)
        self.dialog.recognize_button.click()
        self.dialog.force_close()
        stage4.wait_until(lambda: self.window._image_dialog is None)
        self.assertFalse(temporary.exists())
