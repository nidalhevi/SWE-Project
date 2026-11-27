"""Terminal smoke test of an actual Stockfish executable using Qt events."""
import argparse
import sys
from PySide6.QtCore import QCoreApplication, QTimer
from engine_client import EngineClient
from engine_protocol import format_score
from models import Move, PositionSnapshot, STARTING_FEN


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bin', required=True, help='Stockfish executable, not the C referee')
    parser.add_argument('--wsl', action='store_true')
    parser.add_argument('--distro', default='Ubuntu')
    args = parser.parse_args()
    app = QCoreApplication([sys.argv[0]])
    engine = EngineClient()
    start = PositionSnapshot(STARTING_FEN)
    e4 = PositionSnapshot('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1')
    code = 0
    phase = 0
    expected = None
    last = None

    def begin():
        nonlocal expected, phase
        phase = 1
        expected = engine.analyse(start, start, movetime_ms=300, game_key=1)

    def update(result):
        nonlocal last
        if result.request_id == expected:
            last = result

    def error(message):
        nonlocal code
        code = 1
        print('ERROR:', message, flush=True)

    def finished(request_id):
        nonlocal expected, phase, last, code
        if request_id != expected:
            return
        if last is None or last.score_cp is None or last.best_move is None:
            code = 1
            print('FAIL: Stockfish returned no complete evaluation', flush=True)
            engine.close()
            return
        print(f'PASS: request {request_id}, eval {format_score(last)}, depth {last.depth}, '
              f'line {" ".join(move.uci for move in last.principal_variation)}', flush=True)
        if phase == 1:
            phase = 2
            last = None
            expected = engine.analyse(e4, start, (Move.from_uci('e2e4'),), movetime_ms=300, game_key=1)
        else:
            print('Stockfish connection checks passed. Closing engine.', flush=True)
            engine.close()

    engine.ready.connect(begin)
    engine.result_ready.connect(update)
    engine.finished.connect(finished)
    engine.error.connect(error)
    engine.closed.connect(app.quit)
    def launch():
        if args.wsl:
            engine.start('wsl.exe', ['--distribution', args.distro, '--exec', args.bin])
        else:
            engine.start(args.bin)
    QTimer.singleShot(0, launch)
    app.exec()
    return code


if __name__ == '__main__':
    sys.exit(main())
