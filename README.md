# Anarchy Chess

A real-time, multiplayer web version of a heavily modified 10x10 chess variant. Players join a lobby over WebSockets, challenge each other, and play matches with an unusual set of pieces (Checker, Knook, Antiqueen, Traitor Rook, three pawn types) and special moves such as bouncing bishops, forced en passant chains, piece swaps, fusions, and a Queen that can decay into three pieces.

The game is fully server-authoritative: the Python backend owns all rules, board state, turn order, and match lifecycle; the browser only sends move requests and renders whatever the server broadcasts.

## Repository Layout

```
Anarchy-Chess/
├ start-anarchy.sh              # Top-level launcher (delegates to code/runtime/)
└ code/
  └ main.py                     # FastAPI app: HTTP routes, WebSocket protocol, lobby & match orchestration
    engine.py                   # Game engine: board storage, move execution, special-move effects, history, snapshots
      go_where.py               # Pure move generation for every piece (no board mutation)
        constants.py            # Board size, piece codes, promotion rules
          promote.py            # Promotion eligibility & options for pawns/checkers
    templates/
      index.html                # Landing + lobby screen
      game.html                 # Match screen (board, controls, history, dialogs)
      guide.html                # In-app rules guide (renders guide.md as HTML)
    static/
      js/game.js                # Frontend: WebSocket client, board rendering, move/promotion/undo UI
      css/style.css             # Styling for all screens
      svg/                      # Piece graphics (numbered codes + named variants, white/black)
    guide.md                    # Human-readable rules reference for all pieces & special moves
    runtime/
      anarchy-launcher.py       # Supervisor: starts app, waits for readiness, opens Cloudflare tunnel
        run-app.sh              # Runs uvicorn on 127.0.0.1:8000 inside a Python 3.12 venv
          start-local.sh        # Starts `cloudflared` quick tunnel to the local app
```

## Tech Stack

- **Backend:** Python 3.12, FastAPI, Uvicorn, Jinja2 templates, `markdown` (for the in-app guide), Pydantic for request validation.
- **Real-time layer:** a single WebSocket per player (`/ws/{session_id}`) carrying all lobby and game traffic as JSON messages.
- **Frontend:** plain HTML/CSS/vanilla JavaScript (no framework, no build step).
- **Deployment:** local uvicorn on port 8000 exposed through a Cloudflare quick tunnel (`cloudflared`).

## Architecture

### Layers

1. **`main.py`** (application/orchestration)
   - Manages three in-memory registries: `players` (all sessions), `lobby_users` (waiting players), `active_matches` (live games), guarded by a global `state_lock`; each match additionally has its own `asyncio.Lock`.
   - HTTP routes: `/` (landing), `/api/create-session` (create session, auto-suffices duplicate usernames), `/lobby?sid=`, `/game/{match_id}?sid=`, `/guide?sid=`.
   - WebSocket handler dispatches message types: `JOIN_LOBBY`, `CHALLENGE` / `ACCEPT_CHALLENGE`, `SHOW_MOVEMENT`, `DO_MOVEMENT`, `PROMOTE`, `REQUEST_UNDO`, `REQUEST_NEW_GAME`, `RESPOND_ACTION_REQUEST`, `BACK_TO_LOBBY`.
   - Handles reconnection (per-player connection generation, stale socket close), lobby session expiry (300 s disconnected) and match inactivity timeout (600 s of no moves ends the match and returns both players to the lobby).
   - Player B sees a 180-degree rotated board; `transform_position` converts between display and canonical coordinates in every direction.

