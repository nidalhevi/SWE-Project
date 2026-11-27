"""Piece-placement helpers; these functions do not infer FEN metadata or legality."""
from .board_locator import RecognitionError


def parse_placement(fen):
    rows = fen.strip().split()[0].split('/') if fen.strip() else []
    if len(rows) != 8:
        raise RecognitionError('Expected an eight-rank FEN placement')
    pieces = {}
    for rank, row in zip(range(8, 0, -1), rows):
        file = 0
        for code in row:
            if code in '12345678':
                for _ in range(int(code)):
                    if file >= 8:
                        raise RecognitionError('FEN rank contains too many squares')
                    pieces['abcdefgh'[file] + str(rank)] = None
                    file += 1
            elif code in 'PNBRQKpnbrqk' and file < 8:
                pieces['abcdefgh'[file] + str(rank)] = code
                file += 1
            else:
                raise RecognitionError('Invalid FEN placement')
        if file != 8:
            raise RecognitionError('Each FEN rank must contain eight squares')
    return pieces


def placement_of(pieces):
    if any(pieces.get(f + str(r), '?') == '?' for r in range(1, 9) for f in 'abcdefgh'):
        return None  # Unknown is not empty; never manufacture a complete placement.
    rows = []
    for rank in range(8, 0, -1):
        row, count = '', 0
        for file in 'abcdefgh':
            code = pieces[file + str(rank)]
            if code is None:
                count += 1
            else:
                row += (str(count) if count else '') + code
                count = 0
        rows.append(row + (str(count) if count else ''))
    return '/'.join(rows)
