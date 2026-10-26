"""Move generation for Anarchy Chess.
Public movement functions return ``(moves, forced)``. ``moves`` is a list of
Move pairs, with each Move having this shape:
    ((destination_row, destination_col), [(captured_row, captured_col), ...])
The capture list contains board positions, not piece codes. The Boolean
``forced`` is True when a mandatory rule filters the options (Forced En Passant
or a Bishop's mandatory Underage Pawn capture).
A move may capture friendly pieces when a custom rule explicitly says so
(currently bouncing Bishops capturing Underage Pawns and castling over a friendly
Bishop). This module generates candidate moves only. It does not mutate the
board or perform action effects such as swapping Queentum pieces, moving a
castling rook, triggering Knooklear Fusion, ending the game, or promotion.
"""

from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
from constants import *  # noqa: F401,F403 - piece codes and BOARD_SIZE are project constants

Position = Tuple[int, int]
CaptureList = List[Position]
Move = Tuple[Position, CaptureList]
Board = List[List[int]]
MoveList = List[Move]
# Public move-generation functions return (moves, forced).
MovementResult = Tuple[MoveList, bool]
ORTHOGONAL_DIRS: Tuple[Position, ...] = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIAGONAL_DIRS: Tuple[Position, ...] = ((-1, -1), (-1, 1), (1, -1), (1, 1))
HORSE_OFFSETS: Tuple[Position, ...] = (
    (-2, -1),
    (-2, 1),
    (-1, -2),
    (-1, 2),
    (1, -2),
    (1, 2),
    (2, -1),
    (2, 1),
)
PAWN_TYPES = {PAWN, STERILE_PAWN, UNDERAGE_PAWN}

# ---------------------------------------------------------------------------
# Internal helpers

# ---------------------------------------------------------------------------


def _in_bounds(row: int, col: int) -> bool:
    return 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE


def _valid_position(position: object) -> Optional[Position]:
    """Return a normalized board coordinate, or None if it is invalid."""
    if not isinstance(position, (tuple, list)) or len(position) != 2:
        return None
    row, col = position
    if isinstance(row, bool) or isinstance(col, bool):
        return None
    if not isinstance(row, int) or not isinstance(col, int):
        return None
    if not _in_bounds(row, col):
        return None
    return row, col


def _board_is_valid(board: Board) -> bool:
    return (
        isinstance(board, list)
        and len(board) == BOARD_SIZE
        and all(isinstance(row, list) and len(row) == BOARD_SIZE for row in board)
    )


def _is_enemy(value: int, mover_is_white: bool) -> bool:
    return value < 0 if mover_is_white else value > 0


def _is_friendly(value: int, mover_is_white: bool) -> bool:
    return value > 0 if mover_is_white else value < 0


def _can_land(target_value: int, mover_is_white: bool) -> bool:
    """Normal pieces may land on empty or enemy-occupied squares."""
    return target_value == EMPTY or _is_enemy(target_value, mover_is_white)


def _mover_is_white(
    position: Position, board: Board, piece_type: int
) -> Optional[bool]:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return None
    value = board[pos[0]][pos[1]]
    if value == EMPTY or abs(value) != piece_type:
        return None
    return value > 0


def _deduplicate_positions(positions: Iterable[Position]) -> List[Position]:
    seen: Set[Position] = set()
    result: List[Position] = []
    for position in positions:
        if position not in seen:
            seen.add(position)
            result.append(position)
    return result


def _deduplicate_moves(moves: Iterable[Move]) -> MoveList:
    """Deduplicate identical destination/capture combinations, preserving order."""
    seen: Set[Tuple[Position, Tuple[Position, ...]]] = set()
    result: MoveList = []
    for destination, captures in moves:
        normalized_captures = _deduplicate_positions(captures)
        key = (destination, tuple(normalized_captures))
        if key not in seen:
            seen.add(key)
            result.append((destination, normalized_captures))
    return result


def _move_to(position: Position, board: Board, mover_is_white: bool) -> Move:
    """Make a normal move, marking an enemy piece on the destination for capture."""
    value = board[position[0]][position[1]]
    captures = [position] if value != EMPTY and _is_enemy(value, mover_is_white) else []
    return position, captures


def _moves_from_positions(
    positions: Iterable[Position], board: Board, mover_is_white: bool
) -> MoveList:
    return [_move_to(position, board, mover_is_white) for position in positions]


