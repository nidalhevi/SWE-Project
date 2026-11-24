"""Review an image-derived draft before the controller validates a new tree."""
from pathlib import Path
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)
from board_widget import BoardWidget, PIECE_SYMBOLS
from image_import import ImageDraft, ImageImportError, PositionMetadata, UNKNOWN
from image_recognition_client import RecognitionClient


class DraftBoard(BoardWidget):
    def __init__(self, draft, parent=None):
        super().__init__(parent)
        self.draft = draft
        self.set_interactive(True)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        try:
            left, top, size = self._board_geometry()
            font = QFont()
            font.setPixelSize(max(12, int(size * .5)))
            painter.setFont(font)
            uncertain = set(self.draft.uncertain_squares)
            for row in range(8):
                for column in range(8):
                    square = self._square_name(row, column)
                    rect = QRectF(left + column * size, top + row * size, size, size)
                    if self.draft.cells[square] == UNKNOWN:
                        painter.setPen(QColor('#B3261E'))
                        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, '?')
                    elif square in uncertain:
                        painter.setPen(QPen(QColor('#D86E00'), 3))
                        painter.drawRect(rect.adjusted(2, 2, -2, -2))
        finally:
            painter.end()


class ImageImportDialog(QDialog):
    position_requested = Signal(object)

    def __init__(self, image_path, parent=None, *, backend=None, vision_path=None):
        super().__init__(parent)
        self.setWindowTitle('Import image — review position')
        self.setModal(True)
        self.resize(1140, 820)
        self.path = str(Path(image_path).resolve())
        self.backend = backend
        self.vision_path = vision_path
        self.draft = ImageDraft()
        self._worker = None
        self._request_id = 0
        self._validating = False
        self._closing = False
        self._forced = False
        self._selected = None
        self._dirty = False
        self._pixmap = self._load_image()
        layout = QVBoxLayout(self)
        note = QLabel('Correct every piece and unknown square. Position details must come from you; '
                      'a single image does not establish move history. Import starts a new game tree.')
        note.setWordWrap(True)
        layout.addWidget(note)
        columns = QHBoxLayout()
        left = QVBoxLayout()
        self.photo = QLabel()
        self.photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo.setMinimumSize(240, 220)
        self.photo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        left.addWidget(self.photo, stretch=1)
        self.orientation = QComboBox()
        self.orientation.addItem('Choose image orientation…', None)
        self.orientation.addItem('White at bottom — a1 at lower left', True)
        self.orientation.addItem('Black at bottom — h8 at lower left', False)
        left.addWidget(self.orientation)
        backend_note = QLabel('Recognizer: ' + (backend or 'not configured — manual correction is available'))
        backend_note.setWordWrap(True)
        left.addWidget(backend_note)
        recognition_buttons = QHBoxLayout()
        self.recognize_button = QPushButton('Run recognition')
        self.stop_button = QPushButton('Stop recognition')
        self.stop_button.setEnabled(False)
        recognition_buttons.addWidget(self.recognize_button)
        recognition_buttons.addWidget(self.stop_button)
        left.addLayout(recognition_buttons)
        columns.addLayout(left, stretch=1)
        self.editor = QWidget()
        right = QVBoxLayout(self.editor)
        self.board = DraftBoard(self.draft)
        right.addWidget(self.board, stretch=1)
        self.square_label = QLabel('Choose a piece below, then click squares to place it.')
        self.square_label.setWordWrap(True)
        right.addWidget(self.square_label)
        self.palette = QComboBox()
        self.palette.addItem('Empty — erase a piece', None)
        names = {'P': 'Pawn', 'N': 'Knight', 'B': 'Bishop', 'R': 'Rook', 'Q': 'Queen', 'K': 'King'}
        for code in 'PNBRQKpnbrqk':
            color = 'White' if code.isupper() else 'Black'
            self.palette.addItem(f'{PIECE_SYMBOLS[code]}  {color} {names[code.upper()]}', code)
        self.palette.addItem('Unknown — needs review', UNKNOWN)
        right.addWidget(self.palette)
        draft_buttons = QHBoxLayout()
        self.empty_button = QPushButton('Mark unknown squares empty')
        self.rotate_button = QPushButton('Rotate assignments 180°')
        draft_buttons.addWidget(self.empty_button)
        draft_buttons.addWidget(self.rotate_button)
        right.addLayout(draft_buttons)
        placement_row = QHBoxLayout()
        self.placement = QLineEdit()
        self.placement.setPlaceholderText('Optional: paste only a FEN piece-placement field')
        self.placement_button = QPushButton('Use placement')
        placement_row.addWidget(self.placement)
        placement_row.addWidget(self.placement_button)
        right.addLayout(placement_row)
        metadata = QGridLayout()
        self.turn = QComboBox()
        self.turn.addItem('Choose side to move…', None)
        self.turn.addItem('White', 'w')
        self.turn.addItem('Black', 'b')
        metadata.addWidget(QLabel('Side to move:'), 0, 0)
        metadata.addWidget(self.turn, 0, 1)
        castling = QHBoxLayout()
        self.rights = {}
        for code, label in [('K', 'White O-O'), ('Q', 'White O-O-O'), ('k', 'Black O-O'), ('q', 'Black O-O-O')]:
            box = QCheckBox(label)
            box.setToolTip('Select only if this king and rook have never moved.')
            self.rights[code] = box
            castling.addWidget(box)
        metadata.addWidget(QLabel('Castling rights:'), 1, 0)
        metadata.addLayout(castling, 1, 1, 1, 3)
        self.ep = QLineEdit('-')
        self.ep.setMaxLength(2)
        self.ep.setToolTip('The target square from the last double pawn push, e.g. e3, or - for none.')
        metadata.addWidget(QLabel('En passant target:'), 2, 0)
        metadata.addWidget(self.ep, 2, 1)
        self.halfmove = QSpinBox()
        self.halfmove.setRange(0, 9999)
        self.halfmove.setToolTip('Plies since the last pawn move or capture. Default 0 starts a fresh clock.')
        self.fullmove = QSpinBox()
        self.fullmove.setRange(1, 9999)
        metadata.addWidget(QLabel('Halfmove clock:'), 3, 0)
        metadata.addWidget(self.halfmove, 3, 1)
        metadata.addWidget(QLabel('Fullmove number:'), 3, 2)
        metadata.addWidget(self.fullmove, 3, 3)
        right.addLayout(metadata)
        self.reviewed = QCheckBox('I reviewed the pieces, side to move, castling, en passant, and counters.')
        right.addWidget(self.reviewed)
        columns.addWidget(self.editor, stretch=2)
        layout.addLayout(columns, stretch=1)
        self.message = QLabel('Unknown squares are marked ?. Orange borders indicate confidence below 80%.')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        footer = QHBoxLayout()
        self.count_label = QLabel()
        footer.addWidget(self.count_label)
        footer.addStretch()
        self.cancel_button = QPushButton('Cancel')
        self.import_button = QPushButton('Validate and open position')
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.import_button)
        layout.addLayout(footer)
        self.board.square_clicked.connect(self._edit_square)
        self.empty_button.clicked.connect(self._empty_unknown)
        self.rotate_button.clicked.connect(self._rotate)
        self.placement_button.clicked.connect(self._use_placement)
        self.recognize_button.clicked.connect(self._recognize)
        self.stop_button.clicked.connect(self._cancel_recognition)
        self.orientation.currentIndexChanged.connect(self._orientation_changed)
        self.cancel_button.clicked.connect(self.reject)
        self.import_button.clicked.connect(self._confirm)
        self.turn.currentIndexChanged.connect(self._unreview)
        self.ep.textChanged.connect(self._unreview)
        self.halfmove.valueChanged.connect(self._unreview)
        self.fullmove.valueChanged.connect(self._unreview)
        for checkbox in self.rights.values():
            checkbox.toggled.connect(self._unreview)
        self._refresh()
        self._fit_image()

    def _load_image(self):
        path = Path(self.path)
        if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
            raise ImageImportError('Choose a readable image smaller than 50 MiB')
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 60_000_000:
            raise ImageImportError('Unsupported image or image larger than 60 megapixels')
        reader.setScaledSize(size.scaled(QSize(1200, 1200), Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            raise ImageImportError('Cannot read image: ' + reader.errorString())
        return QPixmap.fromImage(image)

    def _fit_image(self):
        if hasattr(self, 'photo'):
            self.photo.setPixmap(self._pixmap.scaled(self.photo.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()

    def _unreview(self, *args):
        self.reviewed.setChecked(False)

    def _refresh(self):
        self.board.set_position(self.draft.preview())
        self.board.set_selection(self._selected, ())
        self.count_label.setText(f'{len(self.draft.unknown_squares)} unknown; '
                                 f'{len(self.draft.uncertain_squares)} low-confidence squares')

    def _changed(self):
        self._dirty = True
        self._unreview()
        self._refresh()

    def _edit_square(self, square):
        if self._worker is not None or self._validating or self._closing:
            return
        self._selected = square
        piece = self.palette.currentData()
        self.draft.set_square(square, piece)
        self.square_label.setText(f'{square}: ' + ('empty' if piece is None else piece))
        self._changed()

    def _empty_unknown(self):
        self.draft.mark_unknown_empty()
        self._changed()

    def _rotate(self):
        self.draft.rotate_assignments()
        self._selected = None
        self._changed()
        self.message.setText('Assignments rotated. Check the square coordinates against the image.')

    def _use_placement(self):
        try:
            self.draft.load_placement(self.placement.text())
        except ImageImportError as error:
            self.message.setText(str(error))
        else:
            self._changed()

    def _orientation_changed(self, index):
        value = self.orientation.currentData()
        if value is not None and self.board._flipped == value:
            self.board.flip()
        self._unreview()
        self.message.setText('Editor view changed. Recognition uses the selected orientation when you run it; '
                             'existing piece assignments keep their square names.')

    def _set_busy(self):
        busy = self._worker is not None or self._validating or self._closing
        self.editor.setEnabled(not busy)
        self.orientation.setEnabled(not busy)
        self.recognize_button.setEnabled(not busy)
        self.stop_button.setEnabled(self._worker is not None and not self._closing)
        self.import_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not self._validating and not self._closing)

    def _recognize(self):
        if self._worker is not None or self._validating or self._closing:
            return
        orientation = self.orientation.currentData()
        if orientation is None:
            self.message.setText('Choose the image orientation before recognition')
            return
        if self._dirty:
            answer = QMessageBox.question(self, 'Replace draft?', 'Recognition will replace your current piece edits. Continue?',
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._request_id += 1
        self._worker = RecognitionClient(self)
        self._worker.completed.connect(self._recognized)
        self._worker.failed.connect(self._recognition_failed)
        self._worker.closed.connect(self._worker_closed)
        self.message.setText('Recognizing pieces… You can stop recognition and edit manually.')
        self._set_busy()
        self._worker.start(self.path, request_id=self._request_id, white_bottom=orientation,
                           backend=self.backend, vision_path=self.vision_path)

    def _recognized(self, result):
        if self._closing or result.request_id != self._request_id:
            return
        if self.draft.apply(result):
            self._dirty = False
            self._unreview()
            self._refresh()
            self.message.setText(result.message or 'Recognition complete. Correct errors and review all position details.')
        else:
            self.message.setText(result.message or 'Recognition unavailable. Enter the pieces manually.')

    def _recognition_failed(self, message):
        if not self._closing:
            self.message.setText(message + '\nYou can continue correcting the position manually.')

    def _cancel_recognition(self):
        if self._worker is not None:
            self._request_id += 1  # Invalidate results before cancelling the process.
            self.message.setText('Recognition cancelled. Manual correction is available.')
            self._worker.cancel()

    def _worker_closed(self):
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_busy()
        if self._closing:
            super().reject()

    def _confirm(self):
        if self._worker is not None or self._validating or self._closing:
            return
        if self.orientation.currentData() is None:
            self.message.setText('Choose the image orientation and check the square coordinates')
            return
        metadata = PositionMetadata(self.turn.currentData(),
                                    ''.join(code for code, box in self.rights.items() if box.isChecked()) or '-',
                                    self.ep.text().strip(), self.halfmove.value(), self.fullmove.value())
        try:
            position = self.draft.position(metadata, reviewed=self.reviewed.isChecked())
        except ImageImportError as error:
            self.message.setText(str(error))
            return
        self.position_requested.emit(position)

    def begin_validation(self):
        self._validating = True
        self.message.setText('Validating with the referee…')
        self._set_busy()

    def validation_failed(self, message):
        self._validating = False
        self.message.setText('Referee rejected the position: ' + message + '\nCorrect the draft and try again.')
        self._set_busy()

    def validation_succeeded(self):
        self._validating = False
        self.accept()

    def reject(self):
        if self._validating and not self._forced:
            self.message.setText('Wait for referee validation to finish before closing this dialog.')
            return
        self._closing = True
        self._set_busy()
        if self._worker is not None:
            self._cancel_recognition()
        else:
            super().reject()

    def force_close(self):
        self._forced = True
        self._validating = False
        self.reject()

    def closeEvent(self, event):
        event.ignore()
        self.reject()
