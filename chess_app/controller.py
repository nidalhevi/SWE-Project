"""Coordinate board interaction with the stage-3 asynchronous referee.

The C referee owns legality. This module only chooses among returned moves.
"""
from __future__ import annotations

from collections import deque
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal
from models import Move, PositionSnapshot, STARTING_FEN
from game_tree import GameTree
from pgn_service import PgnError, export_study, parse_pgn_text, validate_game
from study import Study


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
    import_failed = Signal(str)
    import_succeeded = Signal()
    study_changed = Signal()
    study_export_ready = Signal(str)
    study_export_failed = Signal(str)

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
        self.study = None
        self._chapter_target = None  # (candidate Study, index); commit after validation/replay
        self._replay_tree = None
        self._replay_purpose = None
        self._export_flow = None
        self._export_trees = None
        self._export_problem = None
        self._export_notification = None
        self._replay_target = None
        self._replay_path = deque()
        self._promotion_moves = ()
        self._pending = None
        self._initial = PositionSnapshot(STARTING_FEN)
        self._notice = ''
        self._import_flow = None
        self._import_source = 'PGN'
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

    @property
    def can_previous_chapter(self):
        return self.can_load and self.study is not None and self.study.active_index > 0

    @property
    def can_next_chapter(self):
        return (self.can_load and self.study is not None
                and self.study.active_index + 1 < len(self.study.chapters))

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
            if self._export_flow is not None:
                self._abort_export(str(error))
            elif self._import_flow is not None or self._chapter_target is not None:
                self._abort_import(str(error))
            else:
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

        if isinstance(context, tuple) and context[0] == 'pgn_import':
            self._advance_import(result)
            return
        if isinstance(context, tuple) and context[0] == 'study_export':
            self._advance_export(result)
            return

        # Navigation is a transaction: don't publish intermediate replay boards.
        if context == 'replay_root':
            if result.fen != self._replay_tree.root.position.fen:
                self._on_fatal('Referee returned a different starting FEN during replay')
                return
            self._replay_next()
        elif isinstance(context, tuple) and context[0] == 'replay_move':
            node = self._replay_tree.node(context[1])
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
            self.status_changed.emit(f'Playing {result}…')
            self._send('play_move', lambda: self.referee.play_move(annotated_move), annotated_move)
        elif action == 'play_move':
            try:
                mainline = self.tree.mainline()
                leaf = mainline[-1] if mainline else self.tree.root
                if self.tree.current.node_id == leaf.node_id:
                    # Extending a finished recorded main line makes its published
                    # result unknown again. Adding a side variation does not.
                    self.tree.headers['Result'] = '*'
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
            notification, self._export_notification = self._export_notification, None
            if notification is not None:
                kind, value = notification
                if kind == 'ready':
                    self.study_export_ready.emit(value)
                else:
                    self.study_export_failed.emit(value)

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
        self.status_changed.emit('Playing…')  # the SAN is not known until the referee answers
        # SAN must be requested BEFORE the move changes the referee's position.
        self._send('san', lambda: self.referee.san(move), move)

    def _publish_current(self):
        # Startup, New game and accepted FEN loads become one-chapter documents.
        # Moves/navigation keep the same Chapter and GameTree objects.
        if self.study is None or self.study.active.tree is not self.tree:
            self.study = Study.from_tree(self.tree)
            self.study_changed.emit()
        self.position = self.tree.current.position
        self.last_move = self.tree.current.move
        self.clear_selection()
        self.position_changed.emit(self.position)
        self.last_move_changed.emit(self.last_move)
        self.tree_changed.emit()

    def go_to(self, node_id, *, force=False):
        """Restore a node by replaying its entire path from the starting FEN.

        FEN alone cannot restore repetition history. Replay also leaves the
        referee's own undo stack and draw detection consistent with the tree.
        """
        if self.tree is None or (not self.can_load and not (force and self.phase == 'importing')):
            return
        if node_id == self.tree.current.node_id and not force:
            return
        self._begin_replay(self.tree, node_id)

    def _begin_replay(self, tree, node_id, *, purpose=None):
        path = tree.path_to(node_id)
        self._replay_tree = tree
        self._replay_purpose = purpose
        self._replay_target = node_id
        self._replay_path = deque(path)
        self.clear_selection()
        self.legal_moves = ()
        self._set_phase('replaying')
        self.status_changed.emit('Restoring selected position…')
        self._send('load_position',
                   lambda: self.referee.load_position(tree.root.position),
                   'replay_root')

    def _replay_next(self):
        if self._replay_path:
            node = self._replay_path.popleft()
            self._send('play_move', lambda: self.referee.play_move(node.move),
                       ('replay_move', node.node_id))
        else:
            tree = self._replay_tree
            purpose = self._replay_purpose
            tree.select(self._replay_target)
            self._replay_target = None
            self._replay_tree = None
            self._replay_purpose = None
            if purpose == 'chapter':
                self._commit_chapter(tree)
            else:
                self.tree = tree
            if purpose == 'export':
                self._finish_export()
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

    def import_image_position(self, position):
        """Validate a reviewed image draft as a new root using the import transaction.

        Reuse rollback/replay so a rejection also preserves repetition history.
        The caller confirms replacing the old game before invoking this method.
        """
        if not self.can_load:
            return False
        if not isinstance(position, PositionSnapshot):
            raise ValueError('Expected a reviewed PositionSnapshot')
        text = ('[Event "Image position"]\n[SetUp "1"]\n'
                f'[FEN "{position.fen}"]\n[Result "*"]\n\n*')
        self.import_game(parse_pgn_text(text)[0], source='image')
        return True

    def import_game(self, parsed_game, *, source='PGN'):
        """Compatibility entry point: replace the document with one chapter."""
        return self.open_study((parsed_game,), source=source)

    def open_study(self, parsed_games, *, source_path=None, source='PGN'):
        """Retain every PGN game; validate the first before replacing the document."""
        if not self.can_load:
            return False
        candidate = Study.from_games(parsed_games, source_path=source_path)
        self._chapter_target = (candidate, 0)
        self._start_chapter_import(candidate.chapters[0].parsed, source)
        return True

    def select_chapter(self, chapter_id):
        if not self.can_load or self.study is None:
            return False
        try:
            index = self.study.index_of(chapter_id)
        except KeyError:
            return False
        if index == self.study.active_index:
            return True
        chapter = self.study.chapters[index]
        self._chapter_target = (self.study, index)
        if chapter.tree is None:
            self._start_chapter_import(chapter.parsed, 'chapter')
        else:
            self._begin_replay(chapter.tree, chapter.tree.current.node_id, purpose='chapter')
        return True

    def previous_chapter(self):
        if self.can_previous_chapter:
            self.select_chapter(self.study.chapters[self.study.active_index - 1].chapter_id)

    def next_chapter(self):
        if self.can_next_chapter:
            self.select_chapter(self.study.chapters[self.study.active_index + 1].chapter_id)

    def _start_chapter_import(self, parsed_game, source):
        self._import_source = source
        self.clear_selection()
        self._set_phase('importing')
        self._import_flow = validate_game(parsed_game)
        self._advance_import()

    def _commit_chapter(self, tree):
        study, index = self._chapter_target
        chapter = study.chapters[index]
        chapter.tree, chapter.error = tree, None
        study.active_index = index
        self.study, self.tree = study, tree
        self._chapter_target = None
        self.study_changed.emit()

    def _advance_import(self, result=None):
        try:
            request = self._import_flow.send(result)
        except StopIteration as finished:
            self._import_flow = None
            self._commit_chapter(finished.value)
            self._notice = ('Imported image position' if self._import_source == 'image'
                            else f'Imported {len(self.tree) - 1} moves and variations')
            self._publish_current()
            self.import_succeeded.emit()
            self._refresh()
            return
        except (PgnError, ValueError, KeyError) as error:
            self._abort_import(str(error))
            return
        self.status_changed.emit(request.description)
        if request.action in ('load_position', 'play_move', 'san'):
            submit = lambda: getattr(self.referee, request.action)(request.payload)
        else:
            submit = getattr(self.referee, request.action)
        self._send(request.action, submit, ('pgn_import', request.description))

    def _abort_import(self, message):
        if self._import_flow is not None:
            self._import_flow.close()
            self._import_flow = None
        if self._chapter_target is not None:
            study, index = self._chapter_target
            study.chapters[index].error = message
        self._chapter_target = None
        self._replay_target = self._replay_tree = self._replay_purpose = None
        self._replay_path.clear()
        self._set_phase('importing')
        self.study_changed.emit()
        label = 'Image' if self._import_source == 'image' else 'PGN'
        self._notice = f'{label} import failed; previous game restored'
        self.import_failed.emit(message)
        # A transport failure emits failed followed by fatal_error. Defer
        # restoration until that fatal signal has had a chance to stop it.
        QTimer.singleShot(0, self._restore_after_import_failure)

    def _restore_after_import_failure(self):
        if self.phase == 'importing':
            self.go_to(self.tree.current.node_id, force=True)

    def export_all_chapters(self):
        """Validate unopened games, restore active history, then emit complete PGN."""
        if not self.can_load or self.study is None:
            return False
        if all(chapter.tree is not None for chapter in self.study.chapters):
            try:
                text = export_study(chapter.tree for chapter in self.study.chapters)
            except (PgnError, ValueError, KeyError) as error:
                self.study_export_failed.emit(str(error))
            else:
                self.study_export_ready.emit(text)
            return True
        self._export_problem = None
        self.clear_selection()
        self._set_phase('exporting')
        self._export_flow = self._validate_unopened_chapters()
        self._advance_export()
        return True

    def _validate_unopened_chapters(self):
        trees = []
        for index, chapter in enumerate(self.study.chapters):
            if chapter.tree is not None:
                trees.append(chapter.tree)
                continue
            flow = validate_game(chapter.parsed)
            response = None
            try:
                while True:
                    try:
                        request = flow.send(response)
                    except StopIteration as complete:
                        trees.append(complete.value)
                        break
                    response = yield replace(request, description=
                        f'Chapter {index + 1} ({chapter.title}): {request.description}')
            except (PgnError, ValueError, KeyError) as error:
                raise PgnError(f'Chapter {index + 1} ({chapter.title}): {error}') from error
            finally:
                flow.close()
        return trees

    def _advance_export(self, result=None):
        try:
            request = self._export_flow.send(result)
        except StopIteration as complete:
            self._export_flow = None
            self._export_trees = complete.value
            self._begin_replay(self.tree, self.tree.current.node_id, purpose='export')
            return
        except (PgnError, ValueError, KeyError) as error:
            self._abort_export(str(error))
            return
        self.status_changed.emit(request.description)
        if request.action in ('load_position', 'play_move', 'san'):
            submit = lambda: getattr(self.referee, request.action)(request.payload)
        else:
            submit = getattr(self.referee, request.action)
        self._send(request.action, submit, ('study_export', request.description))

    def _abort_export(self, message):
        if self._export_flow is not None:
            self._export_flow.close()
            self._export_flow = None
        self._export_trees = None
        self._export_problem = message
        self._set_phase('exporting')
        # A following fatal_error may prevent restoration; never retry a dead process.
        QTimer.singleShot(0, self._restore_after_export)

    def _restore_after_export(self):
        if self.phase == 'exporting':
            self._begin_replay(self.tree, self.tree.current.node_id, purpose='export')

    def _finish_export(self):
        problem = self._export_problem
        try:
            if problem is None:
                text = export_study(self._export_trees)
                for chapter, tree in zip(self.study.chapters, self._export_trees):
                    chapter.tree, chapter.error = tree, None
                self._export_notification = ('ready', text)
                self.study_changed.emit()
            else:
                self._export_notification = ('failed', problem)
        except (PgnError, ValueError, KeyError) as error:
            self._export_notification = ('failed', str(error))
        finally:
            self._export_trees = None
            self._export_problem = None

    def _on_failed(self, request_id, action, message):
        if self.phase in ('closing', 'closed', 'failed'):
            return
        if self._pending is None or self._pending[:2] != (request_id, action):
            return
        context = self._pending[2]
        self._pending = None
        self.clear_selection()
        if isinstance(context, tuple) and context[0] == 'pgn_import':
            self._abort_import(context[1] + ': ' + message)
            return
        if isinstance(context, tuple) and context[0] == 'study_export':
            self._abort_export(context[1] + ': ' + message)
            return
        if self._chapter_target is not None:
            self._abort_import('Could not activate chapter: ' + message)
            return
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
        exporting = (self._export_flow is not None or self._export_trees is not None
                     or self._export_problem is not None or self._export_notification is not None)
        self._cancel_study_work()
        if self._import_flow is not None:
            self._import_flow.close()
            self._import_flow = None
        self._replay_target = None
        self._replay_path.clear()
        self.legal_moves = ()
        self._promotion_moves = ()
        self.clear_selection()
        self._set_phase('failed')
        self.status_changed.emit('Referee error — close and restart the application')
        self.problem.emit(message)
        if exporting:
            self.study_export_failed.emit(message)

    def close(self):
        if self.phase in ('closing', 'closed'):
            return
        self._pending = None
        self._cancel_study_work()
        if self._import_flow is not None:
            self._import_flow.close()
            self._import_flow = None
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
        self._cancel_study_work()
        self._set_phase('closed')
        self.closed.emit()

    def _cancel_study_work(self):
        if self._export_flow is not None:
            self._export_flow.close()
        self._export_flow = self._export_trees = self._export_notification = None
        self._export_problem = None
        self._chapter_target = self._replay_tree = self._replay_purpose = None