def _sliding_moves(
    row: int,
    col: int,
    directions: Tuple[Position, ...],
    board: Board,
    mover_is_white: bool,
) -> MoveList:
    """Sliding movement; the first occupied square stops each ray."""
    moves: MoveList = []
    for dr, dc in directions:
        nr, nc = row + dr, col + dc
        while _in_bounds(nr, nc):
            value = board[nr][nc]
            if value == EMPTY:
                moves.append(((nr, nc), []))
            else:
                if _can_land(value, mover_is_white):
                    moves.append(_move_to((nr, nc), board, mover_is_white))
                break
            nr += dr
            nc += dc
    return moves


def _horse_moves(row: int, col: int, board: Board, mover_is_white: bool) -> MoveList:
    moves: MoveList = []
    for dr, dc in HORSE_OFFSETS:
        nr, nc = row + dr, col + dc
        if _in_bounds(nr, nc) and _can_land(board[nr][nc], mover_is_white):
            moves.append(_move_to((nr, nc), board, mover_is_white))
    return moves


def _rook_two_moves(row: int, col: int, board: Board, mover_is_white: bool) -> MoveList:
    """Rook-like movement limited to two squares, without jumping."""
    moves: MoveList = []
    for dr, dc in ORTHOGONAL_DIRS:
        for distance in (1, 2):
            nr, nc = row + dr * distance, col + dc * distance
            if not _in_bounds(nr, nc):
                break
            value = board[nr][nc]
            if value == EMPTY:
                moves.append(((nr, nc), []))
                continue
            if _can_land(value, mover_is_white):
                moves.append(_move_to((nr, nc), board, mover_is_white))
            break
    return moves


def _find_friendly_pieces(
    board: Board, piece_type: int, mover_is_white: bool
) -> List[Position]:
    return [
        (r, c)
        for r in range(BOARD_SIZE)
        for c in range(BOARD_SIZE)
        if abs(board[r][c]) == piece_type and (board[r][c] > 0) == mover_is_white
    ]


def _value_after_captures(
    board: Board, position: Position, captures: FrozenSet[Position]
) -> int:
    """Treat pieces captured earlier in a simulated chain as having been removed."""
    if position in captures:
        return EMPTY
    return board[position[0]][position[1]]


# ---------------------------------------------------------------------------
# Bouncing Bishop

# ---------------------------------------------------------------------------


def _bouncing_bishop_moves(
    row: int, col: int, board: Board, mover_is_white: bool
) -> MoveList:
    """Trace each reflected diagonal ray until it returns or hits a piece."""
    start = (row, col)
    moves: MoveList = []
    for initial_dr, initial_dc in DIAGONAL_DIRS:
        r, c = row, col
        dr, dc = initial_dr, initial_dc
        seen_states: Set[Tuple[int, int, int, int]] = set()
        while True:
            state = (r, c, dr, dc)
            if state in seen_states:
                break
            seen_states.add(state)
            nr, nc = r + dr, c + dc
            if not _in_bounds(nr, nc):
                if nr < 0 or nr >= BOARD_SIZE:
                    dr = -dr
                if nc < 0 or nc >= BOARD_SIZE:
                    dc = -dc
                nr, nc = r + dr, c + dc
                if not _in_bounds(nr, nc):
                    break
            if (nr, nc) == start:
                break
            value = board[nr][nc]
            if value == EMPTY:
                moves.append(((nr, nc), []))
                r, c = nr, nc
                continue
            # Bishop must capture an Underage Pawn even if it is friendly.
            if abs(value) == UNDERAGE_PAWN:
                moves.append(((nr, nc), [(nr, nc)]))
            elif _is_enemy(value, mover_is_white):
                moves.append(((nr, nc), [(nr, nc)]))
            break
    return _deduplicate_moves(moves)


def _forced_underage_capture_moves(
    moves: Iterable[Move], board: Board
) -> MovementResult:
    """Keep only Bishop moves that land on an Underage Pawn, when any exist."""
    unique_moves = _deduplicate_moves(moves)
    forced_moves = [
        move
        for move in unique_moves
        if abs(board[move[0][0]][move[0][1]]) == UNDERAGE_PAWN
    ]
    if forced_moves:
        return forced_moves, True
    return unique_moves, False


# ---------------------------------------------------------------------------
# Checker

# ---------------------------------------------------------------------------


