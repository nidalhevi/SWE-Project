"""Pure UCI checks; no Qt, referee, or installed Stockfish required."""
import unittest
from engine_protocol import LineBuffer, ProtocolError, SearchRequest, UciSession, parse_info, format_score
from models import Move, PositionSnapshot, STARTING_FEN

START = PositionSnapshot(STARTING_FEN)
E4 = PositionSnapshot('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1')


def request(position=START):
    return SearchRequest(1, position, START, (), 100, 0)


class Harness:
    def __init__(self):
        self.commands, self.results, self.completed, self.errors, self.states = [], [], [], [], []
        self.ready = False
        self.session = UciSession(
            send=self.commands.append, result=self.results.append,
            ready=lambda: setattr(self, 'ready', True), finished=self.completed.append,
            error=self.errors.append, state_changed=lambda state, timeout: self.states.append((state, timeout)),
        )

    def boot(self):
        self.session.boot()
        self.session.line('id name Testfish')
        self.session.line('uciok')
        self.session.line('readyok')

    def search(self, position=START, moves=(), game_key=0):
        ident = self.session.analyse(position, START, moves, movetime_ms=100, game_key=game_key)
        if self.session.state == 'newgame_ready':
            self.session.line('readyok')
        return ident


class EngineProtocolTests(unittest.TestCase):
    def test_fragmented_and_multiple_output_lines(self):
        buffer = LineBuffer()
        self.assertEqual(buffer.feed(b'uci'), [])
        self.assertEqual(buffer.feed(b'ok\r\nreadyok\ninfo str'), ['uciok', 'readyok'])
        self.assertEqual(buffer.feed(b'ing hello\n'), ['info string hello'])

    def test_unterminated_output_limit(self):
        with self.assertRaises(ProtocolError):
            LineBuffer().feed(b'x' * (1024 * 1024 + 1))

    def test_white_score(self):
        result = parse_info('info depth 12 score cp 125 pv e2e4 e7e5', request())
        self.assertEqual(result.score_cp, 125)
        self.assertEqual(result.depth, 12)
        self.assertEqual(format_score(result), '+1.25')

    def test_black_score_is_converted_to_white(self):
        result = parse_info('info depth 9 score cp 125 pv e7e5', request(E4))
        self.assertEqual(result.score_cp, -125)
        self.assertEqual(format_score(result), '-1.25')

    def test_mate_signs_and_zero(self):
        white = parse_info('info depth 5 score mate 3 pv e2e4', request())
        black = parse_info('info depth 5 score mate 3 pv e7e5', request(E4))
        zero = parse_info('info depth 0 score mate 0', request())
        self.assertEqual(white.mate_in, 3)
        self.assertEqual(black.mate_in, -3)
        self.assertEqual(format_score(black), 'Black mates in 3')
        self.assertEqual(format_score(zero), 'Checkmate')

    def test_bound_secondary_and_telemetry_lines_ignored(self):
        for line in ('info string score cp 999 depth 99 pv e2e4',
                     'info depth 4 score cp 200 lowerbound pv e2e4',
                     'info depth 4 score cp -200 upperbound pv e2e4',
                     'info depth 4 multipv 2 score cp 10 pv e2e4',
                     'info depth 5 currmove e2e4 currmovenumber 1'):
            with self.subTest(line=line):
                self.assertIsNone(parse_info(line, request()))

    def test_malformed_info_ignored(self):
        for line in ('info depth x score cp 10 pv e2e4', 'info depth -1 score cp 0 pv e2e4',
                     'info depth 1 score cp', 'info depth 1 score cp 3 pv nonsense',
                     'info depth 1 score cp 3'):
            self.assertIsNone(parse_info(line, request()))

    def test_position_command_carries_history_and_custom_root(self):
        req = SearchRequest(1, E4, START, (Move.from_uci('e2e4'),), 100, 0)
        self.assertEqual(req.command, 'position startpos moves e2e4')
        custom = PositionSnapshot('7k/8/8/8/8/8/8/R6K b - - 0 42')
        req = SearchRequest(2, custom, custom, (), 100, 1)
        self.assertEqual(req.command, 'position fen ' + custom.fen)

    def test_handshake_and_newgame_ready_barrier(self):
        h = Harness()
        h.boot()
        self.assertTrue(h.ready)
        self.assertEqual(h.commands[0], 'uci')
        self.assertIn('setoption name Threads value 1', h.commands)
        ident = h.session.analyse(START, START, movetime_ms=100)
        self.assertEqual(h.session.state, 'newgame_ready')
        self.assertFalse(any(c.startswith('go ') for c in h.commands))
        h.session.line('readyok')
        self.assertEqual(h.commands[-2:], ['position startpos', 'go movetime 100'])
        self.assertEqual(ident, 1)

    def test_cancel_drops_late_updates(self):
        h = Harness(); h.boot(); h.search()
        h.session.cancel()
        h.session.line('info depth 40 score cp 999 pv e2e4')
        h.session.line('bestmove e2e4')
        self.assertEqual(h.results, [])
        self.assertEqual(h.completed, [])
        self.assertEqual(h.session.state, 'barrier')
        h.session.line('readyok')
        self.assertEqual(h.session.state, 'idle')

    def test_latest_request_wins_and_waits_for_old_bestmove(self):
        h = Harness(); h.boot(); old = h.search()
        second = h.session.analyse(E4, START, (Move.from_uci('e2e4'),), movetime_ms=100)
        latest = h.session.analyse(START, START, movetime_ms=200)
        self.assertGreater(latest, second)
        self.assertEqual(h.commands.count('stop'), 1)
        h.session.line('info depth 50 score cp 999 pv e2e4')
        h.session.line('bestmove e2e4')
        self.assertEqual(sum(c.startswith('go ') for c in h.commands), 1)
        h.session.line('readyok')
        self.assertEqual(h.commands[-1], 'go movetime 200')
        h.session.line('info depth 8 score cp 25 pv e2e4')
        self.assertEqual(h.results[-1].request_id, latest)
        self.assertNotEqual(h.results[-1].request_id, old)

    def test_same_fen_search_gets_a_new_id(self):
        h = Harness(); h.boot(); first = h.search()
        second = h.session.analyse(START, START, movetime_ms=100)
        self.assertNotEqual(first, second)

    def test_new_game_key_resets_engine(self):
        h = Harness(); h.boot(); h.search(game_key=1)
        h.session.line('bestmove e2e4'); h.session.line('readyok')
        h.search(game_key=2)
        self.assertEqual(h.commands.count('ucinewgame'), 2)

    def test_changed_final_bestmove_does_not_reuse_old_score(self):
        h = Harness(); h.boot(); ident = h.search()
        h.session.line('info depth 5 score cp 30 pv e2e4 e7e5')
        h.session.line('bestmove d2d4')
        result = h.results[-1]
        self.assertIsNone(result.score_cp)
        self.assertEqual([m.uci for m in result.principal_variation], ['d2d4'])
        self.assertEqual(h.completed, [ident])

    def test_no_info_still_reports_final_move_without_inventing_score(self):
        h = Harness(); h.boot(); h.search()
        h.session.line('bestmove e2e4')
        self.assertIsNone(h.results[-1].score_cp)
        self.assertEqual(h.results[-1].best_move.uci, 'e2e4')

    def test_terminal_bestmove_none(self):
        h = Harness(); h.boot(); h.search()
        h.session.line('info depth 0 score mate 0')
        h.session.line('bestmove (none)')
        self.assertEqual(h.results[-1].mate_in, 0)
        self.assertIsNone(h.results[-1].best_move)

    def test_failure_and_close_discard_pending_work(self):
        h = Harness(); h.boot(); h.search()
        h.session.fail('timeout')
        h.session.line('info depth 8 score cp 999 pv e2e4')
        self.assertEqual(h.errors, ['timeout'])
        self.assertFalse(h.results)
        with self.assertRaises(RuntimeError):
            h.session.analyse(START, START)
        h.session.close()
        self.assertEqual(h.session.state, 'closing')

    def test_invalid_bestmove_fails_session(self):
        h = Harness(); h.boot(); h.search()
        h.session.line('bestmove nonsense')
        self.assertEqual(h.session.state, 'failed')

    def test_cancel_during_newgame_handshake(self):
        h = Harness(); h.boot()
        h.session.analyse(START, START)
        h.session.cancel()
        h.session.line('readyok')
        self.assertEqual(h.session.state, 'idle')
        self.assertFalse(any(c.startswith('go ') for c in h.commands))

    def test_unsolicited_readyok_does_not_end_search(self):
        h = Harness(); h.boot(); h.search()
        h.session.line('readyok')
        self.assertEqual(h.session.state, 'search')


if __name__ == '__main__':
    unittest.main()
