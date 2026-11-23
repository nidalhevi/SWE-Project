"""Coordinate board interaction with the stage-3 asynchronous referee.

The C referee owns legality. This module only chooses among returned moves.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from models import Move, PositionSnapshot, STARTING_FEN


class ChessController(QObject):
    position_changed = Signal(object)       # PositionSnapshot
    selection_changed = Signal(object, object)  # square | None, tuple of targets
    last_move_changed = Signal(object)      # Move | None
    status_changed = Signal(str)
    controls_changed = Signal()
    promotion_requested = Signal(object)    # tuple of legal Move candidates
    problem = Signal(str)
    closed = Signal()

    def __init__(self, referee, parent=None):
        super().__init__(parent)
        self.referee = referee
        self.position = None
        self.phase = 'starting'
        self.game_status = 'ongoing'
        self.selected_square = None
        self.legal_moves = ()
        self.last_move = None
        self._history = []
        self._promotion_moves = ()
        self._pending = None
        self._initial = PositionSnapshot(STARTING_FEN)
        self._notice = ''
        referee.ready.connect(self._on_ready)
        referee.completed.connect(self._on_completed)
        referee.failed.connect(self._on_failed)
        referee.fatal_error.connect(self._on_fatal)
        referee.closed.connect(self._on_closed)

    @property
    def can_move(self):
        return self.phase == 'ready' and self.game_status == 'ongoing'

    @property
    def can_load(self):
        return self.phase == 'ready'

    @property
    def can_undo(self):
        return self.phase == 'ready' and bool(self._history)

    def start(self, program, arguments=None, initial=None):
        self._initial = initial or PositionSnapshot(STARTING_FEN)
        self.status_changed.emit('Starting referee…')
        self.referee.start(program, arguments)

    def _set_phase(self, phase):
        self.phase = phase
        self.controls_changed.emit()

    def _send(self, action, submit, context=None):
        # Stage 3 defers replies, so this ID is recorded before they arrive.
        try:
            request_id = submit()
        except (RuntimeError, ValueError) as error:
            self._on_fatal(str(error))
            return
        self._pending = (request_id, action, context)

    def _on_ready(self):
        if self.phase != 'starting':
            return
        self._load(self._initial)

    def load_position(self, position):
        """Load a reviewed FEN. Loading clears move/undo history."""
        if self.can_load:
            self._load(position)

    def new_game(self):
        self.load_position(PositionSnapshot(STARTING_FEN))

    def _load(self, position):
        self.clear_selection()
        self._set_phase('syncing')
        self.status_changed.emit('Loading position…')
        self._send('load_position', lambda: self.referee.load_position(position))

    def _refresh(self):
        self.legal_moves = ()
        self._set_phase('syncing')
        self.status_changed.emit('Getting legal moves…')
        self._send('legal_moves', self.referee.legal_moves)

    def _on_completed(self, request_id, action, result):
        if self.phase in ('closing', 'closed', 'failed'):
            return
        if self._pending is None or self._pending[:2] != (request_id, action):
            return
        context = self._pending[2]
        self._pending = None

        if action in ('load_position', 'play_move', 'undo'):
            self.position = result
            if action == 'load_position':
                self._history.clear()
            elif action == 'play_move':
                self._history.append(context)
            else:
                self._history.pop()
            self.last_move = self._history[-1] if self._history else None
            self.clear_selection()
            self.position_changed.emit(result)
            self.last_move_changed.emit(self.last_move)
            self._refresh()
        elif action == 'legal_moves':
            self.legal_moves = result
            self._send('status', self.referee.status)
        elif action == 'status':
            self.game_status = result
            self._set_phase('ready')
            message = self._position_status()
            if self._notice:
                message = self._notice + ' — ' + message
                self._notice = ''
            self.status_changed.emit(message)

    def _position_status(self):
        turn = self.position.turn_name
        if self.game_status == 'ongoing':
            return f'{turn} to move'
        if self.game_status == 'checkmate':
            winner = 'Black' if self.position.turn == 'w' else 'White'
            return f'Checkmate — {winner} wins'
        draws = {
            'stalemate': 'Stalemate — draw',
            'insufficient-material': 'Draw — insufficient material',
            'fifty-moves': 'Draw — fifty-move rule',
            'threefold-repetition': 'Draw — threefold repetition',
        }
        return draws.get(self.game_status, self.game_status)

    def clear_selection(self):
        self.selected_square = None
        self.selection_changed.emit(None, ())
        if self.phase == 'ready' and self.position is not None:
            self.status_changed.emit(self._position_status())

    def on_square_clicked(self, square):
        if not self.can_move:
            return
        if square == self.selected_square:
            self.clear_selection()
            self.status_changed.emit(self._position_status())
            return

        candidates = tuple(
            move for move in self.legal_moves
            if move.from_square == self.selected_square and move.to_square == square
        )
        if candidates:
            if any(move.promotion is not None for move in candidates):
                self._promotion_moves = candidates
                self._set_phase('promotion')
                self.status_changed.emit('Choose a promotion piece')
                self.promotion_requested.emit(candidates)
            else:
                self._play(candidates[0])
            return

        piece = self.position.pieces.get(square)
        friendly = piece is not None and piece.isupper() == (self.position.turn == 'w')
        if friendly:
            self.selected_square = square
            targets = tuple(sorted({
                move.to_square for move in self.legal_moves if move.from_square == square
            }))
            self.selection_changed.emit(square, targets)
            self.status_changed.emit(
                f'{self.position.turn_name} to move — selected {square}'
                + ('' if targets else ' (no legal moves)')
            )
        else:
            self.clear_selection()
            self.status_changed.emit(self._position_status())

    def choose_promotion(self, piece):
        """Choose q/r/b/n; None cancels without changing the position."""
        if self.phase != 'promotion':
            return
        if piece is None:
            self._promotion_moves = ()
            self._set_phase('ready')
            self.clear_selection()
            self.status_changed.emit(self._position_status())
            return
        move = next((m for m in self._promotion_moves if m.promotion == piece), None)
        if move is not None:
            self._promotion_moves = ()
            self._play(move)

    def _play(self, move):
        self.clear_selection()
        self._set_phase('moving')
        self.status_changed.emit(f'Playing {move.uci}…')
        self._send('play_move', lambda: self.referee.play_move(move), move)

    def undo(self):
        if not self.can_undo:
            return
        self.clear_selection()
        self._set_phase('moving')
        self.status_changed.emit('Undoing move…')
        self._send('undo', self.referee.undo)

    def _on_failed(self, request_id, action, message):
        if self.phase in ('closing', 'closed', 'failed'):
            return
        if self._pending is None or self._pending[:2] != (request_id, action):
            return
        self._pending = None
        self.clear_selection()
        # Rejected commands leave the accepted referee position unchanged.
        # Refresh before accepting another click. Transport failures will
        # also emit fatal_error; the GUI never blindly retries a move.
        self._notice = message
        if action in ('load_position', 'play_move', 'undo') and self.position is not None:
            self._set_phase('syncing')
            # Let a following fatal_error signal disable recovery first.
            QTimer.singleShot(0, self._recover_rejection)
        else:
            self._on_fatal(message)

    def _recover_rejection(self):
        if self.phase == 'syncing':
            self._refresh()

    def _on_fatal(self, message):
        if self.phase in ('closing', 'closed', 'failed'):
            return
        self._pending = None
        self.legal_moves = ()
        self._promotion_moves = ()
        self.clear_selection()
        self._set_phase('failed')
        self.status_changed.emit('Referee error — close and restart the application')
        self.problem.emit(message)

    def close(self):
        if self.phase in ('closing', 'closed'):
            return
        self._pending = None
        self._promotion_moves = ()
        self.clear_selection()
        self._set_phase('closing')
        self.status_changed.emit('Closing referee…')
        self.referee.close()

    def _on_closed(self):
        # A fatal process may finish before the user closes the window.
        self._pending = None
        self._set_phase('closed')
        self.closed.emit()