def _checker_simple_moves(
    row: int, col: int, board: Board, mover_is_white: bool
) -> MoveList:
    """Generate Checker's unobstructed one- and two-square diagonal moves.

    Ordinary diagonal moves only land on empty squares. A two-square move is
    allowed as a normal move only when the intervening square is empty. If a
    piece occupies that intervening square, the destination is handled by the
    hop rules instead.
    """
    moves: MoveList = []
    for dr, dc in DIAGONAL_DIRS:
        # One-square diagonal step.
        nr, nc = row + dr, col + dc
        if _in_bounds(nr, nc) and board[nr][nc] == EMPTY:
            moves.append(((nr, nc), []))

        # Two-square diagonal move over an empty intermediate square.
        middle = (row + dr, col + dc)
        destination = (row + 2 * dr, col + 2 * dc)
        if (
            _in_bounds(*middle)
            and _in_bounds(*destination)
            and board[middle[0]][middle[1]] == EMPTY
            and board[destination[0]][destination[1]] == EMPTY
        ):
            moves.append((destination, []))

    return _deduplicate_moves(moves)


def _checker_hops(row: int, col: int, board: Board, mover_is_white: bool) -> MoveList:
    """Generate enemy-capturing jumps and allow one non-capturing friendly hop.

    A Checker can jump a consecutive run of enemies, capturing every enemy in
    that run, and can chain enemy jumps. It may also jump over one friendly
    piece during a move; that friendly piece is not captured. Friendly pieces
    cannot be jumped more than once in the same move, and a friendly hop cannot
    pass through a run of pieces. Every hop must land on an empty, on-board
    square immediately beyond the jumped piece or enemy run.
    """
    start = (row, col)
    results: MoveList = []
    explored: Set[
        Tuple[Position, FrozenSet[Position], Tuple[Position, ...], bool]
    ] = set()

    def simulated_value(position: Position, captured: FrozenSet[Position]) -> int:
        # The Checker vacates its original square, and captured enemies are
        # treated as removed for the remainder of the chain.
        if position == start or position in captured:
            return EMPTY
        return board[position[0]][position[1]]

    def explore(
        current: Position,
        considered: FrozenSet[Position],
        capture_history: Tuple[Position, ...],
        friendly_jump_used: bool,
    ) -> None:
        state = (current, considered, capture_history, friendly_jump_used)
        if state in explored:
            return
        explored.add(state)
        captured_set = frozenset(capture_history)

        for dr, dc in DIAGONAL_DIRS:
            first = (current[0] + dr, current[1] + dc)
            if not _in_bounds(*first):
                continue

            first_value = simulated_value(first, captured_set)
            if first_value == EMPTY:
                # Empty squares are handled by ordinary movement, not as hops.
                continue

            if _is_friendly(first_value, mover_is_white):
                # Allow exactly one friendly-piece hop in the entire move.
                if friendly_jump_used:
                    continue
                landing = (first[0] + dr, first[1] + dc)
                if not _in_bounds(*landing):
                    continue
                if landing == start or simulated_value(landing, captured_set) != EMPTY:
                    continue

                # The friendly piece is deliberately not added to captures.
                results.append((landing, list(capture_history)))
                explore(
                    landing,
                    considered,
                    capture_history,
                    True,
                )
                continue

            # Jump over a consecutive run of enemies. Stop if a friendly piece
            # or an enemy already considered in this chain blocks the direction.
            probe = first
            jumped_enemies: List[Position] = []
            while _in_bounds(*probe):
                value = simulated_value(probe, captured_set)
                if value == EMPTY:
                    break
                if _is_friendly(value, mover_is_white) or probe in considered:
                    jumped_enemies = []
                    break
                jumped_enemies.append(probe)
                probe = (probe[0] + dr, probe[1] + dc)

            # The landing square immediately after the enemy run must exist
            # and be empty. Do not permit an off-board or occupied landing.
            if not jumped_enemies or not _in_bounds(*probe):
                continue
            if probe == start or simulated_value(probe, captured_set) != EMPTY:
                continue

            new_captures = tuple(
                square for square in jumped_enemies if square not in captured_set
            )
            next_capture_history = capture_history + new_captures
            next_considered = considered | frozenset(jumped_enemies)
            results.append((probe, list(next_capture_history)))
            explore(
                probe,
                next_considered,
                next_capture_history,
                friendly_jump_used,
            )

    explore(start, frozenset(), (), False)
    return _deduplicate_moves(results)


# ---------------------------------------------------------------------------
# Traitor Rook and special-move destinations

# ---------------------------------------------------------------------------


def _traitorrook_controllers(row: int, col: int, board: Board) -> Tuple[bool, bool]:
    """Return (white_controls, black_controls); ties allow both sides."""
    white_count = black_count = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if not _in_bounds(nr, nc):
                continue
            value = board[nr][nc]
            if value == EMPTY or abs(value) == TRAITORROOK:
                continue
            if value > 0:
                white_count += 1
            else:
                black_count += 1
    return white_count > black_count, black_count > white_count


