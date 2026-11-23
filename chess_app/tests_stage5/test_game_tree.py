"""Pure data-model checks: no Qt, executable, or extra libraries required."""
from dataclasses import FrozenInstanceError
import unittest

from game_tree import GameTree
from models import Move, PositionSnapshot, STARTING_FEN

START = PositionSnapshot(STARTING_FEN)
E4 = PositionSnapshot('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1')
E5 = PositionSnapshot('rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2')
C5 = PositionSnapshot('rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2')


class GameTreeTests(unittest.TestCase):
    def setUp(self):
        self.tree = GameTree(START)
        self.e4 = self.tree.add_child(0, Move('e2', 'e4', san='e4'), E4)
        self.e5 = self.tree.add_child(self.e4.node_id, Move('e7', 'e5', san='e5'), E5)

    def test_new_variation_preserves_original(self):
        c5 = self.tree.add_child(self.e4.node_id, Move('c7', 'c5', san='c5'), C5)
        self.assertEqual(self.tree.node(self.e4.node_id).children,
                         (self.e5.node_id, c5.node_id))
        self.assertEqual([n.move.uci for n in self.tree.mainline()], ['e2e4', 'e7e5'])

    def test_same_move_is_reused(self):
        node = self.tree.add_child(0, Move.from_uci('e2e4'), E4)
        self.assertEqual(node.node_id, self.e4.node_id)
        self.assertEqual(len(self.tree), 3)
        self.assertEqual(node.move.san, 'e4')

    def test_inconsistent_duplicate_is_rejected(self):
        with self.assertRaises(ValueError):
            self.tree.add_child(0, Move.from_uci('e2e4'), E5)
        self.assertEqual(self.tree.node(self.e4.node_id).position, E4)

    def test_next_remembers_variation_without_reordering(self):
        c5 = self.tree.add_child(self.e4.node_id, Move('c7', 'c5', san='c5'), C5)
        self.tree.select(c5.node_id)
        self.tree.select(0)
        self.assertEqual(self.tree.next_id(), self.e4.node_id)
        self.assertEqual(self.tree.last_id(), c5.node_id)
        self.assertEqual(self.tree.node(self.e4.node_id).children[0], self.e5.node_id)

    def test_path_and_occurrences_are_distinct(self):
        # A tree stores occurrences, even if a position is reached again.
        again = self.tree.add_child(self.e5.node_id, Move('g1', 'f3'), START)
        self.assertEqual([n.node_id for n in self.tree.path_to(again.node_id)],
                         [self.e4.node_id, self.e5.node_id, again.node_id])
        self.assertNotEqual(again.node_id, self.tree.root.node_id)
        self.assertEqual(self.tree.path_to(0), ())

    def test_unknown_node_cannot_change_selection(self):
        self.tree.select(self.e4.node_id)
        with self.assertRaises(KeyError):
            self.tree.select(999)
        self.assertEqual(self.tree.current.node_id, self.e4.node_id)

    def test_labels_include_active_side_and_move_number(self):
        self.assertEqual(self.tree.label(self.e4.node_id), '1. e4')
        self.assertEqual(self.tree.label(self.e5.node_id), '1... e5')
        custom = GameTree(PositionSnapshot('7k/8/8/8/8/8/8/R6K b - - 0 42'))
        node = custom.add_child(0, Move('h8', 'g8', san='Kg8'), START)
        self.assertEqual(custom.label(node.node_id), '42... Kg8')

    def test_nodes_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.e4.parent_id = 123
        self.assertIsInstance(self.tree.root.children, tuple)

    def test_deep_lines_do_not_depend_on_python_recursion(self):
        tree = GameTree(START)
        parent = 0
        for _ in range(1100):
            parent = tree.add_child(parent, Move.from_uci('g1f3'), START).node_id
        tree.select(parent)
        self.assertEqual(len(tree.path_to(parent)), 1100)
        self.assertEqual(len(list(tree.iter_nodes())), 1101)


if __name__ == '__main__':
    unittest.main()
