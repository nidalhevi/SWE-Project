"""Image-import records and editable draft; no Qt, vision, or chess-rule dependency.

Squares always use canonical names a1..h8, independent of the photo orientation.
None means known empty; '?' means unknown, never silently assumed empty.
"""
from dataclasses import dataclass
import json
import math
from models import PositionSnapshot

SQUARES = tuple(f'{file}{rank}' for rank in range(1, 9) for file in 'abcdefgh')
PIECES = 'PNBRQKpnbrqk'
UNKNOWN = '?'
MAX_RESPONSE_BYTES = 262144


class ImageImportError(ValueError):
    pass


@dataclass(frozen=True)
class SquareObservation:
    square: str
    piece: str | None  # '?' is unknown; None is known empty.
    confidence: float | None = None


@dataclass(frozen=True)
class RecognitionResult:
    request_id: int
    status: str
    squares: tuple[SquareObservation, ...]
    message: str = ''


@dataclass(frozen=True)
class PositionMetadata:
    turn: str | None = None
    castling: str = '-'
    en_passant: str = '-'
    halfmove_clock: int = 0
    fullmove_number: int = 1


def recognition_from_probabilities(probabilities, *, min_confidence=0.5):
    """Convert teammate's (64,13) probabilities to the adapter return mapping.

    Rows are a1..h8. Columns match chessvision.labels.FEN_CHARS:
    empty, P,N,B,R,Q,K,p,n,b,r,q,k. This does not call or train a classifier.
    Low-confidence/tied predictions remain unknown for human correction.
    """
    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ImageImportError('min_confidence must be from 0 to 1')
    rows = list(probabilities)
    if len(rows) != 64:
        raise ImageImportError('Expected 64 probability rows, indexed a1..h8')
    pieces, confidence = {}, {}
    labels = (None, *PIECES)
    for square, row in zip(SQUARES, rows):
        try:
            values = [float(value) for value in row]
        except (TypeError, ValueError) as error:
            raise ImageImportError('Probability rows must be numeric') from error
        if (len(values) != 13 or any(not math.isfinite(value) or not 0 <= value <= 1 for value in values)
                or abs(sum(values) - 1) > .001):
            raise ImageImportError('Each square needs 13 finite probabilities summing to 1')
        peak = max(values)
        best = values.index(peak)
        confidence[square] = peak
        pieces[square] = labels[best] if peak >= min_confidence and values.count(peak) == 1 else UNKNOWN
    return {'pieces': pieces, 'confidence': confidence}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ImageImportError('Duplicate recognition field: ' + key)
        result[key] = value
    return result


