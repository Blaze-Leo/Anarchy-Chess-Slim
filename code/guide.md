# Anarchy Chess Guide

This guide describes the piece movements and special-move rules implemented by `go_where.py` for this modified version of chess.

## Pieces

---

## King

- Moves one square in any direction: horizontally, vertically, or diagonally.
- Can castle toward a rook under the conditions described in **Castling and Self-Bishop Capture**.
- The king's move-generation function allows movement onto an enemy-occupied square.

## Queen

- Moves any number of squares horizontally, vertically, or diagonally.
- Cannot move through other pieces.
- Can perform **Queentum Tunnelling** with a friendly Antiqueen.
- Can perform **Queen Beta Decay** when all three required spawning squares are available.

## Rook

- Moves any number of squares horizontally or vertically.
- Cannot jump over other pieces.
- Can perform **Knooklear Fusion** with a friendly Horse.

## Bishop

- Moves diagonally, but its path can **bounce off the edges of the board**.
- Can bounce multiple times in one move.
- Stops when it encounters an occupied square or returns to its starting square.
- Can perform **Il Vaticano** when the required arrangement of bishops and enemy pieces exists.
- If it can capture an Underage Pawn along a generated bouncing path, capturing an Underage Pawn becomes mandatory. This applies even when the Underage Pawn belongs to the Bishop's own side.

## Horse (Knight)

- Moves in the usual L-shape: two squares in one direction and one square perpendicular to it.
- Can jump over intervening pieces.
- Can perform **Knooklear Fusion** with a friendly Rook.

## Knook

- Moves like a Horse (Knight).
- Can also move like a Rook for **one or two squares horizontally or vertically**.
- Its Rook-like movement cannot jump over pieces.

## Antiqueen

- Moves like a Horse (Knight).
- Can perform **Queentum Tunnelling** with a friendly Queen.

## Checker

The Checker combines short diagonal movement with chained hops.

- Can move one square diagonally to an empty square.
- Can move two squares diagonally when both the intervening square and destination are empty.
- Can hop over a consecutive run of enemy pieces, capturing each enemy in that run.
- After hopping over enemies, it must land on the first square immediately beyond them, and that landing square must be empty and on the board.
- Can chain multiple hops in a single move.
- Can hop over **one friendly piece** during a move. The friendly piece is not captured.
- A friendly piece can only be hopped over once per move, and the friendly hop must land immediately beyond that piece on an empty square.
- Captures are not forced. The Checker may choose among its available moves without being required to capture.

## Traitor Rook

- Moves like a regular Rook: horizontally or vertically, stopping at the first occupied square.
- Its controller is determined by the pieces immediately adjacent to it.
- Count the occupied squares in the eight surrounding positions, excluding other Traitor Rooks.
- The side with more adjacent pieces controls the Traitor Rook.
- The controlling side determines which side's pieces the Traitor Rook can capture.
- **If the adjacent-piece counts are tied, neither side can move the Traitor Rook under this implementation.**

## Pawns

### Regular Pawn

- Moves forward one square when the destination is empty.
- Captures enemy pieces one square diagonally forward.
- A Pawn on its starting row can advance one, two, or three squares if every square along its path is empty.

### Sterile Pawn

- Moves forward one square when the destination is empty.
- Captures enemy pieces one square diagonally forward.
- Does not receive the regular Pawn's extended starting-row move.

### Underage Pawn

- Moves forward one square when the destination is empty.
- Captures enemy pieces one square diagonally forward.
- A Pawn on its starting row can advance one or two squares if the path is clear.
- Is subject to the Bishop's mandatory-capture rule: if a Bishop has a generated move that captures an Underage Pawn, that Bishop must capture an Underage Pawn instead of making another move.
- A Bishop must capture an Underage Pawn even if it is friendly.

---

## Special Rules

---

## Bouncing Bishop

- A Bishop's diagonal path reflects when it reaches an edge of the board.
- The Bishop can bounce off multiple edges in a single move.
- Each unoccupied square reached along the reflected path is a possible destination.
- If the Bishop encounters an occupied square, its path ends there.
- An enemy piece encountered on the path can be captured.
- If the encountered piece is an Underage Pawn, the Bishop can capture it regardless of which side owns it.
- If at least one generated Bishop move captures an Underage Pawn, other Bishop moves are removed from the available options. The capture is mandatory.

