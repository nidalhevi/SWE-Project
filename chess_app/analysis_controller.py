"""Coordinate optional Stockfish analysis without changing the chess referee.

The request ID, tree object, selected node and FEN must all match before display.
"""
from PySide6.QtCore import QObject, QTimer, Signal


class AnalysisController(QObject):
    result_changed = Signal(object)  # AnalysisResult, or None to clear stale UI
    message_changed = Signal(str)

    def __init__(self, chess_controller, engine, parent=None, *, movetime_ms=1000):
        super().__init__(parent)
        self.chess = chess_controller
        self.engine = engine
        self.enabled = True
        self.movetime_ms = movetime_ms
        self._ready = False
        self._failed = False
        self._disposed = False
        self._expected_id = None
        self._context = None
        self._last_tree = None
        self._game_key = 0
        self._has_result = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._request_current)
        chess_controller.controls_changed.connect(self._on_position_state)
        engine.ready.connect(self._on_ready)
        engine.result_ready.connect(self._on_result)
        engine.finished.connect(self._on_finished)
        engine.error.connect(self._on_error)

    def _on_ready(self):
        self._ready = True
        self._on_position_state()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._on_position_state()

    def set_movetime(self, milliseconds):
        self.movetime_ms = milliseconds
        self._on_position_state()

    def _on_position_state(self):
        if self._disposed:
            return
        self._debounce.stop()
        self._expected_id = None
        self._context = None
        self._has_result = False
        self.engine.cancel()
        self.result_changed.emit(None)
        if self._failed:
            return
        if not self.enabled:
            self.message_changed.emit('Analysis paused')
        elif not self._ready:
            self.message_changed.emit('Starting analysis engine…')
        elif not self.chess.can_load:
            self.message_changed.emit('Waiting for the selected position…')
        elif self.chess.game_status != 'ongoing':
            self.message_changed.emit('Game finished — ' + self.chess.game_status.replace('-', ' '))
        else:
            self.message_changed.emit('Preparing analysis…')
            self._debounce.start(150)

    def _request_current(self):
        if self._disposed or self._failed or not self._ready or not self.enabled:
            return
        if not self.chess.can_load or self.chess.game_status != 'ongoing':
            return
        tree = self.chess.tree
        node = tree.current
        if tree is not self._last_tree:
            self._last_tree = tree
            self._game_key += 1
        self._context = (tree, node.node_id, node.position.fen)
        moves = tuple(item.move for item in tree.path_to(node.node_id))
        try:
            self._expected_id = self.engine.analyse(
                node.position, tree.root.position, moves,
                movetime_ms=self.movetime_ms, game_key=self._game_key,
            )
        except (RuntimeError, ValueError) as error:
            self._on_error(str(error))
            return
        self.message_changed.emit('Analyzing…')

    def _context_is_current(self):
        if self._context is None or not self.enabled or not self.chess.can_load:
            return False
        tree, node_id, fen = self._context
        return (self.chess.tree is tree and tree.current.node_id == node_id
                and self.chess.position.fen == fen)

    def _on_result(self, result):
        if self._disposed or result.request_id != self._expected_id or not self._context_is_current():
            return
        if result.position.fen != self._context[2]:
            return
        if result.best_move is not None:
            legal = {move.uci for move in self.chess.legal_moves}
            if result.best_move.uci not in legal:
                self.message_changed.emit('Engine suggestion does not match the selected position')
                return
        self._has_result = True
        self.result_changed.emit(result)

    def _on_finished(self, request_id):
        if request_id == self._expected_id and self._context_is_current():
            self.message_changed.emit('Analysis complete' if self._has_result else 'No analysis returned')

    def _on_error(self, message):
        if self._disposed:
            return
        self._failed = True
        self._ready = False
        self._debounce.stop()
        self._expected_id = None
        self._context = None
        self.result_changed.emit(None)
        self.message_changed.emit('Analysis unavailable: ' + message)

    def dispose(self):
        self._disposed = True
        self._debounce.stop()
        self._expected_id = None
        self._context = None
        self.chess.controls_changed.disconnect(self._on_position_state)
        self.engine.cancel()