def _castling_moves(row: int, col: int, board: Board, mover_is_white: bool) -> MoveList:
    """Return king destinations and friendly Bishops captured on landing squares."""
    if mover_is_white:
        king_start = (BOARD_SIZE - 1, 5)
        rook_starts = [(BOARD_SIZE - 1, 0), (BOARD_SIZE - 1, BOARD_SIZE - 1)]
    else:
        king_start = (0, 4)
        rook_starts = [(0, 0), (0, BOARD_SIZE - 1)]
    if (row, col) != king_start:
        return []
    king_value = board[row][col]
    if abs(king_value) != KING or (king_value > 0) != mover_is_white:
        return []

    def landing_allowed(value: int) -> bool:
        return value == EMPTY or (
            abs(value) == BISHOP and (value > 0) == mover_is_white
        )

    moves: MoveList = []
    for rook_row, rook_col in rook_starts:
        rook_value = board[rook_row][rook_col]
        if abs(rook_value) != ROOK or (rook_value > 0) != mover_is_white:
            continue
        direction = -1 if rook_col < col else 1
        king_dest = (row, col + 2 * direction)
        rook_dest = (row, col + direction)
        if not _in_bounds(*king_dest) or not _in_bounds(*rook_dest):
            continue
        if not landing_allowed(board[king_dest[0]][king_dest[1]]):
            continue
        if not landing_allowed(board[rook_dest[0]][rook_dest[1]]):
            continue
        low, high = sorted((col, rook_col))
        clear = True
        for path_col in range(low + 1, high):
            value = board[row][path_col]
            if value == EMPTY:
                continue
            path_pos = (row, path_col)
            if path_pos in (king_dest, rook_dest) and landing_allowed(value):
                continue
            clear = False
            break
        if clear:
            captures = [
                square
                for square in (king_dest, rook_dest)
                if abs(board[square[0]][square[1]]) == BISHOP
                and (board[square[0]][square[1]] > 0) == mover_is_white
            ]
            moves.append((king_dest, captures))
    return _deduplicate_moves(moves)


def knooklear_fusion_moves(position: Position, board: Board) -> MoveList:
    """Return Knooklear Fusion moves available to a Rook or Horse.
    Fusion is available when a Rook can slide unobstructed onto a friendly
    Horse, or a Horse can make a knight move onto a friendly Rook. Each move's
    capture list contains occupied squares in the destination-centered 3x3
    blast area. The moving piece's origin is excluded because it vacates before
    the explosion; the destination is included to remove the other fusion piece.
    The resulting Knook placement is an action effect and is handled outside
    this move-generation module.
    """
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return []
    row, col = pos
    piece_value = board[row][col]
    piece_type = abs(piece_value)
    if piece_value == EMPTY or piece_type not in (ROOK, HORSE):
        return []
    mover_is_white = piece_value > 0
    target_type = HORSE if piece_type == ROOK else ROOK
    moves: MoveList = []
    for target_row in range(BOARD_SIZE):
        for target_col in range(BOARD_SIZE):
            target_value = board[target_row][target_col]
            # Fusion requires a friendly piece of the other type.
            if abs(target_value) != target_type:
                continue
            if (target_value > 0) != mover_is_white:
                continue
            target = (target_row, target_col)
            dr = target_row - row
            dc = target_col - col
            if piece_type == ROOK:
                # A Rook must reach the Horse along an unobstructed rank/file.
                if dr != 0 and dc != 0:
                    continue
                step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
                step_c = 0 if dc == 0 else (1 if dc > 0 else -1)
                check_r, check_c = row + step_r, col + step_c
                path_clear = True
                while (check_r, check_c) != target:
                    if board[check_r][check_c] != EMPTY:
                        path_clear = False
                        break
                    check_r += step_r
                    check_c += step_c
                if not path_clear:
                    continue
            else:
                # A Horse must reach the Rook using knight movement.
                if (dr, dc) not in HORSE_OFFSETS:
                    continue
            # Capture every occupied square in the destination-centered 3x3.
            # The moving piece's origin is excluded because it vacates.
            captures: CaptureList = []
            for blast_row in range(
                max(0, target_row - 1),
                min(BOARD_SIZE, target_row + 2),
            ):
                for blast_col in range(
                    max(0, target_col - 1),
                    min(BOARD_SIZE, target_col + 2),
                ):
                    blast_position = (blast_row, blast_col)
                    if blast_position == pos:
                        continue
                    if board[blast_row][blast_col] != EMPTY:
                        captures.append(blast_position)
            moves.append((target, captures))
    return _deduplicate_moves(moves)