2. **`engine.py`** (rules execution)
   - Stores one canonical 10x10 board per match (`_games`), with signed integer piece codes: positive = White, negative = Black, `0` = empty.
   - Maintains en-passant state, a per-match `MovementCache` (invalidated on every board change, pre-warmed for the next player), and move history.
   - `do_movement` validates a requested destination against generated moves, then executes it, dispatching special-move effects:
     - **Queentum Tunnelling** (Queen/Antiqueen swap),
     - **Castling** (king two squares toward a corner rook; may capture a friendly bishop on the landing square),
     - **Il Vaticano** (two friendly bishops swap, capturing the two enemy pieces between them),
     - **Queen Beta Decay** (Queen replaced by Sterile Pawn + Rook + Horse on adjacent squares).
   - Knooklear Fusion is detected in `main.py` (Rook/Horse moving onto a friendly counterpart) and finished with `promote_piece`, which places the resulting Knook after the engine has cleared the 3x3 explosion capture list.
   - Game result: king elimination wins; both kings eliminated or kings touching = draw.
   - Provides `snapshot_game_state` / `restore_game_state` for the opponent-approved undo feature (one restorable snapshot per move).

3. **`go_where.py`** (move generation, pure functions)
   - Returns `(moves, forced)` where each move is `(destination, [captured_positions])`.
   - Per-piece generators: king (incl. castling candidates), queen (+tunnelling, beta decay), rook, bouncing bishop (reflected diagonals, mandatory Underage Pawn capture filter), horse, knook (knight + short rook), checker (1/2-square diagonal moves plus chained enemy hops and one friendly hop), antiqueen, the three pawn types, and the Traitor Rook (controlled by which side has more adjacent pieces; immobile on a tie).
   - **Forced En Passant / Long Passant:** when the previous move was a 2- or 3-square pawn advance, only adjacent eligible pawns may move, and they must capture the last-moved pawn, potentially chaining sideways captures ("long passant"). This is enforced globally via `_forced_en_passant_map`.
   - `show_all_movements` precomputes moves for every occupied square; Traitor Rooks are sign-inverted on a working copy so ordinary generators treat them as enemy pieces.

4. **`promote.py`** (promotion rules)
   - Pawns and Underage Pawns promote on the final rank to Rook, Horse, Knook, Queen, Bishop, or Checker; Checkers can promote to King or Checker. The server sends the legal options in a `PROMOTION_REQUIRED` message and blocks further moves until the player chooses.

### Board & Pieces

- 10x10 board. Back ranks: Rook, Horse/Antiqueen, Knook/Checker, Bishop, Queen, King, Bishop, (mirror), with Underage Pawns in the pawn ranks at columns 3 and 6.
- Two independent **Traitor Rooks** start at (3,0) and (6,9); their allegiance is recomputed from adjacent pieces each move.
- Piece codes live in `constants.py`; SVG artwork for every piece/color lives in `static/svg/`.

### Match Lifecycle

1. A player creates a session (`POST /api/create-session`) and appears in the lobby snapshot broadcast to everyone.
2. One player sends `CHALLENGE` with the target's public id; the target accepts (`ACCEPT_CHALLENGE`). The accepter plays White, the challenger Black.
3. Both clients are redirected to `/game/{match_id}?sid=...`. Moves go through `SHOW_MOVEMENT` (legal-move overlays) and `DO_MOVEMENT`; promotions and opponent-approved undo/new-game requests flow through their own message types.
4. Undo: only the player whose turn it is *not* can request; the opponent accepts/rejects, and on acceptance the previous engine snapshot is restored. New game: same request/response pattern, but accepting replaces the match with a fresh one (idempotent against double-clicks).
5. The match ends on king elimination/draw, both players leaving to the lobby, or 10 minutes of inactivity.

## Running Locally

Prerequisites: Python 3.12 (venv at `/mnt/Local/Virtual_Environments/Python_3.12`), `uvicorn`, `fastapi`, `jinja2`, `markdown`, and `cloudflared` for the public tunnel.

```bash
# Full launcher: starts the app, waits for readiness, opens a Cloudflare tunnel
./start-anarchy.sh

# Or run pieces manually:
cd code
source /mnt/Local/Virtual_Environments/Python_3.12/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000      # app (see runtime/run-app.sh)
cloudflared tunnel --url http://localhost:8000     # public URL (runtime/start-local.sh)
```

The launcher supports `R` (restart app) and `E` (exit), and cleanly stops both process groups on shutdown.

## Rules Reference

Full piece movement and special-move rules are documented in [`code/guide.md`](code/guide.md), which is also served as an in-app page at `/guide`.
