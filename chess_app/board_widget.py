"""Chessboard rendering and mouse input.

This widget displays a position. It does not implement chess rules.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget
from models import PositionSnapshot #added at step 2


FILES = "abcdefgh"

# Uppercase letters represent White; lowercase letters represent Black.
PIECE_SYMBOLS = {
    "K": "♔",
    "Q": "♕",
    "R": "♖",
    "B": "♗",
    "N": "♘",
    "P": "♙",
    "k": "♚",
    "q": "♛",
    "r": "♜",
    "b": "♝",
    "n": "♞",
    "p": "♟",
}


class BoardWidget(QWidget):
    # Other components can connect a function to this signal.
    square_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._pieces: dict[str, str] = {}
        self._selected_square: str | None = None
        self._flipped = False

        # Leave enough space for eight squares and coordinate labels.
        self.setMinimumSize(360, 360)

    
    # def set_position(self, pieces: dict[str, str]) -> None:     # from step 1
        #     """Replace the displayed piece placement.
    
        #     Example input:
        #         {"e1": "K", "e8": "k", "e2": "P"}
    
        #     This is display data, not a complete chess position.
        #     """
        #     self._pieces = dict(pieces)
        #     self._selected_square = None
        #     self.update()
    
    def set_position(self, position: PositionSnapshot) -> None:     # modified, added at step 2
        """Display the pieces derived from an accepted position snapshot."""
        self._pieces = position.pieces
        self._selected_square = None
        self.update()
        
    
    
    def set_selected_square(self, square: str | None) -> None:
        """Highlight a square, or clear the highlight with None."""
        self._selected_square = square
        self.update()

    def flip(self) -> None:
        """Rotate the displayed board by 180 degrees."""
        self._flipped = not self._flipped
        self.update()

    def _board_geometry(self) -> tuple[float, float, float]:
        """Return the board's left edge, top edge, and square size."""
        margin = 28

        # Using the smaller dimension keeps the board square.
        side = max(8.0, min(self.width(), self.height()) - 2 * margin)

        left = (self.width() - side) / 2
        top = (self.height() - side) / 2

        return left, top, side / 8

    def _square_name(self, row: int, column: int) -> str:
        """Convert a displayed row/column to a chess square.

        Screen rows increase downward.

        Normal orientation:
            top-left = a8, bottom-right = h1

        Flipped orientation:
            top-left = h1, bottom-right = a8
        """
        if self._flipped:
            file_index = 7 - column
            rank = row + 1
        else:
            file_index = column
            rank = 8 - row

        return f"{FILES[file_index]}{rank}"

    def square_at(self, point: QPointF) -> str | None:
        """Convert a widget pixel position into a square name."""
        left, top, size = self._board_geometry()

        x = point.x() - left
        y = point.y() - top

        # Ignore clicks in the margin or outside the board.
        if not (0 <= x < size * 8 and 0 <= y < size * 8):
            return None

        column = int(x / size)
        row = int(y / size)

        # Rendering and clicking share this conversion.
        return self._square_name(row, column)

    def mousePressEvent(self, event) -> None:
        """Report left-clicked squares to the rest of the application."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        square = self.square_at(event.position())

        if square is not None:
            self.square_clicked.emit(square)

    def paintEvent(self, event) -> None:
        """Qt calls this whenever the widget needs to be redrawn."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.fillRect(self.rect(), QColor("#252525"))

        left, top, size = self._board_geometry()

        light = QColor("#EEEED2")
        dark = QColor("#769656")
        selected = QColor("#F6D365")

        piece_font = QFont()
        piece_font.setPixelSize(int(size * 0.75))

        label_font = QFont()
        label_font.setPixelSize(14)

        for row in range(8):
            for column in range(8):
                square = self._square_name(row, column)

                rect = QRectF(
                    left + column * size,
                    top + row * size,
                    size,
                    size,
                )

                # a8 is light in the normal orientation.
                color = light if (row + column) % 2 == 0 else dark

                if square == self._selected_square:
                    color = selected

                painter.fillRect(rect, color)

                piece = self._pieces.get(square)

                if piece is not None:
                    painter.setFont(piece_font)
                    painter.setPen(QColor("#171717"))
                    painter.drawText(
                        rect,
                        Qt.AlignmentFlag.AlignCenter,
                        PIECE_SYMBOLS[piece],
                    )

        # File letters below the board.
        painter.setFont(label_font)
        painter.setPen(QColor("#EEEEEE"))

        for column in range(8):
            file_letter = self._square_name(7, column)[0]
            label_rect = QRectF(
                left + column * size,
                top + 8 * size,
                size,
                24,
            )
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignCenter,
                file_letter,
            )

        # Rank numbers to the left of the board.
        for row in range(8):
            rank_number = self._square_name(row, 0)[1]
            label_rect = QRectF(
                left - 24,
                top + row * size,
                24,
                size,
            )
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignCenter,
                rank_number,
            )

        painter.end()