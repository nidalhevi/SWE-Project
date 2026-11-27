"""Draw a chess position and report clicks; rules live in the C referee."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget
from models import Move, PositionSnapshot

FILES = 'abcdefgh'
PIECE_SYMBOLS = dict(zip('KQRBNPkqrbnp', '♔♕♖♗♘♙♚♛♜♝♞♟'))


class BoardWidget(QWidget):
    square_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pieces = {}
        self._selected_square = None
        self._legal_targets = set()
        self._last_move = None
        self._flipped = False
        self._interactive = False
        self.setMinimumSize(360, 360)

    def set_position(self, position: PositionSnapshot):
        self._pieces = position.pieces
        self._selected_square = None
        self._legal_targets.clear()
        self.update()

    def set_selection(self, square, targets):
        self._selected_square = square
        self._legal_targets = set(targets)
        self.update()

    def set_last_move(self, move: Move | None):
        self._last_move = move
        self.update()

    def set_interactive(self, enabled):
        # Don't disable the QWidget: keep full contrast while waiting.
        self._interactive = enabled
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )

    def flip(self):
        self._flipped = not self._flipped
        self.update()

    def _board_geometry(self):
        side = max(8.0, min(self.width(), self.height()) - 56)
        return (self.width() - side) / 2, (self.height() - side) / 2, side / 8

    def _square_name(self, row, column):
        file_index = 7 - column if self._flipped else column
        rank = row + 1 if self._flipped else 8 - row
        return f'{FILES[file_index]}{rank}'

    def square_at(self, point: QPointF):
        left, top, size = self._board_geometry()
        x, y = point.x() - left, point.y() - top
        if not (0 <= x < size * 8 and 0 <= y < size * 8):
            return None
        return self._square_name(int(y / size), int(x / size))

    def mousePressEvent(self, event):
        if self._interactive and event.button() == Qt.MouseButton.LeftButton:
            square = self.square_at(event.position())
            if square is not None:
                self.square_clicked.emit(square)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.fillRect(self.rect(), QColor('#252525'))
            left, top, size = self._board_geometry()
            font = QFont()
            font.setPixelSize(int(size * 0.75))
            painter.setFont(font)
            last_squares = (
                {self._last_move.from_square, self._last_move.to_square}
                if self._last_move is not None else set()
            )
            for row in range(8):
                for column in range(8):
                    square = self._square_name(row, column)
                    rect = QRectF(left + column * size, top + row * size, size, size)
                    color = '#EEEED2' if (row + column) % 2 == 0 else '#769656'
                    if square in last_squares:
                        color = '#CDD26A'
                    if square == self._selected_square:
                        color = '#F6D365'
                    painter.fillRect(rect, QColor(color))
                    if square in self._pieces:
                        painter.setPen(QColor('#171717'))
                        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                                         PIECE_SYMBOLS[self._pieces[square]])
                    if square in self._legal_targets:
                        self._draw_target(painter, rect, size, square in self._pieces)
            self._draw_coordinates(painter, left, top, size)
        finally:
            painter.end()

    def _draw_target(self, painter, rect, size, occupied):
        painter.save()
        if occupied:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor('#285535'), max(2.0, size * 0.06)))
            inset = size * 0.07
            painter.drawEllipse(rect.adjusted(inset, inset, -inset, -inset))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(25, 55, 30, 140))
            painter.drawEllipse(rect.center(), size * 0.12, size * 0.12)
        painter.restore()

    def _draw_coordinates(self, painter, left, top, size):
        font = QFont()
        font.setPixelSize(14)
        painter.setFont(font)
        painter.setPen(QColor('#EEEEEE'))
        for column in range(8):
            rect = QRectF(left + column * size, top + 8 * size, size, 24)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             self._square_name(7, column)[0])
        for row in range(8):
            rect = QRectF(left - 24, top + row * size, 24, size)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             self._square_name(row, 0)[1])
