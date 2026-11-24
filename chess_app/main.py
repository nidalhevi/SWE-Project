"""Launch the GUI: python main.py [--wsl --distro Ubuntu --bin /path/to/chess]."""
import argparse
import os
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication
from main_window import MainWindow
from models import PositionSnapshot, STARTING_FEN


def launch_command(binary, use_wsl, distro):
    """Keep program/arguments separate; no shell quoting or shell execution."""
    if use_wsl:
        return 'wsl.exe', ['--distribution', distro, '--exec', binary, 'batch']
    return binary, ['batch']


def main():
    parser = argparse.ArgumentParser(description='Chess GUI using the C referee')
    parser.add_argument('--bin', help='Referee executable; Linux path with --wsl')
    parser.add_argument('--wsl', action='store_true', help='Launch referee inside WSL')
    parser.add_argument('--distro', default='Ubuntu', help='WSL distribution (default Ubuntu)')
    parser.add_argument('--fen', default=STARTING_FEN, help='Initial six-field FEN')
    parser.add_argument('--stockfish', help='Optional Stockfish executable (Linux path with --stockfish-wsl)')
    parser.add_argument('--stockfish-wsl', action='store_true', help='Launch Stockfish in WSL')
    parser.add_argument('--stockfish-distro', help='Stockfish distribution; defaults to --distro')
    parser.add_argument('--analysis-ms', type=int, default=1000, help='Analysis time per position, 100..10000 ms')
    parser.add_argument('--image-recognizer', help='Optional Python recognition adapter as module:function')
    parser.add_argument('--vision-path', help='Folder containing the recognition adapter/package (Windows path for Windows Python)')
    args = parser.parse_args()
    if not 100 <= args.analysis_ms <= 10000:
        parser.error('--analysis-ms must be 100..10000')
    if args.stockfish_wsl and not args.stockfish:
        parser.error('--stockfish-wsl requires --stockfish')
    try:
        initial = PositionSnapshot(args.fen)
    except ValueError as error:
        parser.error(str(error))

    # On Windows, no arguments selects the WSL build in this repository.
    # Supply --bin C:\path\chess.exe to choose a native Windows build instead.
    use_wsl = args.wsl or (os.name == 'nt' and args.bin is None)
    binary = args.bin
    if binary is None:
        binary = (Path(__file__).resolve().parent.parent / 'build/release/chess').as_posix()
        if use_wsl:
            if len(binary) < 3 or binary[1:3] != ':/':
                parser.error('Supply --bin with the referee Linux path for this location')
            binary = '/mnt/' + binary[0].lower() + binary[2:]
    program, arguments = launch_command(binary, use_wsl, args.distro)
    app = QApplication([sys.argv[0]])
    engine_program, engine_arguments = None, None
    if args.stockfish:
        if args.stockfish_wsl:
            engine_program = 'wsl.exe'
            engine_arguments = ['--distribution', args.stockfish_distro or args.distro,
                                '--exec', args.stockfish]
        else:
            engine_program, engine_arguments = args.stockfish, []
    window = MainWindow(program, arguments, initial, engine_program=engine_program,
                        engine_arguments=engine_arguments, analysis_ms=args.analysis_ms,
                        image_recognizer=args.image_recognizer, vision_path=args.vision_path)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