def parse_recognition(data, expected_id):
    """Strict version-1 worker response. Missing squares remain unknown.

    Payload: {version:1, request_id:N, status:'ok'|'unavailable',
              pieces:{'e1':'K','e4':null,...}, confidence:{'e1':0.9,...}}.
    An empty pieces mapping does not describe an empty board.
    """
    if len(data) > MAX_RESPONSE_BYTES:
        raise ImageImportError('Recognition response exceeded the limit')
    try:
        document = json.loads(data, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as error:
        raise ImageImportError('Invalid recognition JSON: ' + str(error)) from error
    if not isinstance(document, dict):
        raise ImageImportError('Recognition response must be an object')
    if type(document.get('version')) is not int or document['version'] != 1:
        raise ImageImportError('Unsupported recognition response version')
    if type(document.get('request_id')) is not int or document['request_id'] != expected_id:
        raise ImageImportError('Recognition response belongs to a different request')
    status = document.get('status')
    if status not in ('ok', 'unavailable'):
        raise ImageImportError('Unknown recognition status')
    pieces, confidence = document.get('pieces', {}), document.get('confidence', {})
    if not isinstance(pieces, dict) or not isinstance(confidence, dict):
        raise ImageImportError('pieces and confidence must be square mappings')
    if any(square not in SQUARES for square in (*pieces, *confidence)):
        raise ImageImportError('Recognition returned an invalid square')
    for piece in pieces.values():
        if piece is not None and (not isinstance(piece, str) or piece not in (*PIECES, UNKNOWN)):
            raise ImageImportError('Recognition returned an invalid piece')
    for value in confidence.values():
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ImageImportError('Confidence must be a finite number from 0 to 1')
    message = document.get('message', '')
    if not isinstance(message, str) or len(message) > 2000:
        raise ImageImportError('Invalid recognition message')
    if status == 'unavailable' and (pieces or confidence):
        raise ImageImportError('Unavailable recognition cannot supply piece predictions')
    observations = tuple(SquareObservation(square, pieces.get(square, UNKNOWN), confidence.get(square))
                         for square in SQUARES)
    return RecognitionResult(expected_id, status, observations, message)


def placement_of(pieces):
    rows = []
    for rank in range(8, 0, -1):
        row, empty = '', 0
        for file in 'abcdefgh':
            piece = pieces.get(f'{file}{rank}')
            if piece is None or piece == UNKNOWN:
                empty += 1
            else:
                if empty:
                    row += str(empty)
                row += piece
                empty = 0
        rows.append(row + (str(empty) if empty else ''))
    return '/'.join(rows)


class ImageDraft:
    """Mutable correction state, entirely separate from the accepted game tree."""
    def __init__(self):
        self.cells = dict.fromkeys(SQUARES, UNKNOWN)
        self.confidence = {}

    @property
    def unknown_squares(self):
        return tuple(square for square in SQUARES if self.cells[square] == UNKNOWN)

    @property
    def uncertain_squares(self):
        return tuple(square for square, value in self.confidence.items() if value < 0.8)

    def apply(self, result):
        if result.status != 'ok':
            return False
        self.cells = {item.square: item.piece for item in result.squares}
        self.confidence = {item.square: item.confidence for item in result.squares if item.confidence is not None}
        return True

    def set_square(self, square, piece):
        if square not in SQUARES:
            raise ImageImportError('Invalid square')
        if piece is not None and (not isinstance(piece, str) or piece not in (*PIECES, UNKNOWN)):
            raise ImageImportError('Invalid piece')
        self.cells[square] = piece
        self.confidence.pop(square, None)

    def mark_unknown_empty(self):
        for square in self.unknown_squares:
            self.set_square(square, None)

    def load_placement(self, text):
        """Paste the first FEN field only; metadata must still be supplied explicitly."""
        if len(text.split()) != 1:
            raise ImageImportError('Paste only the piece-placement field, before the first space in a FEN')
        try:
            position = PositionSnapshot(text.strip() + ' w - - 0 1')
        except ValueError as error:
            raise ImageImportError(str(error)) from error
        self.cells = {square: position.pieces.get(square) for square in SQUARES}
        self.confidence = {}

    def rotate_assignments(self):
        def opposite(square):
            return 'hgfedcba'['abcdefgh'.index(square[0])] + str(9 - int(square[1]))
        self.cells = {opposite(square): piece for square, piece in self.cells.items()}
        self.confidence = {opposite(square): value for square, value in self.confidence.items()}

    def preview(self):
        # Unknowns are drawn separately by the editor, not accepted as empty.
        return PositionSnapshot(placement_of(self.cells) + ' w - - 0 1')

    def position(self, metadata, *, reviewed=False):
        if self.unknown_squares:
            raise ImageImportError(f'Resolve all {len(self.unknown_squares)} unknown squares first')
        if metadata.turn not in ('w', 'b'):
            raise ImageImportError('Choose whose turn it is')
        if not reviewed:
            raise ImageImportError('Review the pieces and all position details, then tick the confirmation')
        if type(metadata.halfmove_clock) is not int or not 0 <= metadata.halfmove_clock <= 9999:
            raise ImageImportError('Halfmove clock must be 0..9999')
        if type(metadata.fullmove_number) is not int or not 1 <= metadata.fullmove_number <= 9999:
            raise ImageImportError('Fullmove number must be 1..9999')
        # Models check FEN syntax; the C referee is the authority on legality.
        fen = (f'{placement_of(self.cells)} {metadata.turn} {metadata.castling} '
               f'{metadata.en_passant} {metadata.halfmove_clock} {metadata.fullmove_number}')
        try:
            return PositionSnapshot(fen)
        except ValueError as error:
            raise ImageImportError(str(error)) from error
