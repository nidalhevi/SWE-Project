"""Read/write standard-chess PGN and validate every move through the C referee.

No chess rules are implemented here. SAN shape filters the referee's legal
moves, and its canonical SAN output resolves the match. validate_game() is a
pure generator: the caller executes its requests asynchronously or in tests.
"""
from dataclasses import dataclass, field, replace
from pathlib import Path
import re

from game_tree import GameTree
from models import Move, PositionSnapshot, STARTING_FEN

RESULTS = {'*', '1-0', '0-1', '1/2-1/2'}
TAG = re.compile(r'\[\s*([A-Za-z][A-Za-z0-9_]*)\s+"((?:[^"\\\r\n]|\\["\\])*)"\s*\]')
NUMBER = re.compile(r'[0-9]+\s*\.(?:\s*\.\s*\.)?')
SAN = re.compile(
    r'(?P<piece>[KQRBN])?(?P<file>[a-h])?(?P<rank>[1-8])?'
    r'(?P<capture>x)?(?P<to>[a-h][1-8])(?P<promotion>=?[QRBN])?'
    r'(?P<check>\+\+|[+#])?'
)
CASTLE = re.compile(r'(?:O-O(?:-O)?|0-0(?:-0)?)(?:\+\+|[+#])?')
SYMBOLIC_NAGS = {'!': 1, '?': 2, '!!': 3, '??': 4, '!?': 5, '?!': 6}


class PgnError(ValueError):
    """Malformed PGN, unsupported notation, or referee validation failure."""


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    line: int


@dataclass
class ParsedNode:
    node_id: int
    parent_id: int | None = None
    san: str | None = None
    line: int = 1
    children: list[int] = field(default_factory=list)
    comment: str = ''
    starting_comment: str = ''
    nags: set[int] = field(default_factory=set)


@dataclass
class ParsedGame:
    headers: dict[str, str]
    starting_position: PositionSnapshot
    nodes: dict[int, ParsedNode]

    @property
    def description(self):
        white = self.headers.get('White', '?')
        black = self.headers.get('Black', '?')
        event = self.headers.get('Event', 'Untitled game')
        return f'{white} — {black} | {event} | {len(self.nodes) - 1} moves'


@dataclass(frozen=True)
class RefereeRequest:
    action: str
    payload: object = None
    description: str = ''


def _join(first, second):
    return '\n'.join(part for part in (first, second) if part)


def _tokens(text):
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    index, line = 0, 1
    while index < len(text):
        char = text[index]
        if char.isspace():
            line += char == '\n'
            index += 1
            continue
        if char == '%' and (index == 0 or text[index - 1] == '\n'):
            end = text.find('\n', index)
            index = len(text) if end < 0 else end
            continue
        if char == '[':
            match = TAG.match(text, index)
            if match is None:
                raise PgnError(f'Line {line}: malformed header tag')
            name, value = match.groups()
            value = re.sub(r'\\(["\\])', r'\1', value)
            yield Token('tag', (name, value), line)
            line += match.group().count('\n')
            index = match.end()
        elif char == '{':
            end = text.find('}', index + 1)
            if end < 0:
                raise PgnError(f'Line {line}: unclosed comment')
            content = text[index + 1:end]
            yield Token('comment', content.strip(), line)
            line += content.count('\n')
            index = end + 1
        elif char == ';':
            end = text.find('\n', index)
            if end < 0:
                end = len(text)
            yield Token('comment', text[index + 1:end].strip(), line)
            index = end
        elif char in '()':
            yield Token(char, char, line)
            index += 1
        elif char == '$':
            match = re.match(r'\$([0-9]+)', text[index:])
            digits = (match[1].lstrip('0') or '0') if match is not None else ''
            if not digits or len(digits) > 3 or int(digits) > 255:
                raise PgnError(f'Line {line}: invalid numeric annotation')
            yield Token('nag', int(digits), line)
            index += len(match.group())
        elif char in '!?':
            end = index + 1
            while end < len(text) and text[end] in '!?':
                end += 1
            symbol = text[index:end]
            if symbol not in SYMBOLIC_NAGS:
                raise PgnError(f'Line {line}: invalid annotation {symbol!r}')
            yield Token('nag', SYMBOLIC_NAGS[symbol], line)
            index = end
        elif (match := NUMBER.match(text, index)) is not None:
            yield Token('number', match.group(), line)
            line += match.group().count('\n')
            index = match.end()
        else:
            end = index
            while end < len(text) and not text[end].isspace() and text[end] not in '[]{}();$!?':
                end += 1
            if end == index:
                raise PgnError(f'Line {line}: unexpected character {char!r}')
            value = text[index:end]
            kind = 'result' if value in RESULTS else 'san'
            yield Token(kind, value, line)
            index = end