def queen_beta_decay_moves(position: Position, board: Board) -> MoveList:
    """Return the Queen Beta Decay self-square move when all spawn squares are empty.
    White spawns a Sterile Pawn one row forward (up); Black's forward direction
    is down. The move's destination and capture marker are both the Queen's
    square, which engine.py recognizes as this special transformation.
    """
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return []
    row, col = pos
    queen = board[row][col]
    if queen == EMPTY or abs(queen) != QUEEN:
        return []
    is_white = queen > 0
    forward_row = row - 1 if is_white else row + 1
    spawn_positions = (
        (forward_row, col),  # Sterile Pawn in front
        (row, col - 1),  # Rook to the left
        (row, col + 1),  # Horse to the right
    )
    if not all(
        _in_bounds(*spawn_pos) and board[spawn_pos[0]][spawn_pos[1]] == EMPTY
        for spawn_pos in spawn_positions
    ):
        return []
    # Preserve the Queen's own square as the final destination/capture marker.
    return [(pos, [pos])]


def _queentum_tunnel_moves(
    row: int, col: int, board: Board, mover_is_white: bool
) -> MoveList:
    """Return the friendly Queen/Antiqueen counterpart as a swap destination."""
    value = board[row][col]
    if abs(value) == QUEEN:
        other_type = ANTIQUEEN
    elif abs(value) == ANTIQUEEN:
        other_type = QUEEN
    else:
        return []
    return [
        ((r, c), [])
        for r in range(BOARD_SIZE)
        for c in range(BOARD_SIZE)
        if (r, c) != (row, col)
        and abs(board[r][c]) == other_type
        and (board[r][c] > 0) == mover_is_white
    ]


def _il_vaticano_moves(
    row: int, col: int, board: Board, mover_is_white: bool
) -> MoveList:
    """Capture two enemy pieces between friendly Bishops.
    The other friendly Bishop must be exactly three squares away in a
    straight line: horizontal, vertical, or diagonal. Both intervening
    squares must contain enemy pieces.
    The move lands on the other Bishop's square and captures the two
    intervening enemy pieces.
    """
    moves: MoveList = []
    directions = ORTHOGONAL_DIRS + DIAGONAL_DIRS
    for dr, dc in directions:
        first_between = (row + dr, col + dc)
        second_between = (row + 2 * dr, col + 2 * dc)
        destination = (row + 3 * dr, col + 3 * dc)
        # The destination Bishop must be on the board.
        if not _in_bounds(*destination):
            continue
        # Both intermediate positions must be on the board.
        if not _in_bounds(*first_between) or not _in_bounds(*second_between):
            continue
        target_value = board[destination[0]][destination[1]]
        # The destination must contain another friendly Bishop.
        if abs(target_value) != BISHOP:
            continue
        if (target_value > 0) != mover_is_white:
            continue
        first_value = board[first_between[0]][first_between[1]]
        second_value = board[second_between[0]][second_between[1]]
        # Both pieces between the Bishops must be enemies.
        if not _is_enemy(first_value, mover_is_white):
            continue
        if not _is_enemy(second_value, mover_is_white):
            continue
        moves.append((destination, [first_between, second_between]))
    return _deduplicate_moves(moves)


# ---------------------------------------------------------------------------
# Pawns and en passant

# ---------------------------------------------------------------------------


def _pawn_moves(row: int, col: int, board: Board, mover_is_white: bool) -> MoveList:
    step = -1 if mover_is_white else 1
    nr = row + step
    if _in_bounds(nr, col) and board[nr][col] == EMPTY:
        return [((nr, col), [])]
    return []


def _pawn_capture_moves(
    row: int, col: int, board: Board, mover_is_white: bool
) -> MoveList:
    forward = -1 if mover_is_white else 1
    moves: MoveList = []
    for dc in (-1, 1):
        nr, nc = row + forward, col + dc
        if _in_bounds(nr, nc) and _is_enemy(board[nr][nc], mover_is_white):
            moves.append(((nr, nc), [(nr, nc)]))
    return moves


