"""Fault-injection batch process. Not a chess referee; only used by tests."""
import argparse
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=('malformed', 'hang', 'fragmented'), required=True)
mode = parser.parse_args().mode
START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
for raw in sys.stdin:
    command = raw.strip()
    if command == 'quit':
        break
    if mode == 'hang':
        continue
    if mode == 'malformed':
        print('not-a-valid-protocol-response', flush=True)
    elif command == 'fen':
        sys.stdout.write(START[:25]); sys.stdout.flush()
        time.sleep(.01)
        sys.stdout.write(START[25:] + '\n'); sys.stdout.flush()
    else:
        print('ok', flush=True)
