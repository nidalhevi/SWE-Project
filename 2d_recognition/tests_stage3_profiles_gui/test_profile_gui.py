"""Real Qt profile selection/worker checks; no C referee is needed here."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from lichess_2d.board_locator_2d import BoardRect
from lichess_2d.dialog import LichessImageImportDialog
from lichess_2d.notation import parse_placement
from lichess_2d.theme_profiles import START, approve_profile, create_profile
from tests_lichess2d.fixtures import MIDDLE, render

APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate):
    deadline = time.monotonic() + 15
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Timed out waiting for the recognition worker')
        QTest.qWait(10)


class ProfileGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.profile = create_profile(render(START), name='GUI profile', output_dir=cls.root / 'approved', white_bottom=True)
        approve_profile(cls.profile.path)
        cls.draft = create_profile(render(START), name='Draft', output_dir=cls.root / 'draft', white_bottom=True)
        cls.image = cls.root / 'midgame.png'
        render(MIDDLE, cell=64).save(cls.image)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.dialog = LichessImageImportDialog(self.image, backend='lichess_2d.adapter:recognize', vision_path=str(ROOT))
        self.dialog.show()

    def tearDown(self):
        self.dialog.force_close()
        wait_for(lambda: not self.dialog.isVisible())
        self.dialog.deleteLater()
        APP.processEvents()

    def choose(self, path):
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
            self.dialog.profile_button.click()

    def test_reviewed_profile_can_be_selected_and_builtin_restored(self):
        self.choose(self.profile.path)
        self.assertEqual(self.dialog._profile_path, str(self.profile.path))
        self.assertIn('GUI profile', self.dialog.profile_label.text())
        self.dialog.builtin_button.click()
        self.assertIsNone(self.dialog._profile_path)

    def test_draft_selection_preserves_current_profile(self):
        self.choose(self.profile.path)
        self.choose(self.draft.path)
        self.assertEqual(self.dialog._profile_path, str(self.profile.path))
        self.assertIn('draft', self.dialog.message.text())

    def test_cancelling_profile_picker_preserves_selection(self):
        self.choose(self.profile.path)
        self.choose('')
        self.assertEqual(self.dialog._profile_path, str(self.profile.path))

    def test_real_worker_uses_profile_and_cannot_change_global_environment(self):
        self.choose(self.profile.path)
        self.dialog._board_rect = BoardRect(0, 0, 512, 512)
        self.dialog.orientation.setCurrentIndex(1)
        before = os.environ.get('CHESS_2D_PROFILE')
        self.dialog.recognize_button.click()
        self.assertFalse(self.dialog.profile_button.isEnabled())
        self.assertEqual(self.dialog._worker.process.processEnvironment().value('CHESS_2D_PROFILE'), str(self.profile.path))
        wait_for(lambda: self.dialog._worker is None)
        self.assertEqual(self.dialog.draft.cells, parse_placement(MIDDLE))
        self.assertIn('GUI profile', self.dialog.message.text())
        self.assertEqual(os.environ.get('CHESS_2D_PROFILE'), before)

    def test_close_during_profile_recognition_removes_crop_after_worker_closes(self):
        self.choose(self.profile.path)
        self.dialog._board_rect = BoardRect(0, 0, 512, 512)
        self.dialog.orientation.setCurrentIndex(1)
        temporary = Path(self.dialog._crop_files.name)
        self.dialog.recognize_button.click()
        self.dialog.force_close()
        wait_for(lambda: not self.dialog.isVisible())
        self.assertFalse(temporary.exists())
