"""An ordered PGN document. Each chapter owns one retained variation tree."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from game_tree import GameTree
    from pgn_service import ParsedGame


@dataclass
class Chapter:
    parsed: ParsedGame | None = None
    tree: GameTree | None = None
    chapter_id: str = field(default_factory=lambda: uuid4().hex)
    error: str | None = None

    @property
    def title(self):
        headers = self.tree.headers if self.tree is not None else self.parsed.headers
        for tag in ('ChapterName', 'Event'):
            title = headers.get(tag, '').strip()
            if title and title != '?':
                return title
        white, black = headers.get('White', '?'), headers.get('Black', '?')
        return f'{white} — {black}' if (white, black) != ('?', '?') else 'Untitled chapter'


@dataclass
class Study:
    chapters: tuple[Chapter, ...]
    active_index: int = 0
    source_path: str | None = None

    def __post_init__(self):
        if not self.chapters or not 0 <= self.active_index < len(self.chapters):
            raise ValueError('A study needs at least one chapter and a valid selection')
        ids = [chapter.chapter_id for chapter in self.chapters]
        if len(ids) != len(set(ids)):
            raise ValueError('Chapter IDs must be distinct')

    @classmethod
    def from_games(cls, games, *, source_path=None):
        return cls(tuple(Chapter(parsed=game) for game in games), source_path=source_path)

    @classmethod
    def from_tree(cls, tree):
        return cls((Chapter(tree=tree),))

    @property
    def active(self):
        return self.chapters[self.active_index]

    def index_of(self, chapter_id):
        for index, chapter in enumerate(self.chapters):
            if chapter.chapter_id == chapter_id:
                return index
        raise KeyError(chapter_id)
