"""Terminal integration check. Run this file, not the Python >>> prompt."""
import argparse
import sys

from PySide6.QtCore import QCoreApplication, QTimer
from models import Move, PositionSnapshot, STARTING_FEN
from referee_client import RefereeClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bin', required=True, help='Native or WSL referee path')
    parser.add_argument('--wsl', action='store_true', help='Launch through wsl.exe')
    parser.add_argument('--distro', help='Optional WSL distribution name')
    args = parser.parse_args()
    app = QCoreApplication(sys.argv)
    client = RefereeClient(timeout_ms=10000)
    exit_code = 0
    expected = {}
    start = PositionSnapshot(STARTING_FEN)
    stalemate = PositionSnapshot('7k/5K2/6Q1/8/8/8/8/8 b - - 0 1')

    def same_start(result):
        return result.fen == STARTING_FEN

    def after_e4(result):
        pieces = result.pieces
        return pieces.get('e4') == 'P' and 'e2' not in pieces and result.turn == 'b'

    # Queue everything at once to verify ordering and compound move+FEN requests.
    def begin():
        checks = [
            (lambda: client.load_position(start), same_start, False, 'load starting FEN'),
            (client.legal_moves,
             lambda r: len(r) == 20 and any(m.uci == 'e2e4' for m in r),
             False, '20 starting legal moves'),
            (lambda: client.san(Move.from_uci('e2e4')),
             lambda r: r == 'e4', False, 'SAN without changing position'),
            (lambda: client.play_move(Move.from_uci('e2e5')),
             lambda r: 'illegal move' in r, True, 'reject illegal move'),
            (client.get_position, same_start, False, 'position unchanged after rejection'),
            (lambda: client.play_move(Move.from_uci('e2e4')),
             after_e4, False, 'play e2e4 and receive new FEN'),
            (client.undo, same_start, False, 'undo restores starting FEN'),
            (lambda: client.load_position(stalemate),
             lambda r: r.fen == stalemate.fen, False, 'load custom position'),
            (client.legal_moves, lambda r: r == (), False, 'empty legal-move response'),
            (client.status, lambda r: r == 'stalemate', False, 'stalemate status'),
            (lambda: client.load_position(PositionSnapshot('8/8/8/8/8/8/8/8 w - - 0 1')),
             lambda r: r.startswith('error '), True, 'referee rejects missing kings'),
            (lambda: client.load_position(start), same_start, False, 'recover after rejected FEN'),
        ]
        for submit, check, should_fail, label in checks:
            expected[submit()] = (check, should_fail, label)

    def receive(request_id, action, result, failed=False):
        nonlocal exit_code
        check, should_fail, label = expected.pop(request_id)
        if failed != should_fail or not check(result):
            exit_code = 1
            print(f'FAIL: {label}: {result}', flush=True)
            client.close()
            return
        print(f'PASS: {label}', flush=True)
        if not expected:
            print('All checks passed. Closing referee.', flush=True)
            client.close()

    def fatal(message):
        nonlocal exit_code
        exit_code = 1
        print('ERROR:', message, flush=True)

    client.ready.connect(begin)
    client.completed.connect(receive)
    client.failed.connect(lambda i, a, message: receive(i, a, message, True))
    client.fatal_error.connect(fatal)
    client.diagnostics.connect(lambda text: print(text, file=sys.stderr, end=''))
    client.closed.connect(app.quit)

    def launch():
        if args.wsl:
            prefix = ['--distribution', args.distro] if args.distro else []
            client.start('wsl.exe', prefix + ['--exec', args.bin, 'batch'])
        else:
            client.start(args.bin)

    QTimer.singleShot(0, launch)
    app.exec()
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
