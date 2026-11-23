"""A game tree containing a starting position and preserved move variations.

Pure Python: no Qt, engine process, or chess-rule implementation.
Node IDs identify occurrences, not just FENs: transpositions remain distinct.
"""
from dataclasses import dataclass, replace
from models import Move, PositionSnapshot


@dataclass(frozen=True)
class GameNode:
    node_id: int
    position: PositionSnapshot
    parent_id: int | None = None
    move: Move | None = None
    children: tuple[int, ...] = ()


class GameTree:
    """The first child is the original/main continuation, never overwritten.

    Preferred children remember the last visited variation for Next/Last.
    This choice does not reorder the children or replace the main line.
    """

    def __init__(self, starting_position: PositionSnapshot):
        self._nodes = {0: GameNode(0, starting_position)}
        self._current_id = 0
        self._preferred = {}

    @property
    def root(self):
        return self._nodes[0]

    @property
    def current(self):
        return self._nodes[self._current_id]

    def __len__(self):
        return len(self._nodes)

    def node(self, node_id: int) -> GameNode:
        return self._nodes[node_id]

    def path_to(self, node_id: int) -> tuple[GameNode, ...]:
        """Root-to-node move occurrences, excluding the root itself."""
        path = []
        node = self.node(node_id)
        while node.parent_id is not None:
            path.append(node)
            node = self.node(node.parent_id)
        return tuple(reversed(path))

    def select(self, node_id: int):
        """Select a known node and remember the route used to reach it."""
        path = self.path_to(node_id)  # Validate before changing selection.
        for node in path:
            self._preferred[node.parent_id] = node.node_id
        self._current_id = node_id

    def child_for_move(self, parent_id: int, uci: str) -> GameNode | None:
        for child_id in self.node(parent_id).children:
            child = self.node(child_id)
            if child.move.uci == uci:
                return child
        return None

    def add_child(self, parent_id: int, move: Move,
                  position: PositionSnapshot) -> GameNode:
        """Record an accepted move; reuse the same parent's existing move.

        The caller/referee must establish legality. An inconsistent snapshot
        for an existing move is rejected rather than silently overwriting it.
        """
        parent = self.node(parent_id)
        existing = self.child_for_move(parent_id, move.uci)
        if existing is not None:
            if existing.position.fen != position.fen:
                raise ValueError('Existing move has a different resulting FEN')
            return existing
        node_id = len(self._nodes)
        child = GameNode(node_id, position, parent_id, move)
        self._nodes[node_id] = child
        self._nodes[parent_id] = replace(parent, children=parent.children + (node_id,))
        return child

    def next_id(self, node_id: int | None = None) -> int | None:
        node = self.current if node_id is None else self.node(node_id)
        if not node.children:
            return None
        return self._preferred.get(node.node_id, node.children[0])

    def last_id(self) -> int:
        node_id = self.current.node_id
        while (next_id := self.next_id(node_id)) is not None:
            node_id = next_id
        return node_id

    def mainline(self) -> tuple[GameNode, ...]:
        """The original first-child line, independent of navigation choices."""
        nodes = []
        node = self.root
        while node.children:
            node = self.node(node.children[0])
            nodes.append(node)
        return tuple(nodes)

    def iter_nodes(self):
        """Preorder traversal; parents appear before children without recursion."""
        stack = [0]
        while stack:
            node = self.node(stack.pop())
            yield node
            stack.extend(reversed(node.children))

    def label(self, node_id: int) -> str:
        node = self.node(node_id)
        if node.parent_id is None:
            return 'Starting position'
        before = self.node(node.parent_id).position
        number = before.fen.split()[5]
        separator = '.' if before.turn == 'w' else '...'
        return f'{number}{separator} {node.move.san or node.move.uci}'
