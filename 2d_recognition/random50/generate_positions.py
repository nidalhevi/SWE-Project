"""Create a reproducible position plan using the team's actual C referee.

This generator is optional: a validated 50-position plan is already included.
The sample comes from random legal playouts with a capture bias, not uniformly
from the set of all legal chess positions or from human tournament games.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import subprocess

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'


def pieces_of(fen):
    pieces = {}
    rows = fen.split()[0].split('/')
    if len(rows) != 8:
        raise ValueError('Expected eight FEN ranks')
    for rank, row in zip(range(8, 0, -1), rows):
        column = 0
        for code in row:
            if code in '12345678':
                column += int(code)
            elif code in 'PNBRQKpnbrqk' and column < 8:
                pieces['abcdefgh'[column] + str(rank)] = code
                column += 1
            else:
                raise ValueError('Invalid FEN piece placement')
        if column != 8:
            raise ValueError('Invalid rank width')
    if list(pieces.values()).count('K') != 1 or list(pieces.values()).count('k') != 1:
        raise ValueError('Expected exactly one king of each color')
    return pieces


class Referee:
    def __init__(self, command):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1)

    def ask(self, command):
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()
        response = self.process.stdout.readline()
        if not response or response.startswith('error '):
            raise RuntimeError('Referee rejected/closed: ' + command + ' / ' + response.strip())
        return response.rstrip('\r\n')

    def close(self):
        self.process.communicate('quit\n', timeout=10)


def generate(command, *, seed=20261125):
    rng = random.Random(seed)
    quotas = dict(opening=17, middlegame=17, endgame=16)
    counts, seen, collected = Counter(), set(), []
    referee = Referee(command)
    try:
        for game in range(1, 101):
            referee.ask('position ' + START)
            fen, history, san, last_sample = START, [], [], -20
            for ply in range(1, 241):
                legal = referee.ask('moves').split()
                if not legal:
                    break
                pieces = pieces_of(fen)
                captures = [m for m in legal if m[2:4] in pieces
                            or (pieces[m[:2]].lower() == 'p' and m[0] != m[2])]
                move = rng.choice(captures if captures and rng.random() < .55 else legal)
                move_san = referee.ask('san ' + move)
                referee.ask('move ' + move)
                fen = referee.ask('fen')
                history.append(move)
                san.append(move_san)
                material = len(pieces_of(fen))
                phase = ('opening' if ply <= 26 and material >= 26 else
                         'endgame' if material <= 10 else 'middlegame')
                if (ply < 8 or ply - last_sample < 6 or counts[phase] >= quotas[phase]
                        or fen.split()[0] in seen or move_san.endswith(('+', '#'))):
                    continue
                collected.append(dict(fen=fen, phase=phase, source_game=game, ply=ply,
                                      material=material, uci_history=list(history), san_history=list(san)))
                counts[phase] += 1
                seen.add(fen.split()[0])
                last_sample = ply
                if len(collected) == 50:
                    rng.shuffle(collected)
                    for index, item in enumerate(collected):
                        item.update(id=f'random-{index + 1:03d}', white_bottom=index % 2 == 0,
                                    requested_board_size=(512, 640, 768)[index % 3])
                    return dict(version=1, seed=seed, generator='C referee random legal playouts, capture biased',
                                selection_note='Stratified software-test positions; not a representative sample of human games',
                                positions=collected, phase_counts=dict(counts))
        raise RuntimeError('Could not fill the phase quotas')
    finally:
        referee.close()


def write_pgn(plan, path):
    games = []
    for item in plan['positions']:
        moves = []
        for index, move in enumerate(item['san_history']):
            if index % 2 == 0:
                moves.append(str(index // 2 + 1) + '.')
            moves.append(move)
        games.append(f'[Event "Random recognition fixture"]\n[PositionID "{item["id"]}"]\n'
                     f'[Phase "{item["phase"]}"]\n[Result "*"]\n\n' + ' '.join(moves) + ' *\n')
    Path(path).write_text('\n'.join(games), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin', required=True)
    parser.add_argument('--wsl', action='store_true')
    parser.add_argument('--distro', default='Ubuntu')
    parser.add_argument('--seed', type=int, default=20261125)
    parser.add_argument('--output', default='positions_50.json')
    args = parser.parse_args()
    command = (['wsl.exe', '--distribution', args.distro, '--exec', args.bin, 'batch']
               if args.wsl else [args.bin, 'batch'])
    plan = generate(command, seed=args.seed)
    if not args.wsl:
        plan['referee_binary_sha256'] = hashlib.sha256(Path(args.bin).read_bytes()).hexdigest()
    path = Path(args.output)
    path.write_text(json.dumps(plan, indent=2), encoding='utf-8')
    write_pgn(plan, path.with_suffix('.pgn'))
    print('Saved 50 legal positions:', plan['phase_counts'])


if __name__ == '__main__':
    main()
