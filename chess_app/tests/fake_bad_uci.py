"""UCI failure fixture: deliberately invalid bestmove or stop without reply."""
import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=('invalid-bestmove', 'hang-stop'), required=True)
mode = parser.parse_args().mode
for raw in sys.stdin:
    command = raw.strip()
    if command == 'uci':
        print('uciok', flush=True)
    elif command == 'isready':
        print('readyok', flush=True)
    elif command.startswith('go '):
        if mode == 'invalid-bestmove':
            print('bestmove z9z1', flush=True)
        else:
            print('info depth 1 score cp 12 pv e2e4', flush=True)
    elif command == 'quit':
        break
