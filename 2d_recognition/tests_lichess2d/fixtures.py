"""Generated fixtures, NOT an independent browser-screenshot benchmark.

Rendering happens at the test's requested cell size before the recognizer
resizes its inputs. Templates and fixtures necessarily share Cburnett artwork.
"""
from io import BytesIO
from PIL import Image, ImageDraw
from lichess_2d.board_locator import square_name
from lichess_2d.notation import parse_placement
from lichess_2d.recognizer import ASSET_DIR

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR'
MIDDLE = 'r2q1rk1/ppp2ppp/2nbpn2/3p4/3P1B2/2N1PN2/PPP2PPP/R2QKB1R'
END = '6k1/1p3p2/7p/p3r3/P2R4/7P/2N2PP1/2R4K'
PROMOTIONS = 'Q6k/2q5/3N4/4n3/8/8/8/K7'


def render(placement=START, *, cell=72, white_bottom=True, highlights=(), coordinates=False, jpeg=False):
    pieces = parse_placement(placement)
    board = Image.new('RGBA', (cell * 8, cell * 8))
    for row in range(8):
        for column in range(8):
            square = square_name(row, column, white_bottom)
            color = '#f0d9b5' if (row + column) % 2 == 0 else '#b58863'
            if square in highlights:
                color = '#cdd26a' if (row + column) % 2 == 0 else '#aaa23a'
            tile = Image.new('RGBA', (cell, cell), color)
            code = pieces[square]
            if code:
                path = ASSET_DIR / (('w' if code.isupper() else 'b') + code.upper() + '.png')
                with Image.open(path) as piece:
                    tile.alpha_composite(piece.convert('RGBA').resize((cell, cell), Image.Resampling.LANCZOS))
            board.alpha_composite(tile, (column * cell, row * cell))
            if coordinates:
                draw = ImageDraw.Draw(board)
                if column == 0:
                    draw.text((2, row * cell + 2), square[1], fill='#503020')
                if row == 7:
                    draw.text(((column + 1) * cell - 8, (row + 1) * cell - 11), square[0], fill='#503020')
    board = board.convert('RGB')
    if jpeg:
        stream = BytesIO()
        board.save(stream, format='JPEG', quality=85)
        stream.seek(0)
        with Image.open(stream) as decoded:
            return decoded.convert('RGB')
    return board
