"""Document identity and complete multi-game export; no Qt imports."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_tree import GameTree
from models import PositionSnapshot, STARTING_FEN
from pgn_service import PgnError, export_study, parse_pgn_text, write_study_file
from study import Chapter, Study


class StudyModelTests(unittest.TestCase):
    def test_empty_document_is_rejected(self):
        with self.assertRaises(ValueError):
            Study.from_games(())

    def test_duplicate_titles_have_distinct_ids(self):
        games = parse_pgn_text('[Event "Same"]\n*\n\n[Event "Same"]\n*')
        study = Study.from_games(games)
        self.assertEqual([c.title for c in study.chapters], ['Same', 'Same'])
        self.assertNotEqual(study.chapters[0].chapter_id, study.chapters[1].chapter_id)
        self.assertEqual(study.index_of(study.chapters[1].chapter_id), 1)

    def test_duplicate_ids_and_invalid_selection_are_rejected(self):
        chapter = Chapter(tree=GameTree(PositionSnapshot(STARTING_FEN)))
        with self.assertRaises(ValueError):
            Study((chapter, replace(chapter)))
        with self.assertRaises(ValueError):
            Study((chapter,), active_index=1)

    def test_loaded_tree_is_retained_by_identity(self):
        tree = GameTree(PositionSnapshot(STARTING_FEN))
        study = Study.from_tree(tree)
        self.assertIs(study.active.tree, tree)
        tree.annotate(0, comment='Preserved edit')
        self.assertEqual(study.active.tree.annotations(0).comment, 'Preserved edit')

    def test_chapter_name_tag_precedes_event(self):
        game = parse_pgn_text('[ChapterName "Lesson"]\n[Event "Study"]\n*')[0]
        self.assertEqual(Chapter(parsed=game).title, 'Lesson')

    def test_all_chapters_export_in_original_order(self):
        trees = [GameTree(PositionSnapshot(STARTING_FEN), {'Event': name}) for name in ('A', 'B', 'C')]
        trees[1].annotate(0, comment='Middle chapter')
        games = parse_pgn_text(export_study(trees))
        self.assertEqual([g.headers['Event'] for g in games], ['A', 'B', 'C'])
        self.assertEqual(games[1].nodes[0].comment, 'Middle chapter')

    def test_unvalidated_chapter_cannot_be_silently_omitted(self):
        with self.assertRaises(PgnError):
            export_study([GameTree(PositionSnapshot(STARTING_FEN)), None])

    def test_serialization_failure_leaves_destination_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'study.pgn'
            target.write_text('original', encoding='utf-8')
            invalid = GameTree(PositionSnapshot(STARTING_FEN), {'Result': 'invalid'})
            with self.assertRaises(PgnError):
                write_study_file(target, [invalid])
            self.assertEqual(target.read_text(), 'original')

    def test_replace_failure_leaves_destination_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'study.pgn'
            target.write_text('original', encoding='utf-8')
            with patch('os.replace', side_effect=OSError('simulated write failure')):
                with self.assertRaises(OSError):
                    write_study_file(target, [GameTree(PositionSnapshot(STARTING_FEN))])
            self.assertEqual(target.read_text(), 'original')
            self.assertEqual(list(Path(directory).iterdir()), [target])


if __name__ == '__main__':
    unittest.main()