def _pawn_first_move(
    row: int, col: int, board: Board, mover_is_white: bool, max_steps: int
) -> MoveList:
    if mover_is_white:
        if row != BOARD_SIZE - 2:
            return []
        direction = -1
    else:
        if row != 1:
            return []
        direction = 1
    moves: MoveList = []
    for step in range(1, max_steps + 1):
        nr = row + direction * step
        if not _in_bounds(nr, col) or board[nr][col] != EMPTY:
            break
        moves.append(((nr, col), []))
    return moves


def _pawn_all_moves(
    row: int,
    col: int,
    board: Board,
    mover_is_white: bool,
    first_move_steps: Optional[int],
) -> MoveList:
    """Generate ordinary pawn moves only; En Passant is handled by where_to."""
    moves = _pawn_moves(row, col, board, mover_is_white)
    moves.extend(_pawn_capture_moves(row, col, board, mover_is_white))
    if first_move_steps is not None:
        moves.extend(
            _pawn_first_move(
                row, col, board, mover_is_white, max_steps=first_move_steps
            )
        )
    return _deduplicate_moves(moves)


# ---------------------------------------------------------------------------
# Public movement functions

# ---------------------------------------------------------------------------


def where_to_king(position: Position, board: Board) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    row, col = pos
    mover_is_white = _mover_is_white(pos, board, KING)
    if mover_is_white is None:
        return [], False
    moves: MoveList = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if _in_bounds(nr, nc) and _can_land(board[nr][nc], mover_is_white):
                moves.append(_move_to((nr, nc), board, mover_is_white))
    moves.extend(_castling_moves(row, col, board, mover_is_white))
    return _deduplicate_moves(moves), False


def where_to_queen(position: Position, board: Board) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    row, col = pos
    mover_is_white = _mover_is_white(pos, board, QUEEN)
    if mover_is_white is None:
        return [], False
    moves = _sliding_moves(
        row, col, ORTHOGONAL_DIRS + DIAGONAL_DIRS, board, mover_is_white
    )
    moves.extend(_queentum_tunnel_moves(row, col, board, mover_is_white))
    moves.extend(queen_beta_decay_moves(pos, board))
    return _deduplicate_moves(moves), False


def where_to_bishop(position: Position, board: Board) -> MovementResult:
    """Generate all reflected diagonal moves, then apply forced Underage capture."""
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    row, col = pos
    mover_is_white = _mover_is_white(pos, board, BISHOP)
    if mover_is_white is None:
        return [], False
    # Each ray is traced completely, including any edge reflections, until it
    # returns to the Bishop or encounters its first occupied square.
    moves = _bouncing_bishop_moves(row, col, board, mover_is_white)
    moves.extend(_il_vaticano_moves(row, col, board, mover_is_white))
    return _forced_underage_capture_moves(moves, board)


def where_to_rook(position: Position, board: Board) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, ROOK)
    if mover_is_white is None:
        return [], False
    moves = _sliding_moves(pos[0], pos[1], ORTHOGONAL_DIRS, board, mover_is_white)
    moves.extend(knooklear_fusion_moves(pos, board))
    return _deduplicate_moves(moves), False


def where_to_horse(position: Position, board: Board) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, HORSE)
    if mover_is_white is None:
        return [], False
    moves = _horse_moves(pos[0], pos[1], board, mover_is_white)
    moves.extend(knooklear_fusion_moves(pos, board))
    return _deduplicate_moves(moves), False


def where_to_checker(position: Position, board: Board) -> MovementResult:
    """Generate one-/two-square moves plus all connected hop-chain landings."""
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    row, col = pos
    mover_is_white = _mover_is_white(pos, board, CHECKER)
    if mover_is_white is None:
        return [], False
    moves = _checker_simple_moves(row, col, board, mover_is_white)
    moves.extend(_checker_hops(row, col, board, mover_is_white))
    return _deduplicate_moves(moves), False


def where_to_knook(position: Position, board: Board) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, KNOOK)
    if mover_is_white is None:
        return [], False
    moves = _horse_moves(pos[0], pos[1], board, mover_is_white) + _rook_two_moves(
        pos[0], pos[1], board, mover_is_white
    )
    return _deduplicate_moves(moves), False


def where_to_pawn(position: Position, board: Board) -> MovementResult:
    """Normal Pawn movement and captures; En Passant is handled by where_to."""
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, PAWN)
    if mover_is_white is None:
        return [], False
    return (
        _pawn_all_moves(pos[0], pos[1], board, mover_is_white, first_move_steps=3),
        False,
    )


def where_to_sterilepawn(position: Position, board: Board) -> MovementResult:
    """Sterile Pawn normal movement and captures; no special first move."""
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, STERILE_PAWN)
    if mover_is_white is None:
        return [], False
    return (
        _pawn_all_moves(pos[0], pos[1], board, mover_is_white, first_move_steps=None),
        False,
    )


