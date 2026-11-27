"""Qt crop selection. The grid uses original-image pixels, not preview pixels."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                              QSpinBox, QVBoxLayout, QWidget)
from .board_locator_2d import BoardRect, PreviewMapping, grid_segments, square_name


class CropCanvas(QWidget):
    rectangle_changed = Signal(object)

    def __init__(self, pixmap, image_size, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.image_size = image_size
        self.rectangle = None
        self.anchor = None
        self.white_bottom = True
        self.setMinimumSize(320, 280)

    def image_geometry(self):
        return QRectF(*self.preview_mapping().geometry)

    def preview_mapping(self):
        return PreviewMapping(self.image_size, (self.width(), self.height()))

    def source_point(self, point):
        return QPointF(*self.preview_mapping().to_source(point.x(), point.y()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#252525'))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        geometry = self.image_geometry()
        painter.drawPixmap(geometry, self.pixmap, QRectF(self.pixmap.rect()))
        if self.rectangle is not None:
            rect = self.rectangle
            scale = geometry.width() / self.image_size[0]
            x, y = geometry.left() + rect.left * scale, geometry.top() + rect.top * scale
            width, height = rect.width * scale, rect.height * scale
            mapping = self.preview_mapping()
            painter.setPen(QPen(QColor(255, 179, 0, 170), 1))
            for x1, y1, x2, y2 in grid_segments(rect):
                painter.drawLine(QPointF(*mapping.to_preview(x1, y1)), QPointF(*mapping.to_preview(x2, y2)))
            font = QFont()
            font.setPixelSize(max(9, min(15, int(width / 8 * .23))))
            painter.setFont(font)
            painter.setPen(QColor('#ffcf50'))
            for row in range(8):
                for column in range(8):
                    label_rect = QRectF(x + column * width / 8 + 3, y + row * height / 8 + 2,
                                       width / 8 - 5, height / 8 - 4)
                    painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                     square_name(row, column, self.white_bottom))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_geometry().contains(event.position()):
            self.anchor = self.source_point(event.position())

    def mouseMoveEvent(self, event):
        if self.anchor is None:
            return
        point = self.source_point(event.position())
        dx, dy = point.x() - self.anchor.x(), point.y() - self.anchor.y()
        side = int(min(abs(dx), abs(dy)))
        left = round(self.anchor.x()) - (side if dx < 0 else 0)
        top = round(self.anchor.y()) - (side if dy < 0 else 0)
        self.rectangle_changed.emit(BoardRect(left, top, side, side))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mouseMoveEvent(event)
            self.anchor = None


class BoardCropDialog(QDialog):
    def __init__(self, pixmap, image_size, rectangle=None, parent=None, *, white_bottom=True):
        super().__init__(parent)
        self.setWindowTitle('Select the Lichess 8×8 board')
        self.resize(900, 760)
        self.image_size = image_size
        self.rectangle = None
        layout = QVBoxLayout(self)
        instructions = QLabel('Drag from a corner of the board to its opposite corner. '
                              'The gold lines must follow all 64 squares. Exclude outside labels and panels. '
                              'Adjust the pixel fields if needed, then confirm.')
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.canvas = CropCanvas(pixmap, image_size, self)
        self.canvas.white_bottom = white_bottom
        layout.addWidget(self.canvas, 1)
        fields = QHBoxLayout()
        self.left, self.top, self.side = QSpinBox(), QSpinBox(), QSpinBox()
        for field, name, maximum in ((self.left, 'Left', image_size[0] - 1),
                                     (self.top, 'Top', image_size[1] - 1),
                                     (self.side, 'Board width', min(image_size))):
            fields.addWidget(QLabel(name))
            field.setRange(0, maximum)
            field.setSuffix(' px')
            fields.addWidget(field)
            field.valueChanged.connect(self._fields_changed)
        layout.addLayout(fields)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.canvas.rectangle_changed.connect(self.set_rectangle)
        if rectangle is None and abs(image_size[0] - image_size[1]) <= 2:
            rectangle = BoardRect(0, 0, min(image_size), min(image_size))
        self.set_rectangle(rectangle or BoardRect(0, 0, 0, 0))

    def _fields_changed(self, *args):
        self.set_rectangle(BoardRect(self.left.value(), self.top.value(), self.side.value(), self.side.value()))

    def set_rectangle(self, rectangle):
        self.rectangle = rectangle
        for field, value in ((self.left, rectangle.left), (self.top, rectangle.top), (self.side, rectangle.width)):
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self.canvas.rectangle = rectangle
        self.canvas.update()
        try:
            rectangle.checked(self.image_size)
            message, valid = ('Check all grid lines and square names. Output: 512×512 board, '
                              '64 upright crops of 64×64 pixels.'), True
        except ValueError as error:
            message, valid = str(error), False
        self.status.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