def _starting_position(headers):
    variant = headers.get('Variant', 'Standard').casefold()
    if variant not in ('standard', 'chess', 'normal'):
        raise PgnError('Only standard chess PGN is supported')
    setup = headers.get('SetUp')
    if setup not in (None, '0', '1'):
        raise PgnError('SetUp must be 0 or 1')
    if setup == '1' and 'FEN' not in headers:
        raise PgnError('SetUp 1 requires a FEN header')
    if setup == '0' and 'FEN' in headers:
        raise PgnError('SetUp 0 conflicts with the FEN header')
    if headers.get('Result', '*') not in RESULTS:
        raise PgnError('Invalid Result header')
    try:
        return PositionSnapshot(headers.get('FEN', STARTING_FEN))
    except ValueError as error:
        raise PgnError(f'Invalid starting FEN: {error}') from error


def parse_pgn_text(text: str) -> tuple[ParsedGame, ...]:
    """Parse all games. Reject unknown tokens instead of silently skipping them.

    Move numbers are treated as notation; actual turn and numbering come from
    the referee's positions. A final result marker is optional for pasted text.
    A new header after movetext also starts the next game.
    """
    tokens = list(_tokens(text))
    games, index = [], 0
    while index < len(tokens):
        headers, nodes = {}, {0: ParsedNode(0)}
        current, stack = 0, []
        prefix, pending = False, ''
        seen_content = False
        while index < len(tokens):
            token = tokens[index]
            kind, value = token.kind, token.value
            if kind == 'tag' and len(nodes) > 1 and not stack:
                break  # Next game, even without a termination marker.
            index += 1
            if kind == 'tag':
                if stack or len(nodes) > 1:
                    raise PgnError(f'Line {token.line}: header inside movetext')
                name, contents = value
                if name in headers:
                    raise PgnError(f'Line {token.line}: duplicate {name} header')
                headers[name] = contents
                seen_content = True
            elif kind == 'comment':
                if prefix:
                    pending = _join(pending, value)
                else:
                    nodes[current].comment = _join(nodes[current].comment, value)
            elif kind == 'number':
                continue
            elif kind == 'nag':
                if current == 0 or prefix:
                    raise PgnError(f'Line {token.line}: annotation without a move')
                nodes[current].nags.add(value)
            elif kind == '(':
                if current == 0 or prefix:
                    raise PgnError(f'Line {token.line}: variation without a preceding move')
                stack.append((current, prefix, pending))
                current = nodes[current].parent_id
                prefix, pending = True, ''
            elif kind == ')':
                if not stack or prefix:
                    raise PgnError(f'Line {token.line}: unmatched or empty variation')
                current, prefix, pending = stack.pop()
            elif kind == 'result':
                if stack:
                    raise PgnError(f'Line {token.line}: result inside an unclosed variation')
                if 'Result' in headers and headers['Result'] != value:
                    raise PgnError(f'Line {token.line}: Result header and termination disagree')
                headers['Result'] = value
                seen_content = True
                while index < len(tokens) and tokens[index].kind == 'comment':
                    nodes[current].comment = _join(nodes[current].comment, tokens[index].value)
                    index += 1
                break
            elif kind == 'san':
                if SAN.fullmatch(value) is None and CASTLE.fullmatch(value) is None:
                    raise PgnError(f'Line {token.line}: unsupported or malformed move {value!r}')
                child_id = len(nodes)
                child = ParsedNode(child_id, current, value, token.line,
                                   starting_comment=pending if prefix else '')
                nodes[current].children.append(child_id)
                nodes[child_id] = child
                current = child_id
                prefix, pending = False, ''
                seen_content = True
        if stack:
            raise PgnError('Unclosed variation at end of game')
        if seen_content:
            games.append(ParsedGame(headers, _starting_position(headers), nodes))
    if not games:
        raise PgnError('No PGN game found; paste moves such as 1. e4 e5 2. Nf3 *')
    return tuple(games)


