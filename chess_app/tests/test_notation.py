"""Standard notation for engine lines: format_line, NotationService with the real C referee, and the GUI fallback."""
import sys
import unittest

import tests_stage4.test_gui as stage4
from models import Move, STARTING_FEN
from notation import MAX_PLIES, NotationService, format_line
from tests_stage7.test_engine_qt import FAKE

ITALIAN = 'r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4'   # after 1.e4 e5 2.Nf3 Nc6 3.Bc4


def moves(text):
    return tuple(Move.from_uci(u) for u in text.split())


class FormatLineTests(unittest.TestCase):
    def test_white_to_move_numbers_every_white_move(self):
        self.assertEqual(format_line(STARTING_FEN, ['e4', 'e5', 'Nf3']), '1. e4 e5 2. Nf3')

    def test_black_to_move_starts_with_ellipsis(self):
        fen = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
        self.assertEqual(format_line(fen, ['e5', 'Nf3', 'Nc6']), '1... e5 2. Nf3 Nc6')

    def test_move_number_comes_from_the_fen(self):
        self.assertEqual(format_line(ITALIAN, ['O-O']), '4. O-O')

    def test_moves_without_san_stay_in_uci(self):
        self.assertEqual(format_line(STARTING_FEN, ['e4'], ('e2e4', 'e7e5')), '1. e4 e7e5')


class NotationServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = NotationService()
        self.lines, self.lost, self.closed = [], [], False
        self.service.line_ready.connect(self.lines.append)
        self.service.unavailable.connect(lambda: self.lost.append(True))
        self.service.closed.connect(lambda: setattr(self, 'closed', True))

    def tearDown(self):
        self.service.close()
        stage4.wait_until(lambda: self.closed)
        self.service.deleteLater()

    def boot(self):
        program, arguments = stage4.command()
        self.service.start(program, arguments)

    def convert(self, fen, text):
        self.service.request(fen, moves(text))
        stage4.wait_until(lambda: any(l.ucis == tuple(text.split()) for l in self.lines))
        return [l for l in self.lines if l.ucis == tuple(text.split())][-1]

    def test_castling_disambiguation_capture_check_and_mate(self):
        self.boot()
        line = self.convert(ITALIAN, 'e1g1 g8f6 f3g5 d7d5 e4d5 f6d5 g5f7 e8f7 d1f3 f7e6 b1c3')
        self.assertEqual(line.sans, ('O-O', 'Nf6', 'Ng5', 'd5', 'exd5', 'Nxd5', 'Nxf7', 'Kxf7', 'Qf3+', 'Ke6', 'Nc3'))
        mate = self.convert('6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1', 'a1a8')
        self.assertEqual(mate.sans, ('Ra8#',))
        two_knights = self.convert('4k3/8/8/8/8/8/8/1N1NK3 w - - 0 1', 'b1c3')
        self.assertEqual(two_knights.sans, ('Nbc3',))
        promotion = self.convert('8/P6k/8/8/8/8/8/K7 w - - 0 1', 'a7a8q')
        self.assertEqual(promotion.sans, ('a8=Q',))

    def test_requests_before_ready_are_kept_and_the_newest_wins(self):
        self.service.request(STARTING_FEN, moves('e2e4'))     # not started yet: ignored silently
        self.boot()
        self.service.request(STARTING_FEN, moves('d2d4'))
        self.service.request(STARTING_FEN, moves('g1f3'))     # replaces d2d4 before it ran
        stage4.wait_until(lambda: any(l.ucis == ('g1f3',) for l in self.lines))
        self.assertEqual([l.ucis for l in self.lines], [('g1f3',)])

    def test_cached_line_answers_at_once(self):
        self.boot()
        self.convert(STARTING_FEN, 'e2e4 e7e5')
        count = len(self.lines)
        self.service.request(STARTING_FEN, moves('e2e4 e7e5'))
        self.assertEqual(len(self.lines), count + 1)          # synchronous, no referee round trip

    def test_illegal_tail_keeps_the_legal_prefix(self):
        self.boot()
        line = self.convert(STARTING_FEN, 'e2e4 e2e4 g1f3')
        self.assertEqual(line.sans, ('e4',))
        self.assertEqual(format_line(STARTING_FEN, line.sans, line.ucis), '1. e4 e2e4 2. g1f3')
        self.assertEqual(self.convert(STARTING_FEN, 'd2d4').sans, ('d4',))   # still usable afterwards

    def test_long_lines_are_cut(self):
        self.boot()
        text = ' '.join(['g1f3 g8f6 f3g1 f6g8'] * 8)
        self.service.request(STARTING_FEN, moves(text))
        stage4.wait_until(lambda: self.lines)
        self.assertEqual(len(self.lines[-1].ucis), MAX_PLIES)

    def test_missing_binary_reports_unavailable(self):
        self.service.start('/this-referee-does-not-exist')
        stage4.wait_until(lambda: self.lost and self.closed)
        self.assertFalse(self.service.available)


class AnalysisNotationGuiTests(unittest.TestCase):
    setUp = stage4.LegalMoveGuiTests.setUp
    tearDown = stage4.LegalMoveGuiTests.tearDown
    ready = stage4.LegalMoveGuiTests.ready

    def test_best_move_and_line_in_standard_notation(self):
        self.window._start_engine(sys.executable, [FAKE])
        stage4.wait_until(lambda: self.window.pv_view.toPlainText() == '1. e4 e5')
        self.assertEqual(self.window.best_move_label.text(), 'Best move: e4')

    def test_falls_back_to_coordinates_if_the_notation_referee_dies(self):
        self.window._start_engine(sys.executable, [FAKE])
        stage4.wait_until(lambda: self.window.pv_view.toPlainText() == '1. e4 e5')
        self.window.notation._referee._process.kill()
        stage4.wait_until(lambda: self.window.pv_view.toPlainText() == 'e2e4 e7e5')
        self.assertEqual(self.window.best_move_label.text(), 'Best move: e2 → e4')
        self.assertTrue(self.controller.can_move)            # the game's own referee is untouched


if __name__ == '__main__':
    unittest.main()
