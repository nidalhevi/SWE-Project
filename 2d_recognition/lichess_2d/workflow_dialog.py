"""Complete stage-6/7 workflow around the original, tested image review editor."""
from pathlib import Path
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton
from image_import_dialog import ImageImportDialog
from image_recognition_client import RecognitionClient
from .adapter_2d import BUILTIN
from .board_locator_2d import load_image
from .crop_dialog import BoardCropDialog
from .profile_preferences import default_preferences_path, load_selection, save_selection
from .proposal_client import BoardProposalClient
from .theme_profiles import load_profile

BACKEND = 'lichess_2d.adapter_2d:recognize'


class ImageImportDialog2D(ImageImportDialog):
    def __init__(self, image_path, parent=None, *, vision_path=None, preferences_path=None):
        self._board_rect = None
        self._pending_inputs = None
        self._last_inputs = None
        self._needs_recognition = False
        self._manual_mode = False
        self._loading_profiles = True
        self._suggested_rect = None
        self._proposal_inputs = None
        self._proposing = False
        self._preferences_path = Path(preferences_path or default_preferences_path())
        self._recognition_root = Path(vision_path or Path(__file__).resolve().parents[1])
        super().__init__(image_path, parent, backend=BACKEND, vision_path=str(self._recognition_root))
        self.setWindowTitle('Import image — recognize and review position')
        for label in self.findChildren(QLabel):
            if label.text().startswith('Recognizer:'):
                label.setText('Recognition: selected theme profile; review required')
        profiles = QHBoxLayout()
        profiles.addWidget(QLabel('1. Theme:'))
        self.profile = QComboBox()
        self.profile.addItem('Choose a matching profile…', None)
        self.profile.addItem('Bundled Cburnett — only for matching icons', BUILTIN)
        profiles.addWidget(self.profile, 1)
        self.browse_profile_button = QPushButton('Browse profiles…')
        self.calibrate_button = QPushButton('Calibrate profile…')
        self.manual_button = QPushButton('Manual correction')
        self.refresh_profiles_button = QPushButton('Refresh profiles')
        for button in (self.browse_profile_button, self.calibrate_button, self.manual_button,
                       self.refresh_profiles_button):
            profiles.addWidget(button)
        self.layout().insertLayout(1, profiles)
        crop_row = QHBoxLayout()
        self.crop_button = QPushButton('2. Confirm / adjust board…')
        self.crop_label = QLabel('Select the playing-board rectangle; then choose orientation and run recognition.')
        self.crop_label.setWordWrap(True)
        crop_row.addWidget(self.crop_button)
        crop_row.addWidget(self.crop_label, 1)
        self.layout().insertLayout(2, crop_row)
        proposals = QHBoxLayout()
        self.propose_button = QPushButton('Suggest board')
        self.proposal_choices = QComboBox()
        self.proposal_choices.addItem('Suggestions require grid confirmation', None)
        self.use_proposal_button = QPushButton('Review suggestion…')
        proposals.addWidget(self.propose_button)
        proposals.addWidget(self.proposal_choices, 1)
        proposals.addWidget(self.use_proposal_button)
        self.layout().insertLayout(3, proposals)
        self._discover_profiles()
        restored_message = self._restore_selection()
        self._loading_profiles = False
        self.profile.currentIndexChanged.connect(self._profile_changed)
        self.browse_profile_button.clicked.connect(self._browse_profile)
        self.calibrate_button.clicked.connect(self._calibrate)
        self.manual_button.clicked.connect(self._enable_manual)
        self.crop_button.clicked.connect(self._choose_board)
        self.propose_button.clicked.connect(self._propose_board)
        self.use_proposal_button.clicked.connect(self._review_proposal)
        self.proposal_choices.currentIndexChanged.connect(self._set_busy)
        self.refresh_profiles_button.clicked.connect(self._refresh_profiles)
        self.message.setText(restored_message or 'Choose a matching profile or calibrate one. '
                             'Manual correction is available. Orange borders indicate low match quality, not probability.')
        self._set_busy()

    def _refresh_profiles(self):
        if not self._busy():
            self._discover_profiles()
            self.message.setText('Reviewed profiles refreshed. Choose the one matching this screenshot, '
                                 'or calibrate an additional theme. No model is selected automatically.')

    def _propose_board(self):
        if self._busy():
            return
        try:
            with load_image(self.path) as image:
                dimensions = image.size
            self.proposal_choices.clear()
            self.proposal_choices.addItem('Searching…', None)
            self._request_id += 1
            self._proposal_inputs = self._fingerprint()
            self._proposing = True
            self._worker = BoardProposalClient(self)
            self._worker.completed.connect(self._proposals_ready)
            self._worker.failed.connect(self._proposal_failed)
            self._worker.closed.connect(self._worker_closed)
            self.message.setText('Looking for an 8×8 board… You must confirm a proposed grid before recognition.')
            self._set_busy()
            self._worker.start(self.path, request_id=self._request_id, image_size=dimensions)
        except (OSError, ValueError) as error:
            self._proposal_failed(str(error))
            if self._worker is not None:
                self._worker.cancel()

    def _proposals_ready(self, result):
        if self._closing or result.request_id != self._request_id:
            return
        if self._proposal_inputs != self._fingerprint():
            self.message.setText('Ignored board suggestions for changed inputs. Search again or select manually.')
            return
        self.proposal_choices.clear()
        self.proposal_choices.addItem('Choose a suggestion to review…', None)
        for i, proposal in enumerate(result.proposals, 1):
            r = proposal.rectangle
            self.proposal_choices.addItem(f'{i}: ({r.left}, {r.top}), {r.width} px — '
                                          f'grid fit {proposal.grid_fit:.2f}', r)
        if result.proposals:
            self.proposal_choices.setCurrentIndex(1)
            self.message.setText('Board suggestions ready. Grid fit is a heuristic, not a probability. '
                                 'Click Review suggestion and check all grid lines; or select manually.')
        else:
            self.message.setText('No reliable board suggestion. Use Confirm / adjust board to select it manually.')

    def _proposal_failed(self, message):
        if not self._closing:
            self.message.setText('Board search failed: ' + message + ' Select the rectangle manually.')

    def _review_proposal(self):
        if self._busy() or self.proposal_choices.currentData() is None:
            return
        if self._proposal_inputs != self._fingerprint():
            self.message.setText('Inputs changed since the suggestions. Search again or select the board manually.')
            return
        self._suggested_rect = self.proposal_choices.currentData()
        try:
            self._choose_board()
        finally:
            self._suggested_rect = None

    def _busy(self):
        return self._worker is not None or self._validating or self._closing

    def _discover_profiles(self):
        root = self._recognition_root / 'profiles'
        for path in sorted(root.glob('*/profile.json')):
            try:
                profile = load_profile(path)
                self._add_profile(profile)
            except (OSError, ValueError, KeyError, TypeError):
                continue  # Drafts/broken profiles are not offered as working models.

    def _add_profile(self, profile):
        value = str(profile.path)
        index = self.profile.findData(value)
        if index < 0:
            self.profile.addItem(profile.name, value)
            index = self.profile.count() - 1
        return index

    def _restore_selection(self):
        try:
            selection = load_selection(self._preferences_path)
            if selection is None:
                return ''
            index = 1 if selection == BUILTIN else self._add_profile(load_profile(selection))
            self.profile.setCurrentIndex(index)
            return 'Remembered profile restored. Confirm the board rectangle and orientation before recognition.'
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.profile.setCurrentIndex(0)
            return 'Saved profile is unavailable: ' + str(error) + ' Choose another, calibrate, or correct manually.'

    def _profile_changed(self, index):
        if self._loading_profiles:
            return
        self._inputs_changed()
        selected = self.profile.currentData()
        try:
            if selected not in (None, BUILTIN):
                load_profile(selected)
            save_selection(selected, self._preferences_path)
            if selected is None:
                self.message.setText('No profile selected. Choose a matching profile, calibrate, or correct manually.')
            else:
                self.message.setText('Profile selected and remembered. Confirm crop and orientation, then run recognition. '
                                     'For an unsupported theme, calibrate or correct manually.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.message.setText('Profile could not be selected or remembered: ' + str(error) +
                                 ' Choose a valid profile, calibrate, or use manual correction.')

    def _browse_profile(self):
        if self._busy():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a reviewed profile.json',
                                             str(self._recognition_root / 'profiles'), 'Theme profiles (*.json)')
        if path:
            try:
                self.profile.setCurrentIndex(self._add_profile(load_profile(path)))
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.message.setText('Cannot use this profile: ' + str(error) + ' Calibrate or correct manually.')

    def _calibrate(self):
        if self._busy():
            return
        try:
            from .calibration_workflow import calibrate_profile
            path = calibrate_profile(self, self._recognition_root / 'profiles')
            if path:
                self.profile.setCurrentIndex(self._add_profile(load_profile(path)))
            else:
                self.message.setText('Calibration/review cancelled. Current profile and position are unchanged. '
                                     'Unreviewed drafts cannot be used for recognition.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.message.setText('Calibration failed: ' + str(error) + ' Use a clean starting-position reference or correct manually.')

    def _enable_manual(self):
        if self._busy():
            return
        self._manual_mode = True
        self._unreview()
        self.message.setText('Manual correction: set every unknown square or paste a known placement. '
                             'Check the orientation, pieces and position details before opening.')

    def _choose_board(self):
        if self._busy():
            return False
        try:
            with load_image(self.path) as image:
                dimensions = image.size
            orientation = self.orientation.currentData()
            selector = BoardCropDialog(self._pixmap, dimensions, self._suggested_rect or self._board_rect, self,
                                       white_bottom=True if orientation is None else orientation)
            if selector.exec() != QDialog.DialogCode.Accepted:
                return False
            self._board_rect = selector.rectangle
            rect = self._board_rect
            self.crop_label.setText(f'Confirmed: left {rect.left}, top {rect.top}, '
                                    f'{rect.width}×{rect.height} pixels. Check orientation before running.')
            self._inputs_changed()
            return True
        except (OSError, ValueError) as error:
            self.message.setText(str(error))
            return False

    def _fingerprint(self):
        def stamp(path):
            try:
                info = Path(path).stat()
                return info.st_mtime_ns, info.st_size
            except (OSError, TypeError):
                return None
        selected = self.profile.currentData()
        rect = self._board_rect
        rectangle = (rect.left, rect.top, rect.width, rect.height) if rect else None
        return selected, stamp(selected) if selected not in (None, BUILTIN) else None, rectangle, self.orientation.currentData(), stamp(self.path)

    def _inputs_changed(self):
        self._unreview()
        if self._worker is not None:
            self._request_id += 1  # Invalidate before cancelling an old-input request.
            self._worker.cancel()
        if self._last_inputs is not None:
            self._needs_recognition = self._last_inputs != self._fingerprint()

    def _orientation_changed(self, index):
        super()._orientation_changed(index)
        if hasattr(self, 'profile'):
            self._inputs_changed()

    def _changed(self):
        super()._changed()
        self._manual_mode = True

    def _refresh(self):
        super()._refresh()
        self.count_label.setText(f'{len(self.draft.unknown_squares)} unknown; '
                                 f'{len(self.draft.uncertain_squares)} squares with low match quality')

    def _recognize(self):
        if self._busy():
            return
        selection = self.profile.currentData()
        if selection is None:
            self.message.setText('Choose a matching profile, calibrate one, or select manual correction. '
                                 'No model has been selected automatically.')
            return
        if self._board_rect is None and not self._choose_board():
            return
        orientation = self.orientation.currentData()
        if orientation is None:
            self.message.setText('Choose White at bottom or Black at bottom before recognition.')
            return
        if self._dirty:
            answer = QMessageBox.question(self, 'Replace draft?', 'Recognition will replace your piece edits. Continue?',
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            if selection != BUILTIN:
                load_profile(selection)
            self._request_id += 1
            self._pending_inputs = self._fingerprint()
            self._worker = RecognitionClient(self)
            self._worker.completed.connect(self._recognized)
            self._worker.failed.connect(self._recognition_failed)
            self._worker.closed.connect(self._worker_closed)
            rect = self._board_rect
            self._unreview()
            self.message.setText('Recognizing with the selected profile… Results require your review.')
            self._set_busy()
            self._worker.start(self.path, request_id=self._request_id, white_bottom=orientation,
                               backend=BACKEND, vision_path=self.vision_path, profile_path=selection,
                               board_rect=[rect.left, rect.top, rect.width, rect.height])
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.message.setText(str(error) + ' Calibrate a matching profile or correct manually.')
            if self._worker is not None:
                self._worker.cancel()

    def _recognized(self, result):
        if self._closing or result.request_id != self._request_id:
            return
        if self._pending_inputs != self._fingerprint():
            self.message.setText('Ignored a result for changed image/profile/crop/orientation. Run recognition again.')
            return
        super()._recognized(result)
        if result.status == 'ok':
            self._last_inputs = self._pending_inputs
            self._needs_recognition = False
            self._manual_mode = False

    def _recognition_failed(self, message):
        super()._recognition_failed(message)
        if not self._closing:
            self.message.setText(message + '\nChoose another profile, calibrate, or use manual correction.')

    def _worker_closed(self):
        self._proposing = False
        super()._worker_closed()

    def _cancel_recognition(self):
        proposing = self._proposing
        super()._cancel_recognition()
        if proposing and not self._closing:
            self.message.setText('Board search cancelled. Select the board manually or search again.')

    def _confirm(self):
        if self._needs_recognition and not self._manual_mode:
            self.message.setText('Inputs changed after recognition. Run it again, or choose manual correction and review the board.')
            return
        super()._confirm()  # Existing full metadata/review checks and referee signal.

    def _set_busy(self):
        super()._set_busy()
        if hasattr(self, 'profile'):
            for widget in (self.profile, self.browse_profile_button, self.calibrate_button,
                           self.manual_button, self.crop_button, self.refresh_profiles_button,
                           self.propose_button, self.proposal_choices):
                widget.setEnabled(not self._busy())
            self.use_proposal_button.setEnabled(not self._busy() and self.proposal_choices.currentData() is not None)
