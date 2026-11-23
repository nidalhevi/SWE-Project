"""Main window for the first chess GUI milestone."""

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from board_widget import BoardWidget

from models import PositionSnapshot, STARTING_FEN # added at step 2
from photo_importer import PhotoImporter


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

        # The move list of a photo game sits to the right of the board.
        self.move_list = QListWidget()
        self.move_list.setFixedWidth(150)
        self.move_list.currentRowChanged.connect(self.show_ply)

        board_row = QHBoxLayout()
        board_row.addWidget(self.board, stretch=1)
        board_row.addWidget(self.move_list)

        # Stretch factor 1 gives the board the available extra space.
        layout.addLayout(board_row, stretch=1)

        controls = QHBoxLayout()

        flip_button = QPushButton("Flip board")
        flip_button.clicked.connect(self.board.flip)
        controls.addWidget(flip_button)

        clear_button = QPushButton("Clear selection")
        clear_button.clicked.connect(self.clear_selection)
        controls.addWidget(clear_button)

        self.open_photos_button = QPushButton("Open photo game…")
        self.open_photos_button.clicked.connect(self.open_photo_game)
        controls.addWidget(self.open_photos_button)

        self.previous_button = QPushButton("◀")
        self.previous_button.clicked.connect(lambda: self.step_ply(-1))
        controls.addWidget(self.previous_button)

        self.next_button = QPushButton("▶")
        self.next_button.clicked.connect(lambda: self.step_ply(1))
        controls.addWidget(self.next_button)

        self.save_pgn_button = QPushButton("Save PGN…")
        self.save_pgn_button.clicked.connect(self.save_pgn)
        controls.addWidget(self.save_pgn_button)

        controls.addStretch()
        layout.addLayout(controls)

        # The game read from photos, if any, and the process that reads one.
        self.photo_game = None
        self.photo_importer = PhotoImporter(self)
        self.photo_importer.progress.connect(self.on_photo_progress)
        self.photo_importer.finished.connect(self.on_photo_game)
        self.photo_importer.failed.connect(self.on_photo_failed)
        self.update_photo_controls()
        
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

    # ---- photo game: read a folder of photos, then step through the moves ----

    def update_photo_controls(self) -> None:
        loaded = self.photo_game is not None
        row = self.move_list.currentRow()
        self.open_photos_button.setEnabled(not self.photo_importer.busy)
        self.previous_button.setEnabled(loaded and row > 0)
        self.next_button.setEnabled(loaded and row < self.move_list.count() - 1)
        self.save_pgn_button.setEnabled(loaded)

    def open_photo_game(self) -> None:
        """Ask for a folder of photos (one per move) and start reading it."""
        folder = QFileDialog.getExistingDirectory(self, "Folder with the photos of one game")
        if folder:
            self.start_photo_import(folder)

    def start_photo_import(self, folder: str) -> None:
        self.status_label.setText("Reading photos…")
        self.photo_importer.start(folder)
        self.update_photo_controls()

    def on_photo_progress(self, text: str) -> None:
        self.status_label.setText("Reading photos: " + text)

    def on_photo_failed(self, message: str) -> None:
        self.status_label.setText(message)
        self.update_photo_controls()

    def on_photo_game(self, game) -> None:
        """Fill the move list and show the last position of the game."""
        self.photo_game = game
        self.move_list.clear()
        self.move_list.addItem("Start")
        for ply in game.plies:
            self.move_list.addItem(ply.label)
        # Selecting a row displays it (currentRowChanged -> show_ply).
        self.move_list.setCurrentRow(len(game.plies))
        self.update_photo_controls()

    def show_ply(self, index: int) -> None:
        """Display the position after `index` moves of the photo game."""
        if self.photo_game is None or index < 0:
            return
        self.position = self.photo_game.position_at(index)
        self.board.set_position(self.position)
        total = len(self.photo_game.plies)
        text = f"Photo game, move {index} of {total} — {self.position.turn_name} to move."
        if index == total and self.photo_game.status != "ongoing":
            text += f" Game over: {self.photo_game.status}."
        if index > 0 and self.photo_game.plies[index - 1].recovered:
            text += " This photo was unclear; the move was worked out from the next one."
        self.status_label.setText(text)
        self.update_photo_controls()

    def step_ply(self, delta: int) -> None:
        row = self.move_list.currentRow() + delta
        if 0 <= row < self.move_list.count():
            self.move_list.setCurrentRow(row)

    def save_pgn(self) -> None:
        if self.photo_game is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save PGN", "game.pgn", "PGN files (*.pgn)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as file:
                file.write(self.photo_game.pgn)
        except OSError as error:
            self.status_label.setText(f"Could not save: {error}")
            return
        self.status_label.setText(f"Saved {path}")
