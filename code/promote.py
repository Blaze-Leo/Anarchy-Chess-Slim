from typing import List, Optional, Tuple

from constants import *

Position = Tuple[int, int]


def get_promotion_options(
    board: List[List[int]],
    last_position: Position,
    player_colour: str,
) -> List[int]:
    """Return valid promotion choices, or [] if promotion is unavailable.

    White promotes on PROMOTION_RANK_WHITE.
    Black promotes on PROMOTION_RANK_BLACK.

    Pawn-like pieces can promote to PAWN_PROMOTIONS.
    Checkers can promote to CHECKER_PROMOTIONS.

    Returned piece codes retain the player's colour:
        White: positive integers
        Black: negative integers
    """

    if player_colour not in ("white", "black"):
        return []

    row, col = last_position

    # Validate the position.
    if not (0 <= row < len(board) and 0 <= col < len(board[row])):
        return []

    piece = board[row][col]

    if piece == 0:
        return []

    # Ensure the piece belongs to the player who just moved.
    if player_colour == "white":
        if piece < 0 or row != PROMOTION_RANK_WHITE:
            return []
        sign = 1
    else:
        if piece > 0 or row != PROMOTION_RANK_BLACK:
            return []
        sign = -1

    piece_type = abs(piece)

    if piece_type in PROMOTABLE_PAWNS:
        available_promotions = PAWN_PROMOTIONS
    elif piece_type == CHECKER:
        available_promotions = CHECKER_PROMOTIONS
    else:
        return []

    return [sign * promotion for promotion in available_promotions]