def read_pgn_file(path, *, encoding='utf-8-sig'):
    """UTF-8/BOM by default; the GUI offers Latin-1 for older PGN files."""
    return parse_pgn_text(Path(path).read_text(encoding=encoding))


def _normalized_san(san):
    value = san.replace('0', 'O').replace('++', '+')
    return re.sub(r'([18])([QRBN])', r'\1=\2', value)


def _matches_san(requested, canonical):
    requested, canonical = _normalized_san(requested), _normalized_san(canonical)
    # Missing check markers are tolerated on import; incorrect supplied ones aren't.
    if requested.endswith(('+', '#')) and requested[-1] != canonical[-1]:
        return False
    return requested.rstrip('+#') == canonical.rstrip('+#')


def _candidates(san, position, legal_moves):
    normalized = _normalized_san(san)
    if CASTLE.fullmatch(normalized):
        rank = '1' if position.turn == 'w' else '8'
        destination = ('c' if normalized.startswith('O-O-O') else 'g') + rank
        return tuple(m for m in legal_moves if m.from_square == 'e' + rank and m.to_square == destination)
    match = SAN.fullmatch(normalized)
    piece = match['piece'] or 'P'
    promotion = match['promotion'][-1].lower() if match['promotion'] else None
    return tuple(
        move for move in legal_moves
        if position.pieces.get(move.from_square, '').upper() == piece
        and move.to_square == match['to'] and move.promotion == promotion
        and (not match['file'] or move.from_square[0] == match['file'])
        and (not match['rank'] or move.from_square[1] == match['rank'])
    )


def _validation_steps(game):
    stack = [('enter', node_id) for node_id in reversed(game.nodes[0].children)]
    while stack:
        action, node_id = stack.pop()
        yield action, node_id
        if action == 'enter':
            stack.append(('leave', node_id))
            stack.extend(('enter', child) for child in reversed(game.nodes[node_id].children))


def validate_game(game: ParsedGame):
    """Yield RefereeRequests, receive results via send(), return a GameTree.

    Each move is selected from referee legal moves, compared against referee SAN,
    and played by the referee. Undo restores the parent before sibling branches.
    The engine finishes at the new root. The caller commits only on success.
    """
    accepted = yield RefereeRequest('load_position', game.starting_position, 'Validating starting FEN')
    tree = GameTree(accepted, game.headers)
    mapping = {0: 0}
    root = game.nodes[0]
    tree.annotate(0, comment=root.comment)
    for action, parsed_id in _validation_steps(game):
        parsed = game.nodes[parsed_id]
        parent_id = mapping[parsed.parent_id]
        parent = tree.node(parent_id)
        if action == 'leave':
            restored = yield RefereeRequest('undo', description='Restoring variation parent')
            if restored.fen != parent.position.fen:
                raise PgnError('Referee undo did not restore the variation parent')
            continue
        description = f'Validating line {parsed.line}: {parsed.san}'
        legal = yield RefereeRequest('legal_moves', description=description)
        chosen = None
        for move in _candidates(parsed.san, parent.position, legal):
            canonical = yield RefereeRequest('san', move, description)
            if _matches_san(parsed.san, canonical):
                chosen = replace(move, san=canonical)
                break
        if chosen is None:
            raise PgnError(f'Line {parsed.line}: {parsed.san!r} is not valid unambiguous SAN in this position')
        position = yield RefereeRequest('play_move', chosen, description)
        node = tree.add_child(parent_id, chosen, position)
        mapping[parsed_id] = node.node_id
        tree.annotate(node.node_id, comment=parsed.comment,
                      starting_comment=parsed.starting_comment, nags=parsed.nags)
    tree.select(0)
    return tree