def where_to_underagepawn(position: Position, board: Board) -> MovementResult:
    """Underage Pawn normal movement and captures, with a two-square first move."""
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, UNDERAGE_PAWN)
    if mover_is_white is None:
        return [], False
    return (
        _pawn_all_moves(pos[0], pos[1], board, mover_is_white, first_move_steps=2),
        False,
    )


def where_to_antiqueen(position: Position, board: Board) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, ANTIQUEEN)
    if mover_is_white is None:
        return [], False
    moves = _horse_moves(pos[0], pos[1], board, mover_is_white)
    moves.extend(_queentum_tunnel_moves(pos[0], pos[1], board, mover_is_white))
    return _deduplicate_moves(moves), False


def where_to_traitorrook(
    position: Position,
    board: Board,
    current_side_is_white: Optional[bool] = None,
) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    row, col = pos
    piece_is_white = _mover_is_white(pos, board, TRAITORROOK)
    if piece_is_white is None:
        return [], False
    white_controls, black_controls = _traitorrook_controllers(row, col, board)
    if current_side_is_white is True:
        if not white_controls:
            return [], False
        mover_is_white = True
    elif current_side_is_white is False:
        if not black_controls:
            return [], False
        mover_is_white = False
    else:
        mover_is_white = piece_is_white
        if mover_is_white and not white_controls:
            return [], False
        if not mover_is_white and not black_controls:
            return [], False
    return _sliding_moves(row, col, ORTHOGONAL_DIRS, board, mover_is_white), False


# ---------------------------------------------------------------------------
# Compatibility helpers for pawn capture / first-move UI calls

# ---------------------------------------------------------------------------


def _capture_by_pawn_type(
    position: Position,
    board: Board,
    piece_type: int,
) -> MovementResult:
    """Return ordinary diagonal pawn captures only; En Passant is dispatcher-only."""
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, piece_type)
    if mover_is_white is None:
        return [], False
    return _pawn_capture_moves(pos[0], pos[1], board, mover_is_white), False


def capture_by_pawn(position: Position, board: Board) -> MovementResult:
    return _capture_by_pawn_type(position, board, PAWN)


def capture_by_sterilepawn(position: Position, board: Board) -> MovementResult:
    return _capture_by_pawn_type(position, board, STERILE_PAWN)


def capture_by_underagepawn(position: Position, board: Board) -> MovementResult:
    return _capture_by_pawn_type(position, board, UNDERAGE_PAWN)


def first_move_pawn(position: Position, board: Board) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, PAWN)
    if mover_is_white is None:
        return [], False
    return _pawn_first_move(pos[0], pos[1], board, mover_is_white, 3), False


def first_move_underagepawn(position: Position, board: Board) -> MovementResult:
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    mover_is_white = _mover_is_white(pos, board, UNDERAGE_PAWN)
    if mover_is_white is None:
        return [], False
    return _pawn_first_move(pos[0], pos[1], board, mover_is_white, 2), False


# No first_move_sterilepawn by design.

# ---------------------------------------------------------------------------
# Dispatcher and Forced En Passant

# ---------------------------------------------------------------------------


