"""Main window for the first chess GUI milestone."""

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from board_widget import BoardWidget

from models import PositionSnapshot, STARTING_FEN # added at step 2


def starting_pieces() -> dict[str, str]:
    """Return piece placement for the standard starting position."""
    pieces = {}

    for index, file_letter in enumerate("abcdefgh"):
        pieces[f"{file_letter}1"] = "RNBQKBNR"[index]
        pieces[f"{file_letter}2"] = "P"

        pieces[f"{file_letter}7"] = "p"
        pieces[f"{file_letter}8"] = "rnbqkbnr"[index]

    return pieces


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Chess Analysis — Board Prototype")
        self.resize(720, 800)

        # QMainWindow holds a central widget containing our layout.
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        instructions = QLabel(
            "Click a square to select it. Use Flip board to rotate the view."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        """
        # from step 1, replaced at step 2
        self.board = BoardWidget()
        self.board.set_position(starting_pieces())"""
        
        # The window owns the current snapshot for now.
        # The controller will take this responsibility in a later step.
        self.position = PositionSnapshot(STARTING_FEN)      # modified, added at step 2

        self.board = BoardWidget()      # modified, added at step 2
        self.board.set_position(self.position)      # modified, added at step 2

        # Stretch factor 1 gives the board the available extra space.
        layout.addWidget(self.board, stretch=1)

        controls = QHBoxLayout()

        flip_button = QPushButton("Flip board")
        flip_button.clicked.connect(self.board.flip)
        controls.addWidget(flip_button)

        clear_button = QPushButton("Clear selection")
        clear_button.clicked.connect(self.clear_selection)
        controls.addWidget(clear_button)

        controls.addStretch()
        layout.addLayout(controls)
        
        """
        # from step 1, changed in step 2
        self.status_label = QLabel(
            "Starting position — White to move. Selection demo only."
        )
        layout.addWidget(self.status_label)"""
        
        self.status_label = QLabel(
            f"{self.position.turn_name} to move — selection demo only."
        ) # modified, aded in step 2
        layout.addWidget(self.status_label) # modified, added in step 2

        # The board reports a square; the window chooses the response.
        self.board.square_clicked.connect(self.on_square_clicked)

    def on_square_clicked(self, square: str) -> None:
        """Highlight the clicked square and report its coordinate."""
        self.board.set_selected_square(square)
        self.status_label.setText(
            f"Selected square: {square} — move handling comes next."
        )

    def clear_selection(self) -> None:
        self.board.set_selected_square(None)
        self.status_label.setText("Selection cleared.")