"""Deterministic UCI test process. It is not a chess analysis engine."""
import argparse
import sys
import threading

parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=('normal', 'exit-on-go'), default='normal')
parser.add_argument('--log')
args = parser.parse_args()
lock = threading.Lock()
stop = threading.Event()
worker = None
position = 'position startpos'


def emit(line):
    with lock:
        # Two writes deliberately exercise output buffering when not coalesced.
        split = len(line) // 2
        sys.stdout.write(line[:split])
        sys.stdout.flush()
        sys.stdout.write(line[split:] + '\n')
        sys.stdout.flush()


def search(command, interrupted):
    words = command.split()
    moves = words[words.index('moves') + 1:] if 'moves' in words else []
    if not moves:
        best, pv = 'e2e4', 'e2e4 e7e5'
    elif moves[-1] == 'e2e4':
        best, pv = 'e7e5', 'e7e5 g1f3'
    else:
        best, pv = 'g1f3', 'g1f3 b8c6'
    emit('info string test engine, not Stockfish')
    emit(f'info depth 1 score cp 15 pv {pv}')
    if interrupted.wait(.06):
        # A cancelled search is allowed to emit a final late update.
        emit(f'info depth 50 score cp 999 pv {pv}')
    else:
        emit(f'info depth 8 score cp 34 pv {pv}')
    emit('bestmove ' + best)


try:
    for raw in sys.stdin:
        command = raw.strip()
        if args.log:
            with open(args.log, 'a', encoding='utf-8') as handle:
                handle.write(command + '\n')
        if command == 'uci':
            emit('id name Testfish')
            emit('option name Threads type spin default 1 min 1 max 8')
            emit('option name Hash type spin default 16 min 1 max 1024')
            emit('option name MultiPV type spin default 1 min 1 max 10')
            emit('uciok')
        elif command == 'isready':
            emit('readyok')
        elif command.startswith('position '):
            position = command
        elif command.startswith('go '):
            if args.mode == 'exit-on-go':
                sys.exit(3)
            stop = threading.Event()
            worker = threading.Thread(target=search, args=(position, stop), daemon=True)
            worker.start()
        elif command == 'stop':
            stop.set()
        elif command == 'quit':
            break
finally:
    stop.set()
    if worker is not None:
        worker.join(timeout=.5)