def _comment(text):
    if '}' in text:
        return '\n'.join(';' + line for line in text.split('\n'))
    return '{' + text + '}'


def export_pgn(tree: GameTree) -> str:
    """Export every variation, header, comment, and numeric annotation.

    All move SAN must have been supplied by the referee (as in stages 5/6).
    Current selection and navigation preferences do not change the main line.
    """
    headers = dict(tree.headers)
    defaults = {'Event': '?', 'Site': '?', 'Date': '????.??.??', 'Round': '?',
                'White': '?', 'Black': '?', 'Result': '*'}
    headers = {**defaults, **headers}
    if headers['Result'] not in RESULTS:
        raise PgnError('Invalid Result metadata')
    if tree.root.position.fen != STARTING_FEN:
        headers.update(SetUp='1', FEN=tree.root.position.fen)
    else:
        headers.pop('FEN', None)
        headers.pop('SetUp', None)
    # PlyCount refers to the original main line, not the selected variation.
    if 'PlyCount' in headers:
        headers['PlyCount'] = str(len(tree.mainline()))
    lines = []
    for name, value in headers.items():
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) is None or '\n' in value or '\r' in value:
            raise PgnError('Invalid header name/value for export')
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(f'[{name} "{escaped}"]')
    tokens = []
    root_annotation = tree.annotations(0)
    if root_annotation.comment:
        tokens.append(_comment(root_annotation.comment))
    # A line emits its first move, then alternative first moves, then continues.
    stack = [('children', 0)]
    while stack:
        kind, value = stack.pop()
        if kind == 'token':
            tokens.append(value)
        elif kind == 'move':
            node = tree.node(value)
            if not node.move.san:
                raise PgnError(f'Move at node {value} has no referee-provided SAN')
            annotation = tree.annotations(value)
            if annotation.starting_comment:
                tokens.append(_comment(annotation.starting_comment))
            tokens.extend((tree.label(value).split(' ', 1)[0], node.move.san))
            tokens.extend(f'${nag}' for nag in annotation.nags)
            if annotation.comment:
                tokens.append(_comment(annotation.comment))
        elif kind == 'line':
            stack.extend((('children', value), ('move', value)))
        else:
            children = tree.node(value).children
            if children:
                first, *alternatives = children
                sequence = [('move', first)]
                for alternative in alternatives:
                    sequence.extend((('token', '('), ('line', alternative), ('token', ')')))
                sequence.append(('children', first))
                stack.extend(reversed(sequence))
    tokens.append(headers['Result'])
    # Wrap between tokens, keeping comment text intact. Semicolon comments
    # always occupy their own lines so they cannot swallow the following move.
    wrapped, current = [], ''
    for token in tokens:
        separate = token.startswith(';') or '\n' in token
        if current and (separate or len(current) + len(token) + 1 > 88):
            wrapped.append(current)
            current = ''
        if separate:
            wrapped.append(token)
        else:
            current = (current + ' ' + token).lstrip()
    if current:
        wrapped.append(current)
    return '\n'.join(lines) + '\n\n' + '\n'.join(wrapped) + '\n'



def write_pgn_file(path, tree):
    """Serialize first, then atomically replace the selected destination file."""
    import os
    import tempfile
    destination = Path(path)
    text = export_pgn(tree)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
