"""Run on the user's Windows GUI Python; PySide6 is required."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from lichess_2d.board_locator_2d import BoardRect
from lichess_2d.crop_dialog import BoardCropDialog

APP = QApplication.instance() or QApplication([])


class CropSelectorTests(unittest.TestCase):
    def setUp(self):
        self.dialog = BoardCropDialog(QPixmap(900, 700), (1800, 1400), white_bottom=False)
        self.dialog.show()
        APP.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        APP.processEvents()

    def test_orientation_sets_grid_labels(self):
        self.assertFalse(self.dialog.canvas.white_bottom)

    def test_invalid_rectangle_cannot_be_confirmed(self):
        button = self.dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(button.isEnabled())
        self.dialog.set_rectangle(BoardRect(100, 80, 512, 512))
        self.assertTrue(button.isEnabled())
        self.dialog.set_rectangle(BoardRect(1700, 80, 512, 512))
        self.assertFalse(button.isEnabled())

    def test_drag_coordinates_follow_original_image_not_preview(self):
        canvas = self.dialog.canvas
        mapping = canvas.preview_mapping()
        start = QPointF(*mapping.to_preview(200, 200)).toPoint()
        end = QPointF(*mapping.to_preview(800, 800)).toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        selected = self.dialog.rectangle
        self.assertAlmostEqual(selected.left, 200, delta=4)
        self.assertAlmostEqual(selected.top, 200, delta=4)
        self.assertAlmostEqual(selected.width, 600, delta=4)
        self.assertEqual(selected.width, selected.height)

    def test_pixel_controls_update_shared_rectangle(self):
        self.dialog.left.setValue(117)
        self.dialog.top.setValue(83)
        self.dialog.side.setValue(512)
        self.assertEqual(self.dialog.rectangle, BoardRect(117, 83, 512, 512))
        self.assertIs(self.dialog.canvas.rectangle, self.dialog.rectangle)
