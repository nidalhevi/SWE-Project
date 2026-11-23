"""Coordinate board interaction with the stage-3 asynchronous referee.

The C referee owns legality. This module only chooses among returned moves.
"""
from __future__ import annotations

from collections import deque
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal
from models import Move, PositionSnapshot, STARTING_FEN
from game_tree import GameTree


class ChessController(QObject):
    position_changed = Signal(object)       # PositionSnapshot
    selection_changed = Signal(object, object)  # square | None, tuple of targets
    last_move_changed = Signal(object)      # Move | None
    status_changed = Signal(str)
    controls_changed = Signal()
    promotion_requested = Signal(object)    # tuple of legal Move candidates
    problem = Signal(str)
    closed = Signal()
    tree_changed = Signal()

    def __init__(self, referee, parent=None):
        super().__init__(parent)
        self.referee = referee
        self.position = None
        self.phase = 'starting'
        self.game_status = 'ongoing'
        self.selected_square = None
        self.legal_moves = ()
        self.last_move = None
        self.tree = None
        self._replay_target = None
        self._replay_path = deque()
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
    def can_previous(self):
        return self.can_load and self.tree is not None and self.tree.current.parent_id is not None

    @property
    def can_next(self):
        return self.can_load and self.tree is not None and self.tree.next_id() is not None

    @property
    def can_undo(self):
        # Compatibility with stage 4: Undo now navigates back, preserving moves.
        return self.can_previous

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
        """Start a new tree from a reviewed FEN; caller confirms discarding old lines."""
        if self.can_load:
            self._load(position)

    def new_game(self):
        self.load_position(PositionSnapshot(STARTING_FEN))

    def _load(self, position):
        self.clear_selection()
        self._set_phase('syncing')
        self.status_changed.emit('Loading position…')
        self._send('load_position', lambda: self.referee.load_position(position), 'new_tree')

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

        # Navigation is a transaction: don't publish intermediate replay boards.
        if context == 'replay_root':
            if result.fen != self.tree.root.position.fen:
                self._on_fatal('Referee returned a different starting FEN during replay')
                return
            self._replay_next()
        elif isinstance(context, tuple) and context[0] == 'replay_move':
            node = self.tree.node(context[1])
            if result.fen != node.position.fen:
                self._on_fatal('Referee replay disagreed with a stored position')
                return
            self._replay_next()
        elif action == 'load_position':
            self.tree = GameTree(result)
            self._publish_current()
            self._refresh()
        elif action == 'san':
            annotated_move = replace(context, san=result)
            self._send('play_move', lambda: self.referee.play_move(annotated_move), annotated_move)
        elif action == 'play_move':
            try:
                node = self.tree.add_child(self.tree.current.node_id, context, result)
                self.tree.select(node.node_id)
            except (KeyError, ValueError) as error:
                self._on_fatal(str(error))
                return
            self._publish_current()
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
        existing = self.tree.child_for_move(self.tree.current.node_id, move.uci)
        if existing is not None:
            self.go_to(existing.node_id)
            return
        self.clear_selection()
        self._set_phase('moving')
        self.status_changed.emit(f'Playing {move.uci}…')
        # SAN must be requested BEFORE the move changes the referee's position.
        self._send('san', lambda: self.referee.san(move), move)

    def _publish_current(self):
        self.position = self.tree.current.position
        self.last_move = self.tree.current.move
        self.clear_selection()
        self.position_changed.emit(self.position)
        self.last_move_changed.emit(self.last_move)
        self.tree_changed.emit()

    def go_to(self, node_id):
        """Restore a node by replaying its entire path from the starting FEN.

        FEN alone cannot restore repetition history. Replay also leaves the
        referee's own undo stack and draw detection consistent with the tree.
        """
        if not self.can_load or self.tree is None:
            return
        if node_id == self.tree.current.node_id:
            return
        path = self.tree.path_to(node_id)
        self._replay_target = node_id
        self._replay_path = deque(path)
        self.clear_selection()
        self.legal_moves = ()
        self._set_phase('replaying')
        self.status_changed.emit('Restoring selected position…')
        self._send('load_position',
                   lambda: self.referee.load_position(self.tree.root.position),
                   'replay_root')

    def _replay_next(self):
        if self._replay_path:
            node = self._replay_path.popleft()
            self._send('play_move', lambda: self.referee.play_move(node.move),
                       ('replay_move', node.node_id))
        else:
            self.tree.select(self._replay_target)
            self._replay_target = None
            self._publish_current()
            self._refresh()

    def previous(self):
        if self.can_previous:
            self.go_to(self.tree.current.parent_id)

    def next(self):
        if self.can_next:
            self.go_to(self.tree.next_id())

    def first(self):
        if self.can_previous:
            self.go_to(self.tree.root.node_id)

    def last(self):
        if self.can_next:
            self.go_to(self.tree.last_id())

    def undo(self):
        """Move to the parent without deleting the continuation."""
        self.previous()

    def _on_failed(self, request_id, action, message):
        if self.phase in ('closing', 'closed', 'failed'):
            return
        if self._pending is None or self._pending[:2] != (request_id, action):
            return
        self._pending = None
        self.clear_selection()
        if self._replay_target is not None:
            # The referee may be partway through a restored line; never enable
            # input against the old displayed position after a replay failure.
            self._on_fatal('Could not restore the selected line: ' + message)
            return
        # Rejected commands leave the accepted referee position unchanged.
        # Refresh before accepting another click. Transport failures will
        # also emit fatal_error; the GUI never blindly retries a move.
        self._notice = message
        if action in ('load_position', 'play_move', 'san') and self.position is not None:
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
        self._replay_target = None
        self._replay_path.clear()
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
        self._replay_target = None
        self._replay_path.clear()
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
