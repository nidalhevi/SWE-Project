"""Extend the existing stage-8 editor with a board-cropping step.

The C referee, controller, game tree, cancellation, review and confirmation
behavior stay in the existing implementation. The worker receives a temporary
PNG containing only the confirmed board, preserving its public protocol.
"""
from pathlib import Path
import tempfile
from PySide6.QtCore import QProcessEnvironment
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton
from image_import_dialog import ImageImportDialog
from image_recognition_client import RecognitionClient
from .board_locator_2d import normalize_board, load_image
from .crop_dialog import BoardCropDialog
from .theme_profiles import load_profile


class LichessImageImportDialog(ImageImportDialog):
    def __init__(self, image_path, parent=None, *, backend=None, vision_path=None):
        super().__init__(image_path, parent, backend=backend, vision_path=vision_path)
        self._board_rect = None
        self._profile_path = None
        self._crop_files = tempfile.TemporaryDirectory(prefix='chess-lichess-2d-')
        self.finished.connect(self._cleanup_crop)
        row = QHBoxLayout()
        self.crop_button = QPushButton('Select / adjust 8×8 board…')
        self.crop_button.clicked.connect(self._choose_board)
        self.crop_label = QLabel('Cburnett pieces • select the board before recognition')
        row.addWidget(self.crop_button)
        row.addWidget(self.crop_label, 1)
        self.layout().insertLayout(1, row)
        profiles = QHBoxLayout()
        self.profile_button = QPushButton('Choose calibrated profile…')
        self.profile_button.clicked.connect(self._choose_profile)
        self.builtin_button = QPushButton('Use bundled Cburnett')
        self.builtin_button.clicked.connect(self._use_builtin)
        self.profile_label = QLabel('Profile: bundled Cburnett')
        profiles.addWidget(self.profile_button)
        profiles.addWidget(self.builtin_button)
        profiles.addWidget(self.profile_label, 1)
        self.layout().insertLayout(2, profiles)
        self.message.setText('Select the 8×8 board and choose its orientation. '
                             'Matching runs in the existing worker. Orange borders show low match quality.')

    def _choose_profile(self):
        if self._worker is not None or self._validating or self._closing:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a reviewed theme profile',
                                             str(Path(__file__).resolve().parents[1] / 'profiles'),
                                             'Theme profile (profile.json)')
        if path:
            try:
                profile = load_profile(path)
                self._profile_path = str(profile.path)
                self.profile_label.setText('Profile: ' + profile.name)
                self._unreview()
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.message.setText('Cannot select profile: ' + str(error))

    def _use_builtin(self):
        if self._worker is not None or self._validating or self._closing:
            return
        self._profile_path = None
        self.profile_label.setText('Profile: bundled Cburnett')
        self._unreview()

    def _choose_board(self):
        if self._worker is not None or self._validating or self._closing:
            return False
        try:
            image = load_image(self.path)
            image_size = image.size
            image.close()
            orientation = self.orientation.currentData()
            dialog = BoardCropDialog(self._pixmap, image_size, self._board_rect, self,
                                     white_bottom=True if orientation is None else orientation)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return False
            self._board_rect = dialog.rectangle
            rect = self._board_rect
            self.crop_label.setText(f'Confirmed board: left {rect.left}, top {rect.top}, '
                                    f'{rect.width} × {rect.height} pixels → 512×512, 64 squares')
            self._unreview()
            return True
        except (OSError, ValueError) as error:
            self.message.setText(str(error))
            return False

    def _recognize(self):
        if self._worker is not None or self._validating or self._closing:
            return
        if self.orientation.currentData() is None:
            super()._recognize()  # Keep the existing orientation feedback.
            return
        if self._board_rect is None and not self._choose_board():
            return
        if self._dirty:
            answer = QMessageBox.question(self, 'Replace draft?', 'Recognition will replace your current piece edits. Continue?',
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            if self._profile_path:
                load_profile(self._profile_path)
            with load_image(self.path) as image:
                board = normalize_board(image, self._board_rect)
                cropped_path = Path(self._crop_files.name) / 'confirmed-board.png'
                board.save(cropped_path)
                board.close()
            self._request_id += 1
            self._worker = RecognitionClient(self)
            environment = QProcessEnvironment.systemEnvironment()
            if self._profile_path:
                environment.insert('CHESS_2D_PROFILE', self._profile_path)
            else:
                environment.remove('CHESS_2D_PROFILE')
            # Per-worker configuration: never mutate global process environment.
            self._worker.process.setProcessEnvironment(environment)
            self._worker.completed.connect(self._recognized)
            self._worker.failed.connect(self._recognition_failed)
            self._worker.closed.connect(self._worker_closed)
            self.message.setText('Recognizing pieces with the selected theme profile…')
            self._set_busy()
            self._worker.start(str(cropped_path), request_id=self._request_id,
                               white_bottom=self.orientation.currentData(), backend=self.backend,
                               vision_path=self.vision_path)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.message.setText(str(error))

    def _set_busy(self):
        super()._set_busy()
        if hasattr(self, 'crop_button'):
            enabled = self._worker is None and not self._validating and not self._closing
            self.crop_button.setEnabled(enabled)
            self.profile_button.setEnabled(enabled)
            self.builtin_button.setEnabled(enabled)

    def _cleanup_crop(self, *args):
        # Parent waits for worker.closed before rejecting during recognition.
        self._crop_files.cleanup()