def _forced_en_passant_map(
    board: Board,
    en_passant_pawn_position: Optional[Position],
    current_side_is_white: bool,
) -> Dict[Position, MoveList]:
    """Map eligible pawns to forced, potentially chained En Passant moves.
    The last-moved opposing pawn is captured first. The destination is the
    empty square immediately behind it. From there, the chain looks sideways
    toward the side opposite the starting pawn: when the starting pawn was to
    the right of the last-moved pawn, the chain looks left, and vice versa.
    Each additional piece on that side is captured only when the square
    immediately behind that newly found piece is on-board and empty. If the
    chain cannot continue, the last valid destination and captures are returned.
    """
    previous_pawn_pos = _valid_position(en_passant_pawn_position)
    if previous_pawn_pos is None:
        return {}
    pr, pc = previous_pawn_pos
    previous_value = board[pr][pc]
    if previous_value == EMPTY or abs(previous_value) not in PAWN_TYPES:
        return {}
    previous_pawn_is_white = previous_value > 0
    if previous_pawn_is_white == current_side_is_white:
        return {}
    # White advances toward lower row indices; Black advances toward higher.
    behind_step = 1 if previous_pawn_is_white else -1
    first_destination = (pr + behind_step, pc)
    if not _in_bounds(*first_destination):
        return {}
    if board[first_destination[0]][first_destination[1]] != EMPTY:
        # A blocked first En Passant square means En Passant is unavailable.
        return {}
    forced: Dict[Position, MoveList] = {}
    for adjacent_col in (pc - 1, pc + 1):
        source = (pr, adjacent_col)
        if not _in_bounds(*source):
            continue
        source_value = board[source[0]][source[1]]
        if source_value == EMPTY or abs(source_value) not in PAWN_TYPES:
            continue
        if (source_value > 0) != current_side_is_white:
            continue
        # A pawn on the right chains toward the left; one on the left chains
        # toward the right. The initial last-moved pawn is always captured.
        chain_side_step = -1 if adjacent_col > pc else 1
        destination = first_destination
        captures: List[Position] = [previous_pawn_pos]
        while True:
            side_position = (destination[0], destination[1] + chain_side_step)
            if not _in_bounds(*side_position):
                break
            side_value = board[side_position[0]][side_position[1]]
            if side_value == EMPTY:
                break
            # Continue behind the newly found piece, not behind the previous
            # destination. The destination therefore follows the chain sideways
            # as well as advancing one row behind each newly captured piece.
            next_destination = (side_position[0] + behind_step, side_position[1])
            if not _in_bounds(*next_destination):
                break
            if board[next_destination[0]][next_destination[1]] != EMPTY:
                break
            # The next hop is possible, so include this side piece in the
            # capture list and set the final destination directly behind it.
            if side_position not in captures:
                captures.append(side_position)
            destination = next_destination
        forced[source] = [(destination, captures)]
    return forced


def where_to(
    position: Position,
    board: Board,
    en_passant_pawn_position: Optional[Position] = None,
    current_side_is_white: Optional[bool] = None,
) -> MovementResult:
    """Return ``(moves, forced)`` for a selected piece.
    ``en_passant_pawn_position`` is the final position of the pawn that moved
    two or three squares on the immediately preceding turn, or None if the last
    move did not create an En Passant opportunity. This function checks its
    adjacent squares for active-side pawns and enforces Forced En Passant globally.
    Each move is ``(destination, capture_positions)``. ``forced`` is True when
    Forced En Passant applies, or when a Bishop must capture an Underage Pawn.
    """
    pos = _valid_position(position)
    if pos is None or not _board_is_valid(board):
        return [], False
    row, col = pos
    value = board[row][col]
    if value == EMPTY:
        return [], False
    piece_type = abs(value)
    selected_side_is_white = value > 0
    active_side = (
        selected_side_is_white
        if current_side_is_white is None
        else current_side_is_white
    )
    if piece_type != TRAITORROOK and selected_side_is_white != active_side:
        return [], False
    # En Passant is isolated here: pawn movement functions only generate normal
    # forward moves and diagonal captures. If any active-side pawn is adjacent
    # to the previous pawn, only those eligible pawns may move.
    forced_ep = _forced_en_passant_map(board, en_passant_pawn_position, active_side)
    if forced_ep:
        if pos in forced_ep:
            return forced_ep[pos], True
        return [], True
    dispatch = {
        KING: where_to_king,
        QUEEN: where_to_queen,
        BISHOP: where_to_bishop,
        ROOK: where_to_rook,
        HORSE: where_to_horse,
        CHECKER: where_to_checker,
        KNOOK: where_to_knook,
        PAWN: where_to_pawn,
        STERILE_PAWN: where_to_sterilepawn,
        UNDERAGE_PAWN: where_to_underagepawn,
        ANTIQUEEN: where_to_antiqueen,
    }
    if piece_type in dispatch:
        return dispatch[piece_type](pos, board)
    if piece_type == TRAITORROOK:
        return where_to_traitorrook(pos, board, active_side)
    return [], False


def show_all_movements(
    board: Board,
    en_passant_pawn_position: Optional[Position] = None,
    current_side_is_white: Optional[bool] = None,
) -> List[List[Optional[MovementResult]]]:
    """Precompute movement results for every occupied square.
    Each occupied square stores the (moves, forced) result returned by
    where_to(). Empty squares store None.
    """
    all_movements: List[List[Optional[MovementResult]]] = [
        [None for _ in row] for row in board
    ]
    for row in range(len(board)):
        for col in range(len(board[row])):
            if board[row][col] == 0:
                continue
            all_movements[row][col] = where_to(
                (row, col),
                board,
                en_passant_pawn_position=en_passant_pawn_position,
                current_side_is_white=current_side_is_white,
            )
    return all_movements
