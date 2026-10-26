# Anarchy Chess Rules

A 10x10 chess variant with 12 piece types and several special moves. White moves first; players alternate one move per turn. Captures are made by landing on an enemy piece (unless a rule says otherwise).

## Board Setup

```
Black:  Rook Horse Checker Bishop Queen King Bishop Knook Antiqueen Rook   row 0
        Underage Pawns at columns 3 and 6                                   rows 1-2 (pawns)
White:  mirror image                                                        row 9
        Underage Pawns at columns 3 and 6                                   rows 7-8 (pawns)

Traitor Rooks: (3,0) and (6,9)
```

Pawn rows: White pawns on rows 7-8, Black pawns on rows 1-2. White advances toward row 0; Black toward row 9.

**Winning:** eliminate the enemy King. **Draw:** both Kings eliminated in one move, or the Kings become adjacent at any point.

## Pieces

| Piece | Movement |
|---|---|
| **King** | One square in any direction. May castle (see Special Moves). |
| **Queen** | Slides any distance, orthogonally or diagonally. Queentum Tunnelling and Beta Decay (Special Moves). |
| **Antiqueen** | Knight move. Queentum Tunnelling (Special Moves). |
| **Rook** | Slides orthogonally. Knooklear Fusion (Special Moves). |
| **Horse** | Knight move. Knooklear Fusion (Special Moves). |
| **Knook** | Knight move, or 1-2 squares orthogonally without jumping. |
| **Bishop** | Slides diagonally, **reflecting off board edges** like a light ray; a ray stops at the first piece it meets and may capture it (an enemy, or any Underage Pawn). Il Vaticano (Special Moves). Forced Underage capture (Forced Rules). |
| **Checker** | 1 square diagonally to an empty square; 2 squares diagonally if the intervening square is empty. May also hop: jump over a consecutive run of enemy pieces and land on the empty square immediately beyond, capturing every piece jumped. Hops can chain, but every hop in a chain must capture. Alternatively, one hop over a single friendly piece (not captured) is allowed as a standalone move - it cannot be combined with any other hop. |
| **Pawn** | 1 square forward; from its starting row it may instead advance up to 3 squares. Captures diagonally forward. Forced En Passant (Forced Rules). |
| **Sterile Pawn** | Same as Pawn, but has no multi-square first move. |
| **Underage Pawn** | Same as Pawn, but its first move is up to 2 squares. |
| **Traitor Rook** | Slides orthogonally for whichever side currently has more pieces in the 8 surrounding squares (other Traitor Rooks don't count). If the counts are tied or the opponent leads, it is immobile. Its allegiance is re-evaluated every turn. |

## Special Moves

### Castling (King)
Available only from the King's starting square, toward a corner Rook that is still on its starting square. The King moves two squares toward that Rook and the Rook lands on the square between them. Every square between the King and Rook must be empty except the two landing squares, each of which may be empty or hold a **friendly Bishop** - a friendly Bishop on a landing square is captured as part of the move.

### Queentum Tunnelling (Queen / Antiqueen)
A Queen may swap squares with a friendly Antiqueen, and an Antiqueen may swap with a friendly Queen. No path requirements; nothing is captured.

### Knooklear Fusion (Rook / Horse)
A Rook that can slide unobstructed onto a friendly Horse, or a Horse that can knight-move onto a friendly Rook, may fuse with it: both pieces are removed, **every occupied square in the 3x3 area centered on the destination is captured** (the mover's origin is excluded), and a Knook is placed on an empty square within that blast area.

### Queen Beta Decay (Queen)
Instead of moving, a Queen may transform in place into three pieces: a **Sterile Pawn one square forward, a Rook to its left, and a Horse to its right**. All three spawn squares must be empty.

### Il Vaticano (Bishop)
If another friendly Bishop sits exactly 3 squares away in a straight line (horizontal, vertical, or diagonal) with **both intervening squares occupied by enemy pieces**, the moving Bishop lands on the friendly Bishop's square and captures both enemies.

## Forced Rules

### Forced En Passant / Long Passant
If the previous move was a pawn advancing 2-3 squares, normal play is suspended: only your pawns on the same row, adjacent to that pawn, may move - and they must capture it by landing one square behind it (in your forward direction). From there the capture **chains sideways** in the direction away from where the captured pawn started: each additional piece found on that side is captured if the square immediately behind it (your forward direction) is on-board and empty, and the final destination is the square behind the last captured piece.

### Forced Underage Pawn Capture (Bishop)
If a Bishop has any legal move landing on an Underage Pawn (friendly or enemy), it **must** capture one; all other moves are unavailable until no Underage Pawn is reachable.

## Promotion

When a pawn reaches the final rank, its owner chooses: **Rook, Horse, Knook, Queen, Bishop, or Checker**. A Checker reaching the final rank may promote to a **King** (or remain a Checker). Promotion happens immediately on arrival; the game is blocked until a choice is made.
