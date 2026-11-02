"""Anarchy Chess game engine.
The engine stores one canonical 10x10 board per match.
Piece encoding:
    0  = empty
    Positive values = White pieces
    Negative values = Black pieces
Movement generation is delegated to go_where.py. This module validates
and executes moves, handles special-move effects, tracks en passant,
and records the move history.
"""
from typing import Dict, List, Optional, Tuple
from constants import *
from go_where import *
Position = Tuple[int, int]
_games: Dict[str, dict] = {}
# Overlay colours: red for the active side's own (movable) moves, blue for
# opponent moves shown purely as a cosmetic reference.
MOVABLE_COLOUR = "#e53935"
OPPOSING_COLOUR = "#1e88e5"
class MovementCache:
    """Cache movement-generation results for one match."""
    def __init__(self):
        self._board_snapshot = None
        self._en_passant_position = None
        self._current_side_is_white = None
        self._movements = None
    def get(
        self,
        board: List[List[int]],
        en_passant_pawn_position: Optional[Position],
        current_side_is_white: bool,
    ):
        """Return cached movements or recompute them if inputs changed."""
        # Snapshot the board so in-place mutations can be detected.
        board_snapshot = tuple(tuple(row) for row in board)
        en_passant_snapshot = (
            tuple(en_passant_pawn_position)
            if en_passant_pawn_position is not None
            else None
        )
        # Reuse the cached results if all inputs are unchanged.
        if (
            self._movements is not None
            and self._board_snapshot == board_snapshot
            and self._en_passant_position == en_passant_snapshot
            and self._current_side_is_white == current_side_is_white
        ):
            return self._movements
            # Inputs changed: calculate movements for the entire board.
        movements = show_all_movements(
            board,
            en_passant_pawn_position=en_passant_pawn_position,
            current_side_is_white=current_side_is_white,
        )
        self._board_snapshot = board_snapshot
        self._en_passant_position = en_passant_snapshot
        self._current_side_is_white = current_side_is_white
        self._movements = movements
        return self._movements
    def invalidate(self) -> None:
        """Discard the cached results."""
        self._board_snapshot = None
        self._en_passant_position = None
        self._current_side_is_white = None
        self._movements = None
        # ---------------------------------------------------------------------------
        # Piece names
        # ---------------------------------------------------------------------------
PIECE_NAMES = {
    KING: "King",
    QUEEN: "Queen",
    BISHOP: "Bishop",
    ROOK: "Rook",
    HORSE: "Horse",
    CHECKER: "Checker",
    KNOOK: "Knook",
    PAWN: "Pawn",
    STERILE_PAWN: "Sterile Pawn",
    UNDERAGE_PAWN: "Underage Pawn",
    ANTIQUEEN: "Antiqueen",
    TRAITORROOK: "Traitor Rook",
}
def _piece_name(piece: int) -> str:
    """Return a readable name for a piece code."""
    return PIECE_NAMES.get(abs(piece), f"Unknown Piece ({abs(piece)})")
    # ---------------------------------------------------------------------------
    # Position validation
    # ---------------------------------------------------------------------------
def _normalize_position(position) -> Optional[Position]:
    """Validate and normalize a board position."""
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        return None
    row, col = position
    if type(row) is not int or type(col) is not int:
        return None
    if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE):
        return None
    return row, col
def _normalize_capture_positions(
    captured_positions,
    source: Position,
) -> Optional[List[Position]]:
    """Validate and deduplicate captured positions.
    Returns None if any capture position is invalid or attempts to capture
    the moving piece's source square.
    """
    normalized_positions: List[Position] = []
    for position in captured_positions:
        normalized = _normalize_position(position)
        if normalized is None:
            return None
        if normalized == source:
            return None
        if normalized not in normalized_positions:
            normalized_positions.append(normalized)
    return normalized_positions
    # ---------------------------------------------------------------------------
    # Initial board creation
    # ---------------------------------------------------------------------------
