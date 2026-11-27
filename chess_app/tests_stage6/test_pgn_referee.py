"""PGN validation/export against the actual C executable; no Qt required."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from models import Move, PositionSnapshot
from pgn_service import (
    PgnError, export_pgn, parse_pgn_text, validate_game, write_pgn_file, read_pgn_file,
)

SAMPLE = '''[Event "Opening study"]
[White "Nidal"]
[Black "Team"]
[Result "*"]

{Root comment} 1. e4 {King pawn} e5 $1
( {Sicilian start} 1... c5 {Sicilian} 2. Nf3 (2. Nc3 $5))
2. Nf3 Nc6 *
'''


def referee_command():
    binary = os.environ.get('CHESS_BIN')
    use_wsl = os.name == 'nt' and not (binary and binary.lower().endswith('.exe'))
    if binary is None:
        binary = (Path(__file__).resolve().parents[2] / 'build/release/chess').as_posix()
        if use_wsl:
            binary = '/mnt/' + binary[0].lower() + binary[2:]
    if use_wsl:
        return ['wsl.exe', '--distribution', os.environ.get('CHESS_DISTRO', 'Ubuntu'),
                '--exec', binary, 'batch']
    return [binary, 'batch']


class RefereeDriver:
    """Blocking transport for tests only. The GUI uses the asynchronous client."""
    def __init__(self):
        self.process = subprocess.Popen(referee_command(), stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True)

    def ask(self, command):
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()
        reply = self.process.stdout.readline()
        if not reply:
            raise PgnError('Referee closed its output during a test')
        reply = reply.rstrip('\r\n')
        if reply.startswith('error '):
            raise PgnError(reply)
        return reply

    def request(self, request):
        action, payload = request.action, request.payload
        if action == 'load_position':
            self.ask('position ' + payload.fen)
        elif action == 'play_move':
            self.ask('move ' + payload.uci)
        elif action == 'undo':
            self.ask('undo')
        elif action == 'legal_moves':
            return tuple(Move.from_uci(m) for m in self.ask('moves').split())
        elif action == 'san':
            return self.ask('san ' + payload.uci)
        return PositionSnapshot(self.ask('fen'))

    def import_text(self, text):
        flow = validate_game(parse_pgn_text(text)[0])
        result = None
        try:
            while True:
                request = flow.send(result)
                result = self.request(request)
        except StopIteration as finished:
            return finished.value
        finally:
            flow.close()

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('quit\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        try:
            self.process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate()


def signature(tree):
    return [(tuple(n.move.uci for n in tree.path_to(node.node_id)), node.position.fen,
             tree.annotations(node.node_id)) for node in tree.iter_nodes()]


class PgnRefereeTests(unittest.TestCase):
    def setUp(self):
        self.referee = RefereeDriver()

    def tearDown(self):
        self.referee.close()

    def test_import_builds_every_variation(self):
        tree = self.referee.import_text(SAMPLE)
        self.assertEqual(len(tree), 8)
        self.assertEqual(tree.current.node_id, 0)
        self.assertEqual(tree.headers['White'], 'Nidal')
        e4 = tree.root.children[0]
        e5, c5 = tree.node(e4).children
        self.assertEqual(tree.annotations(e5).nags, (1,))
        self.assertEqual(tree.annotations(c5).starting_comment, 'Sicilian start')

    def test_roundtrip_preserves_branches_annotations_and_headers(self):
        original = self.referee.import_text(SAMPLE)
        copy = self.referee.import_text(export_pgn(original))
        self.assertEqual(signature(original), signature(copy))
        self.assertEqual(copy.headers['Event'], original.headers['Event'])

    def test_illegal_move_in_variation_rejected(self):
        with self.assertRaisesRegex(PgnError, 'Bh6'):
            self.referee.import_text('1. e4 e5 (1... Bh6) 2. Nf3 *')

    def test_invalid_start_rejected_by_c(self):
        with self.assertRaises(PgnError):
            self.referee.import_text('[SetUp "1"]\n[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n*')

    def test_custom_black_start_exported(self):
        tree = self.referee.import_text('[SetUp "1"]\n[FEN "7k/8/8/8/8/8/8/R6K b - - 0 42"]\n42... Kg8 *')
        self.assertEqual(tree.label(tree.root.children[0]), '42... Kg8')
        exported = export_pgn(tree)
        self.assertIn('[SetUp "1"]', exported)
        self.assertEqual(signature(self.referee.import_text(exported)), signature(tree))

    def test_castling_zero_alias(self):
        tree = self.referee.import_text('1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6 4.0-0 *')
        pieces = tree.mainline()[-1].position.pieces
        self.assertEqual(pieces.get('g1'), 'K')
        self.assertEqual(pieces.get('f1'), 'R')

    def test_en_passant(self):
        tree = self.referee.import_text('[SetUp "1"]\n[FEN "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"]\n2.exd6 *')
        pieces = tree.mainline()[-1].position.pieces
        self.assertEqual(pieces.get('d6'), 'P')
        self.assertNotIn('d5', pieces)

    def test_underpromotion_variations(self):
        tree = self.referee.import_text('[SetUp "1"]\n[FEN "7k/P7/8/8/8/8/8/7K w - - 0 1"]\n1.a8=Q+ (1.a8=N) *')
        self.assertEqual(len(tree.root.children), 2)
        self.assertEqual({tree.node(n).position.pieces['a8'] for n in tree.root.children}, {'Q', 'N'})

    def test_ambiguous_san_rejected(self):
        prefix = '[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1"]\n'
        with self.assertRaisesRegex(PgnError, 'Nd2'):
            self.referee.import_text(prefix + '1.Nd2 *')
        tree = self.referee.import_text(prefix + '1.Nbd2 *')
        self.assertEqual(tree.mainline()[0].move.uci, 'b1d2')

    def test_incorrect_check_marker_rejected(self):
        with self.assertRaises(PgnError):
            self.referee.import_text('1. e4+ *')

    def test_duplicate_variations_merge_without_losing_comments(self):
        tree = self.referee.import_text('1.e4 {one} (1.e4 {two} c5) e5 *')
        self.assertEqual(len(tree.root.children), 1)
        e4 = tree.root.children[0]
        self.assertEqual(len(tree.node(e4).children), 2)
        self.assertIn('one', tree.annotations(e4).comment)
        self.assertIn('two', tree.annotations(e4).comment)

    def test_atomic_file_save_and_reopen(self):
        original = self.referee.import_text(SAMPLE)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'saved.pgn'
            path.write_text('old contents', encoding='utf-8')
            write_pgn_file(path, original)
            parsed, = read_pgn_file(path)
            restored = self.referee.import_text(path.read_text(encoding='utf-8'))
            self.assertEqual(parsed.headers['Event'], 'Opening study')
            self.assertEqual(signature(restored), signature(original))
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['saved.pgn'])

    def test_long_comment_whitespace_survives_export(self):
        comment = 'A long note ' * 25
        tree = self.referee.import_text('1.e4 {' + comment.strip() + '} e5 *')
        copy = self.referee.import_text(export_pgn(tree))
        self.assertEqual(signature(tree), signature(copy))

    def test_semicolon_comment_with_closing_brace_can_be_saved(self):
        tree = self.referee.import_text('1.e4 ; left } right\ne5 *')
        copy = self.referee.import_text(export_pgn(tree))
        self.assertEqual(signature(tree), signature(copy))

    def test_export_error_does_not_overwrite_existing_file(self):
        tree = self.referee.import_text('1.e4 *')
        tree.headers['bad name'] = 'invalid tag'
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'keep.pgn'
            target.write_text('keep these bytes', encoding='utf-8')
            with self.assertRaises(PgnError):
                write_pgn_file(target, tree)
            self.assertEqual(target.read_text(encoding='utf-8'), 'keep these bytes')
