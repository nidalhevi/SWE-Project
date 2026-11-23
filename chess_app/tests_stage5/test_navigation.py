"""Real Qt + C navigation checks; includes inherited stage-4 regression tests.

Run from chess_app: python -m unittest discover -s tests_stage5 -v
Requires tests_stage4 from the previously installed stage-4 bundle.
"""
from PySide6.QtCore import Qt
import tests_stage4.test_gui as stage4
from models import PositionSnapshot


class NavigationTests(stage4.LegalMoveGuiTests):
    def go(self, node_id):
        self.controller.go_to(node_id)
        self.ready()

    def make_original_line(self):
        for uci in ('e2e4', 'e7e5', 'g1f3'):
            self.play(uci)
        tree = self.controller.tree
        return tree, tuple(node.node_id for node in tree.mainline())

    def test_new_branch_preserves_original_and_can_switch(self):
        tree, (e4, e5, nf3) = self.make_original_line()
        original_fen = tree.node(nf3).position.fen
        self.go(e4)
        self.play('c7c5')
        c5 = tree.current.node_id
        self.play('g1f3')
        branch_tip = tree.current.node_id
        self.assertEqual(tree.node(e4).children, (e5, c5))
        self.assertEqual([node.node_id for node in tree.mainline()], [e4, e5, nf3])
        self.go(nf3)
        self.assertEqual(self.controller.position.fen, original_fen)
        self.go(branch_tip)
        self.assertEqual(self.controller.position.fen, tree.node(branch_tip).position.fen)

    def test_navigation_buttons_remember_branch(self):
        tree, (e4, e5, nf3) = self.make_original_line()
        self.go(e4)
        self.play('c7c5')
        c5 = tree.current.node_id
        self.window.previous_button.click()
        self.ready()
        self.assertEqual(tree.current.node_id, e4)
        self.window.next_button.click()
        self.ready()
        self.assertEqual(tree.current.node_id, c5)
        self.window.first_button.click()
        self.ready()
        self.assertEqual(tree.current.node_id, 0)
        self.window.last_button.click()
        self.ready()
        self.assertEqual(tree.current.node_id, c5)
        self.assertEqual(tree.node(e4).children[0], e5)

    def test_replaying_existing_move_reuses_node(self):
        tree, (e4, e5, nf3) = self.make_original_line()
        original_size = len(tree)
        self.go(e4)
        self.play('e7e5')
        self.assertEqual(tree.current.node_id, e5)
        self.assertEqual(len(tree), original_size)
        self.assertTrue(self.controller.can_next)

    def test_tree_selection_routes_to_matching_board(self):
        tree, (e4, e5, nf3) = self.make_original_line()
        item = self.window._node_items[e4]
        self.window.moves_tree.setCurrentItem(item)
        self.ready()
        self.assertEqual(tree.current.node_id, e4)
        self.assertEqual(self.window.board._pieces, tree.node(e4).position.pieces)
        selected = self.window.moves_tree.currentItem()
        self.assertEqual(selected.data(0, Qt.ItemDataRole.UserRole), e4)

    def test_san_is_requested_before_move(self):
        self.play('e2e4')
        tree = self.controller.tree
        self.assertEqual(tree.current.move.san, 'e4')
        self.assertEqual(tree.label(tree.current.node_id), '1. e4')
        self.play('e7e5')
        self.assertEqual(tree.label(tree.current.node_id), '1... e5')

    def test_threefold_history_survives_navigation(self):
        for uci in ('g1f3', 'g8f6', 'f3g1', 'f6g8') * 2:
            self.play(uci)
        tree = self.controller.tree
        repeated_id = tree.current.node_id
        self.assertEqual(self.controller.game_status, 'threefold-repetition')
        self.window.first_button.click()
        self.ready()
        self.assertEqual(self.controller.game_status, 'ongoing')
        self.go(repeated_id)
        self.assertEqual(self.controller.game_status, 'threefold-repetition')
        self.assertFalse(self.controller.can_move)
        self.assertEqual(len(tree), 9)

    def test_custom_start_keeps_black_move_number(self):
        self.load('7k/8/8/8/8/8/8/R6K b - - 0 42')
        self.play('h8g8')
        tree = self.controller.tree
        last = tree.current.node_id
        self.assertEqual(tree.label(last), '42... Kg8')
        self.window.first_button.click()
        self.ready()
        self.assertEqual(self.controller.position.turn, 'b')
        self.go(last)
        self.assertEqual(self.controller.position.fen, tree.node(last).position.fen)

    def test_navigation_ignores_extra_requests_and_board_clicks(self):
        tree, (e4, e5, nf3) = self.make_original_line()
        c = self.controller
        c.go_to(e4)
        c.go_to(nf3)
        c.on_square_clicked('c7')
        c.on_square_clicked('c5')
        self.ready()
        self.assertEqual(tree.current.node_id, e4)
        self.assertEqual(len(tree), 4)

    def test_navigation_retains_special_move_results(self):
        self.load('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')
        self.play('e1g1')
        tree = self.controller.tree
        king_side = tree.current.node_id
        self.go(0)
        self.play('e1c1')
        queen_side = tree.current.node_id
        self.go(king_side)
        self.assertEqual(self.controller.position.pieces.get('f1'), 'R')
        self.go(queen_side)
        self.assertEqual(self.controller.position.pieces.get('d1'), 'R')
        self.assertEqual(len(tree.root.children), 2)

    def test_promotion_choices_create_distinct_variations(self):
        self.load('7k/P7/8/8/8/8/8/7K w - - 0 1')
        tree = self.controller.tree
        self.play('a7a8q')
        queen = tree.current.node_id
        self.go(0)
        self.play('a7a8n')
        knight = tree.current.node_id
        self.assertEqual(len(tree.root.children), 2)
        self.go(queen)
        self.assertEqual(self.controller.position.pieces.get('a8'), 'Q')
        self.go(knight)
        self.assertEqual(self.controller.position.pieces.get('a8'), 'N')

    def test_close_during_replay(self):
        tree, ids = self.make_original_line()
        self.controller.first()
        self.window.close()
        stage4.wait_until(lambda: self.window._referee_stopped)
        self.assertEqual(self.controller.phase, 'closed')

    def test_rejected_load_keeps_existing_variations(self):
        tree, (e4, e5, nf3) = self.make_original_line()
        self.go(e4)
        self.play('c7c5')
        current = tree.current.node_id
        size = len(tree)
        self.controller.load_position(PositionSnapshot('8/8/8/8/8/8/8/8 w - - 0 1'))
        self.ready()
        self.assertIs(self.controller.tree, tree)
        self.assertEqual(tree.current.node_id, current)
        self.assertEqual(len(tree), size)


class StartupFailureTests(stage4.StartupFailureTests):
    """Keep the stage-4 missing-executable regression check."""
    pass