def _create_initial_board() -> List[List[int]]:
    """Create a board using the specified default configuration."""
    board = [[EMPTY for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    # Black back rank: row 0.
    black_back_rank = [
        ROOK,
        ANTIQUEEN,
        CHECKER,
        BISHOP,
        KING,
        QUEEN,
        BISHOP,
        KNOOK,
        HORSE,
        ROOK,
    ]
    # Black pawn rank: row 1.
    black_pawn_rank = [
        PAWN,
        PAWN,
        PAWN,
        UNDERAGE_PAWN,
        PAWN,
        PAWN,
        UNDERAGE_PAWN,
        PAWN,
        PAWN,
        PAWN,
    ]
    # White pawn rank: row 8.
    white_pawn_rank = [
        PAWN,
        PAWN,
        PAWN,
        UNDERAGE_PAWN,
        PAWN,
        PAWN,
        UNDERAGE_PAWN,
        PAWN,
        PAWN,
        PAWN,
    ]
    # White back rank: row 9.
    white_back_rank = [
        ROOK,
        HORSE,
        KNOOK,
        BISHOP,
        QUEEN,
        KING,
        BISHOP,
        CHECKER,
        ANTIQUEEN,
        ROOK,
    ]
    # Black pieces have negative codes.
    board[0] = [-piece for piece in black_back_rank]
    board[1] = [-piece for piece in black_pawn_rank]
    # White pieces have positive codes.
    board[BOARD_SIZE - 2] = white_pawn_rank[:]
    board[BOARD_SIZE - 1] = white_back_rank[:]
    # Independent Traitor Rooks.
    board[3][0] = TRAITORROOK
    board[6][9] = -TRAITORROOK
    return board
    # ---------------------------------------------------------------------------
    # Game lifecycle
    # ---------------------------------------------------------------------------
def create_game(
    match_id: str,
    player_a_id: str,
    player_b_id: str,
) -> List[List[int]]:
    """Create a new game with the default board configuration."""
    if not match_id or not player_a_id or not player_b_id:
        raise ValueError("match_id and both player IDs are required")
    if player_a_id == player_b_id:
        raise ValueError("A game requires two different players")
    board = _create_initial_board()
    _games[match_id] = {
        "board": board,
        "player_a_id": player_a_id,
        "player_b_id": player_b_id,
        # Final square of the pawn that last advanced two or three squares.
        # None means the previous move did not enable en passant.
        "en_passant_pawn_position": None,
        # Independent movement cache for this match.
        "movement_cache": MovementCache(),
        # Second cache holding the opposite side's moves, used only for the
        # cosmetic opponent-movement overlay (never for move execution).
        "opponent_movement_cache": MovementCache(),
        # History contains successful moves only.
        "history": [],
    }
    return [row[:] for row in board]
def remove_game(match_id: str) -> None:
    """Remove all engine state belonging to a match."""
    _games.pop(match_id, None)
def _get_game(match_id: str) -> dict:
    """Retrieve a game or raise an error if it does not exist."""
    try:
        return _games[match_id]
    except KeyError as exc:
        raise KeyError(f"Unknown match ID: {match_id}") from exc
        # ---------------------------------------------------------------------------
        # Board state and history
        # ---------------------------------------------------------------------------
def show_state(match_id: str) -> List[List[int]]:
    """Return a copy of the canonical board."""
    game = _get_game(match_id)
    return [row[:] for row in game["board"]]
def get_game_result(match_id: str) -> Optional[str]:
    """Return DRAW, WHITE WINS, BLACK WINS, or None."""
    board = _get_game(match_id)["board"]
    white_kings = []
    black_kings = []
    for r, row in enumerate(board):
        for c, piece in enumerate(row):
            if piece == KING:
                white_kings.append((r, c))
            elif piece == -KING:
                black_kings.append((r, c))
                # King elimination takes priority over adjacency.
    if not white_kings and not black_kings:
        return "DRAW"
    if not white_kings:
        return "BLACK WINS"
    if not black_kings:
        return "WHITE WINS"
        # Any opposing Kings touching horizontally, vertically, or diagonally.
    for wr, wc in white_kings:
        for br, bc in black_kings:
            if max(abs(wr - br), abs(wc - bc)) == 1:
                return "DRAW"
    return None
def get_history(match_id: str) -> List[str]:
    """Return a copy of the match history."""
    return _get_game(match_id)["history"][:]


def snapshot_game_state(match_id: str) -> dict:
    """Return a restorable snapshot of all mutable rule state for a match.

    The movement cache is intentionally excluded because it can be rebuilt
    from the board and en-passant state after restoration.
    """
    game = _get_game(match_id)
    en_passant_position = game.get("en_passant_pawn_position")
    return {
        "board": [row[:] for row in game["board"]],
        "en_passant_pawn_position": (
            tuple(en_passant_position) if en_passant_position is not None else None
        ),
        "history": list(game["history"]),
    }


def restore_game_state(match_id: str, snapshot: dict) -> bool:
    """Restore a snapshot created by :func:`snapshot_game_state`.

    Returns False without changing the game if the supplied snapshot is invalid.
    """
    if not isinstance(snapshot, dict):
        return False
    board = snapshot.get("board")
    history = snapshot.get("history")
    en_passant = snapshot.get("en_passant_pawn_position")
    if (
        not isinstance(board, list)
        or len(board) != BOARD_SIZE
        or any(
            not isinstance(row, list)
            or len(row) != BOARD_SIZE
            or any(type(piece) is not int for piece in row)
            for row in board
        )
        or not isinstance(history, list)
        or any(not isinstance(entry, str) for entry in history)
    ):
        return False
    normalized_en_passant = None
    if en_passant is not None:
        normalized = _normalize_position(en_passant)
        if normalized is None:
            return False
        normalized_en_passant = normalized
    game = _get_game(match_id)
    game["board"] = [row[:] for row in board]
    game["en_passant_pawn_position"] = normalized_en_passant
    game["history"] = list(history)
    game["movement_cache"] = MovementCache()
    game["opponent_movement_cache"] = MovementCache()
    return True
    # ---------------------------------------------------------------------------
    # Movement generation
    # ---------------------------------------------------------------------------
def _generate_moves_for_side(
    match_id: str,
    position,
    side_is_white: bool,
    cache: MovementCache,
):
    """Generate available moves for one side using the given movement cache.
    Each move has the form:
        (
            (destination_row, destination_col),
            [(captured_row, captured_col), ...]
        )
    """
    game = _get_game(match_id)
    source = _normalize_position(position)
    if source is None:
        return []
    board = game["board"]
    row, col = source
    # Reject positions outside the board.
    if not (0 <= row < len(board) and 0 <= col < len(board[row])):
        return []
    piece = board[row][col]
    if piece == EMPTY:
        return []
    # Ordinary pieces must belong to the side being queried.
    # Traitor Rooks use their special control rules in go_where.py.
    if abs(piece) != TRAITORROOK:
        if side_is_white and piece < 0:
            return []
        if not side_is_white and piece > 0:
            return []
    # Retrieve or calculate the movement cache for this match.
    all_movements = cache.get(
        board,
        en_passant_pawn_position=game["en_passant_pawn_position"],
        current_side_is_white=side_is_white,
    )
    result = all_movements[row][col]
    if result is None:
        return []
    moves, _forced = result
    return moves

def _generate_moves(
    match_id: str,
    position,
    player_colour: str,
):
    """Generate the active side's available moves (used by do_movement)."""
    if player_colour not in ("white", "black"):
        return []
    game = _get_game(match_id)
    return _generate_moves_for_side(
        match_id,
        position,
        side_is_white=player_colour == "white",
        cache=game["movement_cache"],
    )

def _opponent_moves(
    match_id: str,
    position,
    active_player_colour: str,
):
    """Generate the opposite side's available moves (display only)."""
    if active_player_colour not in ("white", "black"):
        return []
    game = _get_game(match_id)
    return _generate_moves_for_side(
        match_id,
        position,
        side_is_white=active_player_colour == "black",
        cache=game["opponent_movement_cache"],
    )
def _build_overlay(
    moves,
    board: List[List[int]],
    colour: str,
) -> Dict[str, List[List[int]]]:
    """Build the square/dot overlay for a list of moves in one colour."""
    result = {
        "square": {},
        "dot": {},
    }
    square_positions = []
    dot_positions = []
    for destination, captured_positions in moves:
        row, col = destination
        destination_square = [row, col]
        # Captures use a solid square, even when the destination is empty.
        # This is needed for En Passant and other special captures.
        if captured_positions or board[row][col] != EMPTY:
            if destination_square not in square_positions:
                square_positions.append(destination_square)
        else:
            if destination_square not in dot_positions:
                dot_positions.append(destination_square)
    if square_positions:
        result["square"][colour] = square_positions
    if dot_positions:
        result["dot"][colour] = dot_positions
    return result

def show_movement(
    match_id: str,
    position,
    player_colour: str,
) -> Dict[str, Dict[str, List[List[int]]]]:
    """Return movement overlays in the format expected by main.py.
    A destination with a capture is shown as a square.
    A destination without a capture is shown as a dot.
    The active side's own moves use MOVABLE_COLOUR (red). When the selected
    piece belongs to the opponent, its moves are shown in OPPOSING_COLOUR
    (blue) purely for display and cannot be used to move.
    The frontend overlay format is:
        {
            "square": {"#e53935": [[row, col], ...]},
            "dot":    {"#e53935": [[row, col], ...]}
        }
    """
    result = {
        "square": {},
        "dot": {},
    }
    game = _get_game(match_id)
    board = game["board"]
    main_moves = _generate_moves(match_id, position, player_colour)
    if main_moves:
        overlay = _build_overlay(main_moves, board, MOVABLE_COLOUR)
    else:
        overlay = _build_overlay(
            _opponent_moves(match_id, position, player_colour),
            board,
            OPPOSING_COLOUR,
        )
    result["square"].update(overlay["square"])
    result["dot"].update(overlay["dot"])
    return result
    # ---------------------------------------------------------------------------
    # Queentum Tunnel
    # ---------------------------------------------------------------------------
def _handle_queentum_tunnel(
    board: List[List[int]],
    source: Position,
    target: Position,
    captured_positions: List[Position],
) -> bool:
    """Handle a Queen/Antiqueen Queentum Tunnel by swapping the pieces.
    Returns True if this was a valid Queentum Tunnel and it was executed.
    Returns False if the move is not a Queentum Tunnel.
    """
    source_row, source_col = source
    target_row, target_col = target
    moving_piece = board[source_row][source_col]
    target_piece = board[target_row][target_col]
    if moving_piece == EMPTY or target_piece == EMPTY:
        return False
        # Queentum Tunnel is a swap, not a capture.
    if captured_positions:
        return False
        # Queen can tunnel to its friendly Antiqueen.
    if abs(moving_piece) == QUEEN:
        if abs(target_piece) != ANTIQUEEN:
            return False
            # Antiqueen can tunnel to its friendly Queen.
    elif abs(moving_piece) == ANTIQUEEN:
        if abs(target_piece) != QUEEN:
            return False
    else:
        return False
        # The two pieces must belong to the same side.
    if (moving_piece > 0) != (target_piece > 0):
        return False
        # Swap their positions rather than overwrite the destination piece.
    board[source_row][source_col] = target_piece
    board[target_row][target_col] = moving_piece
    return True
    # ---------------------------------------------------------------------------
    # Castling
    # ---------------------------------------------------------------------------
def _is_castling_move(
    source: Position,
    target: Position,
    moving_piece: int,
) -> bool:
    """Determine whether the move coordinates describe a castling move."""
    if abs(moving_piece) != KING:
        return False
    if moving_piece > 0:
        # White King begins at (9, 5).
        king_start = (BOARD_SIZE - 1, 5)
    else:
        # Black King begins at (0, 4).
        king_start = (0, 4)
    if source != king_start:
        return False
        # Castling moves the King two columns along the same row.
    return target[0] == king_start[0] and abs(target[1] - king_start[1]) == 2
def _handle_castling(
    board: List[List[int]],
    source: Position,
    target: Position,
    captured_positions: List[Position],
) -> bool:
    """Execute castling by moving both the King and its Rook.
    Castling is only allowed when every square between them is empty, so it
    never captures pieces (captured_positions is always empty for castling).
    Returns True if castling succeeds, otherwise False.
    """
    source_row, source_col = source
    target_row, target_col = target
    king_piece = board[source_row][source_col]
    if not _is_castling_move(source, target, king_piece):
        return False
    direction = 1 if target_col > source_col else -1
    # The Rook is on the relevant end of the King’s starting row.
    rook_source = (
        source_row,
        0 if direction < 0 else BOARD_SIZE - 1,
    )
    # go_where.py places the Rook one square in the direction of castling.
    rook_target = (
        source_row,
        source_col + direction,
    )
    rook_source_row, rook_source_col = rook_source
    rook_target_row, rook_target_col = rook_target
    rook_piece = board[rook_source_row][rook_source_col]
    # Validate the Rook before changing any squares.
    if abs(rook_piece) != ROOK:
        return False
    # The castling Rook must belong to the same side as the King.
    if (rook_piece > 0) != (king_piece > 0):
        return False
    # Clear both starting squares.
    board[source_row][source_col] = EMPTY
    board[rook_source_row][rook_source_col] = EMPTY
    # Place the King and Rook on their castling destinations.
    board[target_row][target_col] = king_piece
    board[rook_target_row][rook_target_col] = rook_piece
    return True
    # ---------------------------------------------------------------------------
    # Il Vaticano
    # ---------------------------------------------------------------------------
def _handle_il_vaticano(
    board: List[List[int]],
    source: Position,
    target: Position,
    captured_positions: List[Position],
) -> bool:
    """Execute an Il Vaticano move generated by go_where.py.
    The two friendly Bishops swap positions and the two intermediate enemy
    pieces are captured.
    Returns True if this move was handled as Il Vaticano, otherwise False.
    """
    source_row, source_col = source
    target_row, target_col = target
    moving_piece = board[source_row][source_col]
    target_piece = board[target_row][target_col]
    if abs(moving_piece) != BISHOP:
        return False
    if abs(target_piece) != BISHOP:
        return False
        # Both Bishops must belong to the same side.
    if (moving_piece > 0) != (target_piece > 0):
        return False
        # The move generator identifies Il Vaticano by its two captures.
    if len(captured_positions) != 2:
        return False
        # Neither Bishop may be one of the captured pieces.
    if source in captured_positions or target in captured_positions:
        return False
        # Validate the pieces to be captured before modifying the board.
    for captured_row, captured_col in captured_positions:
        captured_piece = board[captured_row][captured_col]
        if captured_piece == EMPTY:
            return False
            # Both intermediate pieces must be enemies of the moving Bishop.
        if (captured_piece > 0) == (moving_piece > 0):
            return False
            # Capture the two intermediate pieces.
    for captured_row, captured_col in captured_positions:
        board[captured_row][captured_col] = EMPTY
        # Swap the Bishops. Do not overwrite the destination Bishop.
    board[source_row][source_col] = target_piece
    board[target_row][target_col] = moving_piece
    return True
    # ---------------------------------------------------------------------------
def _handle_queen_beta_decay(
    board: List[List[int]],
    source: Position,
    target: Position,
    captured_positions: List[Position],
) -> bool:
    """Replace a Queen with a forward Sterile Pawn, left Rook, and right Horse."""
    if source != target or captured_positions != [source]:
        return False
    row, col = source
    queen = board[row][col]
    if queen == EMPTY or abs(queen) != QUEEN:
        return False
    is_white = queen > 0
    forward_row = row - 1 if is_white else row + 1
    spawn_positions = (
        (forward_row, col),
        (row, col - 1),
        (row, col + 1),
    )
    # Validate every destination before changing the board.
    for spawn_row, spawn_col in spawn_positions:
        if not (0 <= spawn_row < BOARD_SIZE and 0 <= spawn_col < BOARD_SIZE):
            return False
        if board[spawn_row][spawn_col] != EMPTY:
            return False
    side = 1 if is_white else -1
    board[row][col] = EMPTY
    board[forward_row][col] = side * STERILE_PAWN
    board[row][col - 1] = side * ROOK
    board[row][col + 1] = side * HORSE
    return True
    # Execute movement
    # ---------------------------------------------------------------------------
def do_movement(
    match_id: str,
    source_position,
    target_position,
    player_colour: str,
) -> bool:
    """Validate and execute a move.
    Returns True on success and False if the move is invalid.
    """
    game = _get_game(match_id)
    if player_colour not in ("white", "black"):
        return False
    source = _normalize_position(source_position)
    target = _normalize_position(target_position)
    if source is None or target is None:
        return False
    board = game["board"]
    source_row, source_col = source
    moving_piece = board[source_row][source_col]
    if moving_piece == EMPTY:
        return False
        # Obtain available moves using the same generator as SHOW_MOVEMENT.
    moves = _generate_moves(
        match_id,
        source,
        player_colour,
    )
    # Find the move matching the requested destination.
    selected_move = None
    for destination, captured_positions in moves:
        if destination == target:
            selected_move = (destination, captured_positions)
            break
            # Do not alter the board if the destination is not legal.
    if selected_move is None:
        return False
    destination, raw_captured_positions = selected_move
    # Queen Beta Decay intentionally uses the Queen's own square as the
    # destination and capture marker, which the standard capture validator
    # otherwise rejects.
    queen_beta_decay_candidate = (
        source == target
        and abs(moving_piece) == QUEEN
        and raw_captured_positions == [source]
    )
    if queen_beta_decay_candidate:
        captured_positions = [source]
    else:
        captured_positions = _normalize_capture_positions(
            raw_captured_positions,
            source,
        )
        if captured_positions is None:
            return False
    target_row, target_col = destination
    # --------------------------------------------------------
    # Special move 1: Queentum Tunnel
    # --------------------------------------------------------
    queentum_handled = _handle_queentum_tunnel(
        board,
        source,
        destination,
        captured_positions,
    )
    # --------------------------------------------------------
    # Special move 2: Castling
    # --------------------------------------------------------
    castling_handled = False
    if not queentum_handled and _is_castling_move(
        source,
        destination,
        moving_piece,
    ):
        castling_handled = _handle_castling(
            board,
            source,
            destination,
            captured_positions,
        )
        # A failed castling move must not become an ordinary King move.
        if not castling_handled:
            return False
            # --------------------------------------------------------
            # Special move 3: Il Vaticano
            # --------------------------------------------------------
    il_vaticano_handled = False
    if not queentum_handled and not castling_handled:
        il_vaticano_handled = _handle_il_vaticano(
            board,
            source,
            destination,
            captured_positions,
        )
        # --------------------------------------------------------
        # Special move 4: Queen Beta Decay
        # --------------------------------------------------------
    queen_beta_decay_handled = False
    if not queentum_handled and not castling_handled and not il_vaticano_handled:
        queen_beta_decay_handled = _handle_queen_beta_decay(
            board,
            source,
            destination,
            captured_positions,
        )
    if source == target and not queen_beta_decay_handled:
        return False
    if queen_beta_decay_candidate and not queen_beta_decay_handled:
        return False
        # --------------------------------------------------------
        # Ordinary move and captures
        # --------------------------------------------------------
    if (
        not queentum_handled
        and not castling_handled
        and not il_vaticano_handled
        and not queen_beta_decay_handled
    ):
        # Prevent overwriting an occupied destination unless it is captured.
        if (
            board[target_row][target_col] != EMPTY
            and destination not in captured_positions
        ):
            return False
            # Apply captures.
        for captured_row, captured_col in captured_positions:
            board[captured_row][captured_col] = EMPTY
            # Move the piece while preserving its signed piece code.
        board[source_row][source_col] = EMPTY
        board[target_row][target_col] = moving_piece
        # --------------------------------------------------------
        # Update en passant state
        # --------------------------------------------------------
    row_distance = abs(target_row - source_row)
    if (
        abs(moving_piece)
        in (
            PAWN,
            STERILE_PAWN,
            UNDERAGE_PAWN,
        )
        and row_distance in (2, 3)
        and not captured_positions
    ):
        game["en_passant_pawn_position"] = destination
    else:
        game["en_passant_pawn_position"] = None
        # --------------------------------------------------------
        # Invalidate this match's movement caches
        # --------------------------------------------------------
    game["movement_cache"].invalidate()
    game["opponent_movement_cache"].invalidate()
    # Record one concise history entry.
    if queen_beta_decay_handled:
        game["history"].append(f"Queen Beta Decay at {source}")
    else:
        game["history"].append(
            f"{_piece_name(moving_piece)} - {source} to {destination}"
        )
        # Precompute movements for the next player.
    next_player_is_white = player_colour == "black"
    game["movement_cache"].get(
        board,
        en_passant_pawn_position=game["en_passant_pawn_position"],
        current_side_is_white=next_player_is_white,
    )
    return True
def promote_piece(match_id, position, promoted_piece):
    """Replace a piece on the board with its selected promotion."""
    game = _get_game(match_id)
    target = _normalize_position(position)
    if target is None:
        return False
    if type(promoted_piece) is not int or promoted_piece == 0:
        return False
    row, col = target
    board = game["board"]
    current_piece = board[row][col]
    # There must be a piece on the promotion square.
    if current_piece == 0:
        return False
        # Promotion must preserve the piece's colour.
    if (current_piece > 0) != (promoted_piece > 0):
        return False
        # Replace the original piece with the chosen piece.
    board[row][col] = promoted_piece
    # Clear or invalidate cached movement options.
    for cache_key in ("movement_cache", "opponent_movement_cache"):
        movement_cache = game.get(cache_key)
        if movement_cache is not None:
            if hasattr(movement_cache, "invalidate"):
                movement_cache.invalidate()
            elif hasattr(movement_cache, "clear"):
                movement_cache.clear()
            # Record the promotion in the game history.
    game.setdefault("history", []).append(
        f"Piece {current_piece} promoted to {promoted_piece} " f"at ({row}, {col})."
    )
    return True
