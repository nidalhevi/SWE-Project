"""PGN syntax and file checks; standard library only, no Qt/referee required."""
from pathlib import Path
import tempfile
import unittest
from pgn_service import PgnError, parse_pgn_text, read_pgn_file


class PgnSyntaxTests(unittest.TestCase):
    def test_plain_pasted_moves_without_result(self):
        game, = parse_pgn_text('1.e4 e5 2.Nf3 Nc6')
        self.assertEqual(len(game.nodes), 5)
        self.assertEqual(game.nodes[1].san, 'e4')

    def test_nested_variations_and_mainline_parentage(self):
        game, = parse_pgn_text('1. e4 e5 (1... c5 2. Nf3 (2. Nc3)) 2. Nf3 *')
        self.assertEqual(game.nodes[1].children, [2, 3])
        self.assertEqual(game.nodes[3].children, [4, 5])
        self.assertEqual(game.nodes[2].children, [6])

    def test_comments_and_annotations(self):
        game, = parse_pgn_text('{root} 1. e4! {pawn} e5 ( {intro} 1... c5 $5) *')
        self.assertEqual(game.nodes[0].comment, 'root')
        self.assertEqual(game.nodes[1].comment, 'pawn')
        self.assertEqual(game.nodes[1].nags, {1})
        self.assertEqual(game.nodes[3].starting_comment, 'intro')
        self.assertEqual(game.nodes[3].nags, {5})

    def test_semicolon_comment_and_escape_line(self):
        game, = parse_pgn_text('% ignore this line\n1. e4 ; a note\ne5 *')
        self.assertEqual(game.nodes[1].comment, 'a note')
        self.assertEqual(len(game.nodes), 3)

    def test_multiple_games(self):
        games = parse_pgn_text('[Event "One"]\n1. e4 *\n[Event "Two"]\n1. d4 *')
        self.assertEqual(len(games), 2)
        self.assertEqual(games[1].headers['Event'], 'Two')

    def test_headers_can_separate_games_without_termination(self):
        self.assertEqual(len(parse_pgn_text('1.e4\n[Event "Two"]\n1.d4 *')), 2)

    def test_escaped_header_values(self):
        text = r'[Event "A \"quote\" and \\ path"]' + '\n*'
        game, = parse_pgn_text(text)
        self.assertEqual(game.headers['Event'], 'A "quote" and \\ path')

    def test_custom_starting_position(self):
        text = '[SetUp "1"]\n[FEN "7k/8/8/8/8/8/8/R6K b - - 0 42"]\n42... Kg8 *'
        game, = parse_pgn_text(text)
        self.assertEqual(game.starting_position.turn, 'b')
        self.assertTrue(game.starting_position.fen.endswith('0 42'))

    def test_empty_text_rejected(self):
        with self.assertRaises(PgnError):
            parse_pgn_text('  {only a comment}  ')

    def test_unknown_text_not_silently_skipped(self):
        for text in ('garbage 1. e4 *', '1. e4 nonsense e5 *', '1. e4 -- *'):
            with self.subTest(text=text), self.assertRaises(PgnError):
                parse_pgn_text(text)

    def test_unclosed_comment_rejected(self):
        with self.assertRaisesRegex(PgnError, 'comment'):
            parse_pgn_text('1. e4 {unclosed')

    def test_unclosed_and_empty_variations_rejected(self):
        for text in ('1. e4 (1. d4', '1. e4 () *', '1. e4 ) *'):
            with self.subTest(text=text), self.assertRaises(PgnError):
                parse_pgn_text(text)

    def test_bad_headers_rejected(self):
        for text in ('[Event noquote]\n*', '[Event "One"]\n[Event "Two"]\n*',
                     '[SetUp "1"]\n*', '[SetUp "0"]\n[FEN "bad"]\n*',
                     '[Variant "Chess960"]\n*'):
            with self.subTest(text=text), self.assertRaises(PgnError):
                parse_pgn_text(text)

    def test_result_mismatch_rejected(self):
        with self.assertRaisesRegex(PgnError, 'disagree'):
            parse_pgn_text('[Result "1-0"]\n1. e4 *')

    def test_invalid_nags_rejected(self):
        for text in ('1. e4 $256 *', '1. e4 $x *', '$1 1. e4 *'):
            with self.subTest(text=text), self.assertRaises(PgnError):
                parse_pgn_text(text)

    def test_utf8_bom_and_legacy_encoding(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'game.pgn'
            path.write_text('[White "Nidal"]\n1.e4 *', encoding='utf-8-sig')
            self.assertEqual(read_pgn_file(path)[0].headers['White'], 'Nidal')
            path.write_bytes('[White "André"]\n1.e4 *'.encode('latin-1'))
            with self.assertRaises(UnicodeDecodeError):
                read_pgn_file(path)
            self.assertEqual(read_pgn_file(path, encoding='latin-1')[0].headers['White'], 'André')


if __name__ == '__main__':
    unittest.main()