## Forced En Passant and Long Passant

En Passant is handled as a forced move when the required opportunity exists.

- The rule applies when the preceding move creates an En Passant opportunity and the position of the last-moved Pawn is supplied to the move generator.
- The last-moved opposing Pawn must be next to an eligible Pawn of the active side.
- The square immediately behind the last-moved Pawn must be on the board and empty.
- When a forced En Passant capture is available, the eligible Pawn must make that capture instead of an ordinary move.
- Other pieces cannot move while the forced En Passant opportunity is active.
- The initial capture removes the last-moved Pawn, and the capturing Pawn moves to the empty square immediately behind it.

### Long Passant Chain

- After the initial En Passant capture, the move may continue through a diagonal chain of additional occupied squares.
- The direction of the chain depends on whether the capturing Pawn began to the left or right of the last-moved Pawn.
- An additional piece is included in the capture chain only when the square immediately behind it is on the board and empty.
- The destination advances behind each additional captured piece.
- The chain stops when there is no further occupied square to capture, the next landing square is blocked, or the required square is off the board.
- The initial En Passant capture and any valid additional captures are treated as part of the same move.

## Queentum Tunnelling

- A Queen and its friendly Antiqueen can swap positions.
- The Queen can tunnel to the square occupied by its friendly Antiqueen.
- The Antiqueen can tunnel to the square occupied by its friendly Queen.
- The special move is available when the matching Queen and Antiqueen belong to the same side.

## Queen Beta Decay

A Queen can split into three pieces when all required spawning squares are available.

- The square immediately in front of the Queen must be on the board and empty.
- The square immediately to the Queen's left must be on the board and empty.
- The square immediately to the Queen's right must be on the board and empty.
- The Queen transforms into:
  - A Sterile Pawn directly in front of the Queen.
  - A Rook immediately to its left.
  - A Horse immediately to its right.
- White's forward direction is toward the opposite end of the board from Black's forward direction.
- If any required spawning square is occupied or outside the board, Queen Beta Decay is unavailable.

## Il Vaticano

Two friendly Bishops can perform Il Vaticano when they are aligned with two enemy pieces between them.

- The destination Bishop must be exactly three squares away from the moving Bishop.
- The Bishops must be aligned horizontally, vertically, or diagonally.
- Both squares between the Bishops must contain enemy pieces.
- The moving Bishop moves to the other friendly Bishop's square.
- Both enemy pieces between the Bishops are captured in the same move.

## Castling and Self-Bishop Capture

The move generator provides castling moves when the required king, rook, path, and destination-square conditions are met.

- The King must be on its configured starting square.
- A friendly Rook must occupy the corresponding corner square.
- The King moves two squares toward that Rook.
- The Rook's destination is the square immediately next to the King's original square.
- The route between the King and Rook must be clear, apart from the permitted destination-square exception.
- A friendly Bishop may occupy either of the two castling destination squares.
- If a friendly Bishop occupies one of those destination squares, it is included in the capture list and is removed as part of the castling move.

**Implementation detail:** This move-generation function checks the board layout and the configured starting positions. It does not track whether the King or Rook moved earlier, and it does not check attacked squares along the castling route.

## Knooklear Fusion

A Rook and a friendly Horse can fuse into a Knook.

- A Rook can fuse with a friendly Horse by moving along an unobstructed horizontal or vertical path onto the Horse's square.
- A Horse can fuse with a friendly Rook by making a normal Knight move onto the Rook's square.
- The fusion triggers an explosion centred on the destination square.
- Every occupied square in the surrounding 3×3 area is included in the capture list, except the moving piece's original square.
- The resulting piece is a Knook placed on the fusion square.

---

## General Movement Notes

- The board boundaries constrain all generated moves.
- Ordinary sliding movement stops at the first occupied square.
- Ordinary pieces can generally land on empty squares or capture an enemy piece. Friendly-piece captures are permitted only for special rules that explicitly allow them, such as a Bishop capturing an Underage Pawn or castling over a friendly Bishop.
- A forced move restricts the available options. In this implementation, forced En Passant restricts the active side's move options, while a mandatory Underage Pawn capture restricts the Bishop's move options.
- This guide covers the movement and candidate special moves generated by `go_where.py`. The module does not itself execute every special-move effect or define promotion outcomes, game-ending conditions, clocks, or timeout rules.
