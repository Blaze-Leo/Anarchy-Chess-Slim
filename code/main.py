import asyncio
import markdown
import random
import string
from contextlib import suppress
from typing import Dict, Optional, List
from pathlib import Path
from promote import get_promotion_options
import engine
from constants import *
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
LOBBY_TIMEOUT_SECONDS = 300
MATCH_INACTIVITY_TIMEOUT_SECONDS = 600  # 10 minutes
BOARD_SIZE = 10

# ============================================================
# DATA MODELS
# ============================================================

class Player:
    """A player session, independent of whether its browser is connected."""

    def __init__(
        self,
        session_id: str,
        username: str,
        public_id: str,
    ):
        self.session_id = session_id
        self.username = username
        self.public_id = public_id
        self.websocket: Optional[WebSocket] = None
        self.active_match_id: Optional[str] = None
        self.expiry_task: Optional[asyncio.Task] = None
        self.connection_generation = 0
        self.is_navigating = False

class Match:
    """One game between two players, with its own action lock."""
    def __init__(self, match_id: str, player_a: Player, player_b: Player):
        self.match_id = match_id
        self.p1 = player_a
        self.p2 = player_b
        self.active_player = self.p1
        self.lock = asyncio.Lock()
        # Canonical [row, column] positions of the last successful move.
        self.last_turn_source_position = None
        self.last_turn_position = None
        self.result: Optional[str] = None
        # One restorable pre-move snapshot per successfully executed move.
        self.undo_history: List[dict] = []
        # At most one opponent-approved action can be pending per match.
        self.pending_action_request: Optional[dict] = None
        self.inactivity_task: Optional[asyncio.Task] = None

class SessionRequest(BaseModel):
    username: str
# All valid sessions, including players in matches.
players: Dict[str, Player] = {}
# Only players waiting for a match.
lobby_users: Dict[str, Player] = {}
# Active matches only.
active_matches: Dict[str, Match] = {}
# Serializes session/lobby/match transitions.
state_lock = asyncio.Lock()
# Promotions awaiting a player's choice, keyed by match ID.
pending_promotions = {}

# ============================================================
# GENERAL HELPERS
# ============================================================

def generate_random_string(length: int = 5) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))

def get_unique_match_id() -> str:
    match_id = generate_random_string(10)
    while match_id in active_matches:
        match_id = generate_random_string(10)
    return match_id

def player_belongs_to_match(match: Match, session_id: str) -> bool:
    return session_id in (match.p1.session_id, match.p2.session_id)

def get_match_opponent(match: Match, session_id: str) -> Optional[Player]:
    if match.p1.session_id == session_id:
        return match.p2
    if match.p2.session_id == session_id:
        return match.p1
    return None

def cancel_expiration(player: Player) -> None:
    task = player.expiry_task
    player.expiry_task = None
    if task is not None and not task.done():
        task.cancel()

def schedule_expiration(player: Player) -> None:
    """Schedule removal of a disconnected player who is waiting in the lobby."""
    cancel_expiration(player)
    player.expiry_task = asyncio.create_task(
        expire_lobby_session(player.session_id, player)
    )

def cancel_match_inactivity(match: Match) -> None:
    """Cancel the inactivity timer associated with a match."""
    task = match.inactivity_task
    match.inactivity_task = None
    if (
        task is not None
        and not task.done()
        and task is not asyncio.current_task()
    ):
        task.cancel()

def reset_match_inactivity(match: Match) -> None:
    """Start a fresh 10-minute inactivity countdown for this match."""
    cancel_match_inactivity(match)
    match.inactivity_task = asyncio.create_task(
        expire_match_after_inactivity(match.match_id, match)
    )

async def safe_send(websocket: Optional[WebSocket], message: dict) -> bool:
    if websocket is None:
        return False
    try:
        await websocket.send_json(message)
        return True
    except Exception as exc:
        print(f"WebSocket send failed: {exc}")
        return False

async def send_to_player(player: Player, message: dict) -> bool:
    return await safe_send(player.websocket, message)

def normalize_position(position):
    """Validate a zero-based [row, column] position."""
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        return None
    row, col = position
    if type(row) is not int or type(col) is not int:
        return None
    if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE):
        return None
    return [row, col]

def transform_position(position, flipped: bool):
    """Convert between a player's displayed coordinates and canonical ones.
    A 180-degree rotation is its own inverse, so this helper works in both
    directions. Invalid positions return None.
    """
    normalized = normalize_position(position)
    if normalized is None:
        return None
    row, col = normalized
    if flipped:
        return [BOARD_SIZE - 1 - row, BOARD_SIZE - 1 - col]
    return [row, col]

def is_knooklear_fusion_move(board, source, target) -> bool:
    """Return True if a Rook/Horse move targets a friendly Horse/Rook."""
    moving_piece = board[source[0]][source[1]]
    target_piece = board[target[0]][target[1]]
    if moving_piece == EMPTY or target_piece == EMPTY:
        return False
    # The two pieces must belong to the same player.
    if (moving_piece > 0) != (target_piece > 0):
        return False
    # Fusion requires one Rook and one Horse.
    return {abs(moving_piece), abs(target_piece)} == {ROOK, HORSE}

# ============================================================
# LOBBY BROADCASTING
# ============================================================

def build_lobby_snapshot() -> list:
    return [
        {
            "username": player.username,
            "public_id": player.public_id,
        }
        for player in lobby_users.values()
    ]

async def broadcast_lobby_update() -> None:
    """Broadcast one complete, identical lobby snapshot to all lobby sockets."""
    message = {"type": "LOBBY_UPDATE", "users": build_lobby_snapshot()}
    connected_players = [p for p in list(lobby_users.values()) if p.websocket]
    await asyncio.gather(
        *(send_to_player(player, message) for player in connected_players),
        return_exceptions=True,
    )

# ============================================================
# GAME STATE / ORIENTATION
# ============================================================

def build_game_state_payload(match: Match, viewer_sid: str) -> dict:
    """Build a viewer-specific board from the canonical engine state."""
    # Player B sees a 180-degree rotated board.
    flipped = viewer_sid == match.p2.session_id
    # Get the canonical board from the engine.
    board = engine.show_state(match.match_id)
    # Rotate the board only for Player B.
    if flipped:
        board = [list(reversed(row)) for row in reversed(board)]
    # Convert both last-move squares to the viewer's orientation.
    last_turn_source_position = None
    last_turn_position = None

    if match.last_turn_source_position is not None:
        last_turn_source_position = transform_position(
            match.last_turn_source_position,
            flipped,
        )

    if match.last_turn_position is not None:
        last_turn_position = transform_position(
            match.last_turn_position,
            flipped,
        )
    return {
        "type": "GAME_STATE",
        "match_id": match.match_id,
        "board": board,
        "history": engine.get_history(match.match_id),
        "player_a_sid": match.p1.session_id,
        "player_a_username": match.p1.username,
        "player_b_sid": match.p2.session_id,
        "player_b_username": match.p2.username,
        "active_player_sid": match.active_player.session_id,
        "can_move": (
            match.result is None
            and match.pending_action_request is None
            and match.active_player.session_id == viewer_sid
        ),
        "game_result": match.result,
        "last_turn_source_position": last_turn_source_position,
        "last_turn_position": last_turn_position,
        "can_request_undo": (
            match.result is None
            and match.active_player.session_id != viewer_sid
            and bool(match.undo_history)
            and match.match_id not in pending_promotions
            and match.pending_action_request is None
        ),
        "pending_action_request": (
            {
                "request_id": match.pending_action_request["request_id"],
                "action": match.pending_action_request["action"],
                "requester_sid": match.pending_action_request["requester_sid"],
                "target_sid": match.pending_action_request["target_sid"],
                "requester_username": match.pending_action_request["requester_username"],
            }
            if match.pending_action_request is not None
            else None
        ),
    }

async def send_game_start(match: Match) -> None:
    """Redirect both players to the new/current match URL."""
    for player in (match.p1, match.p2):
        await send_to_player(
            player,
            {
                "type": "GAME_START",
                "match_id": match.match_id,
                "redirect_url": f"/game/{match.match_id}?sid={player.session_id}",
            },
        )

# ============================================================
# LOBBY SESSION EXPIRATION
# ============================================================

async def expire_lobby_session(session_id: str, expected_player: Player) -> None:
    try:
        await asyncio.sleep(LOBBY_TIMEOUT_SECONDS)
        async with state_lock:
            if players.get(session_id) is not expected_player:
                return
            if expected_player.active_match_id is not None:
                return
            if expected_player.websocket is not None:
                return
            if lobby_users.get(session_id) is not expected_player:
                return
            lobby_users.pop(session_id, None)
            players.pop(session_id, None)
            expected_player.expiry_task = None
            print(f"Lobby session expired: {expected_player.username} ({session_id})")
            await broadcast_lobby_update()
    except asyncio.CancelledError:
        pass

async def expire_match_after_inactivity(
    match_id: str,
    expected_match: Match,
) -> None:
    """End an unchanged match and return both registered players to the lobby."""
    try:
        await asyncio.sleep(MATCH_INACTIVITY_TIMEOUT_SECONDS)

        async with state_lock:
            # A normal close or rematch may have replaced this match already.
            if active_matches.get(match_id) is not expected_match:
                return

            async with expected_match.lock:
                if active_matches.get(match_id) is not expected_match:
                    return

                active_matches.pop(match_id, None)
                pending_promotions.pop(match_id, None)
                engine.remove_game(match_id)

                for player in (expected_match.p1, expected_match.p2):
                    player.active_match_id = None
                    if players.get(player.session_id) is player:
                        lobby_users[player.session_id] = player
                        if player.websocket is None:
                            schedule_expiration(player)

                # This task has completed; do not leave it attached to the match.
                expected_match.inactivity_task = None
                print(f"Match expired due to inactivity: {match_id}")

        await broadcast_lobby_update()

        # Reuse the same client messages as a normal return-to-lobby action.
        for player in (expected_match.p1, expected_match.p2):
            await send_to_player(
                player,
                {
                    "type": "GAME_OVER",
                    "reason": "The match ended due to 10 minutes of inactivity.",
                },
            )
            await send_to_player(
                player,
                {
                    "type": "RETURN_TO_LOBBY",
                    "redirect_url": f"/lobby?sid={player.session_id}",
                },
            )
    except asyncio.CancelledError:
        # The match was closed, replaced, or had its timer reset.
        pass
    except Exception as exc:
        print(f"Match inactivity handler failed for {match_id}: {exc}")

# ============================================================
# HTTP ROUTES
# ============================================================

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "sid": "",
            "public_id": "",
            "match_id": "",
            "screen": "landing",
        },
    )

@app.post("/api/create-session")
async def create_session(request: SessionRequest):
    username = request.username.strip()
    if not username:
        return JSONResponse({"error": "Username is required."}, status_code=400)
    if len(username) > 30:
        return JSONResponse(
            {"error": "Username must be 30 characters or fewer."},
            status_code=400,
        )
    async with state_lock:
        
        # Ensure the username is unique.
        existing_usernames = {
            player.username.casefold()
            for player in players.values()
        }

        if username.casefold() in existing_usernames:
            base_username = username
            suffix_length = 3

            # Keep the suffix at three characters and the full
            # username within the 30-character limit.
            base_username = base_username[:30 - suffix_length - 1]

            while True:
                suffix = generate_random_string(suffix_length)
                candidate_username = f"{base_username}-{suffix}"

                if candidate_username.casefold() not in existing_usernames:
                    username = candidate_username
                    break
        
        sid = generate_random_string()
        while sid in players:
            sid = generate_random_string()

        public_id = generate_random_string(10)

        while any(
            player.public_id == public_id
            for player in players.values()
        ):
            public_id = generate_random_string(10)

        player = Player(sid, username, public_id)
        
        players[sid] = player
        lobby_users[sid] = player
        print(f"Session created: {username} ({sid})")
        await broadcast_lobby_update()
    return JSONResponse({"sid": sid})

@app.get("/lobby")
async def lobby_page(request: Request, sid: str):
    async with state_lock:
        player = players.get(sid)
        if player is None:
            return HTMLResponse(
                content="<h1>Invalid Session</h1><p>This session has expired. Please join again.</p>",
                status_code=404,
            )
        if player.active_match_id:
            match = active_matches.get(player.active_match_id)
            if match is not None:
                return RedirectResponse(
                    url=f"/game/{match.match_id}?sid={sid}",
                    status_code=303,
                )
        if lobby_users.get(sid) is not player:
            return HTMLResponse("<h1>Invalid Session</h1>", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "sid": sid,
            "public_id": player.public_id,
            "match_id": "",
            "screen": "lobby",
        },
    )

@app.get("/guide", response_class=HTMLResponse)
async def guide_page(request: Request, sid: str = ""):
    """Render guide.md as HTML."""
    guide_path = BASE_DIR / "guide.md"

    if not guide_path.is_file():
        return HTMLResponse(
            content=(
                "<h1>Guide not found</h1>"
                "<p>Expected guide.md in the project root.</p>"
            ),
            status_code=404,
        )

    try:
        guide_source = guide_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Unable to read guide.md: {exc}")
        return HTMLResponse(
            content="<h1>Unable to read guide</h1>",
            status_code=500,
        )

    guide_html = markdown.markdown(
        guide_source,
        extensions=["fenced_code", "tables", "toc"],
    )

    if sid and sid not in players:
        sid = ""

    return templates.TemplateResponse(
        request=request,
        name="guide.html",
        context={
            "sid": sid,
            "guide_html": guide_html,
        },
    )
    
@app.get("/game/{match_id}")
async def game_page(request: Request, match_id: str, sid: str):
    async with state_lock:
        match = active_matches.get(match_id)
        if match is None:
            # If the player has already been moved to another match, take them there.
            player = players.get(sid)
            if player and player.active_match_id:
                current = active_matches.get(player.active_match_id)
                if current and player_belongs_to_match(current, sid):
                    return RedirectResponse(
                        url=f"/game/{current.match_id}?sid={sid}",
                        status_code=303,
                    )
            if player and sid in lobby_users:
                return RedirectResponse(url=f"/lobby?sid={sid}", status_code=303)
            return HTMLResponse("<h1>Match Not Found</h1>", status_code=404)
        if not player_belongs_to_match(match, sid):
            return HTMLResponse("<h1>Access Denied</h1>", status_code=403)
    return templates.TemplateResponse(
        request=request,
        name="game.html",
        context={"sid": sid, "match_id": match_id},
    )

# ============================================================
# MATCH CREATION / REMATCH / CLOSE
# ============================================================

async def start_match(challenger_sid: str, target_sid: str) -> Optional[Match]:
    async with state_lock:
        challenger = lobby_users.get(challenger_sid)
        target = lobby_users.get(target_sid)
        if challenger is None or target is None or challenger_sid == target_sid:
            return None
        if challenger.active_match_id is not None or target.active_match_id is not None:
            return None
        cancel_expiration(challenger)
        cancel_expiration(target)
        match_id = get_unique_match_id()
        # The challenged player plays White; the challenger plays Black.
        match = Match(match_id, target, challenger)
        engine.create_game(
            match_id,
            target.session_id,
            challenger.session_id,
        )
        active_matches[match_id] = match
        challenger.active_match_id = match_id
        target.active_match_id = match_id
        reset_match_inactivity(match)
        lobby_users.pop(challenger_sid, None)
        lobby_users.pop(target_sid, None)
        print(f"Match started: {match_id} ({challenger.username} vs {target.username})")
        await broadcast_lobby_update()
    await send_game_start(match)
    return match

async def create_new_match_from_existing(
    old_match_id: str,
    requester_sid: str,
) -> tuple[Optional[Match], bool]:
    """Replace a match with a fresh match between the same two players.
    Idempotent for a stale/double click: if old_match_id has already been
    replaced and the requester is already in a newer match, return that match
    rather than creating another one.
    """
    async with state_lock:
        old_match = active_matches.get(old_match_id)
        requester = players.get(requester_sid)
        if requester is None:
            return None, False
        if old_match is None:
            current = active_matches.get(requester.active_match_id or "")
            if current is not None and player_belongs_to_match(current, requester_sid):
                return current, False
            return None, False
        if not player_belongs_to_match(old_match, requester_sid):
            return None, False
        if requester.active_match_id != old_match_id:
            current = active_matches.get(requester.active_match_id or "")
            if current is not None and player_belongs_to_match(current, requester_sid):
                return current, False
            return None, False
        async with old_match.lock:
            # Re-check after acquiring the match lock.
            if active_matches.get(old_match_id) is not old_match:
                current = active_matches.get(requester.active_match_id or "")
                if current is not None and player_belongs_to_match(
                    current, requester_sid
                ):
                    return current, False
                return None, False
            player_a, player_b = old_match.p1, old_match.p2
            new_match_id = get_unique_match_id()
            new_match = Match(new_match_id, player_a, player_b)
            engine.create_game(new_match_id, player_a.session_id, player_b.session_id)
            cancel_match_inactivity(old_match)
            active_matches.pop(old_match_id, None)
            active_matches[new_match_id] = new_match
            player_a.active_match_id = new_match_id
            player_b.active_match_id = new_match_id
            engine.remove_game(old_match_id)
            reset_match_inactivity(new_match)
            print(f"Match {old_match_id} replaced with fresh match {new_match_id}")
    return new_match, True

async def close_match_to_lobby(match_id: str, requester_sid: str) -> Optional[Match]:
    """Close the current match and return both participants to the lobby."""
    async with state_lock:
        match = active_matches.get(match_id)
        requester = players.get(requester_sid)
        # A duplicate/stale click must not close a newer match.
        if match is None:
            if requester and requester.active_match_id:
                current = active_matches.get(requester.active_match_id)
                if current is not None and player_belongs_to_match(
                    current, requester_sid
                ):
                    return None
            if requester and requester_sid in lobby_users:
                return None
            return None
        if not player_belongs_to_match(match, requester_sid):
            return None
        if requester is None or requester.active_match_id != match_id:
            return None
        async with match.lock:
            if active_matches.get(match_id) is not match:
                return None
            cancel_match_inactivity(match)
            active_matches.pop(match_id, None)
            pending_promotions.pop(match_id, None)
            engine.remove_game(match_id)
            for player in (match.p1, match.p2):
                player.active_match_id = None
                if players.get(player.session_id) is player:
                    lobby_users[player.session_id] = player
                    if player.websocket is None:
                        schedule_expiration(player)
            await broadcast_lobby_update()
    for player in (match.p1, match.p2):
        await send_to_player(
            player,
            {"type": "GAME_OVER", "reason": "The match was closed."},
        )
        await send_to_player(
            player,
            {
                "type": "RETURN_TO_LOBBY",
                "redirect_url": f"/lobby?sid={player.session_id}",
            },
        )
    print(f"Match closed and players returned to lobby: {match_id}")
    return match

async def send_player_to_current_location(player: Player) -> None:
    """Recover gracefully from a stale game action after a navigation race."""
    if player.active_match_id:
        match = active_matches.get(player.active_match_id)
        if match and player_belongs_to_match(match, player.session_id):
            await send_to_player(
                player,
                {
                    "type": "GAME_START",
                    "match_id": match.match_id,
                    "redirect_url": f"/game/{match.match_id}?sid={player.session_id}",
                },
            )
            return
    if player.session_id in lobby_users:
        await send_to_player(
            player,
            {
                "type": "RETURN_TO_LOBBY",
                "redirect_url": f"/lobby?sid={player.session_id}",
            },
        )

# ============================================================
# WEBSOCKET HANDLER
# ============================================================

async def handle_do_movement(
    websocket: WebSocket,
    player: Player,
    session_id: str,
    data: dict,
) -> None:
    """Validate and execute a move, checking whether promotion is required."""
    requested_match_id = data.get("match_id") or player.active_match_id
    match = active_matches.get(requested_match_id or "")
    if (
        match is None
        or not player_belongs_to_match(match, session_id)
        or player.active_match_id != requested_match_id
    ):
        await send_player_to_current_location(player)
        return
    flipped = session_id == match.p2.session_id
    display_source = normalize_position(data.get("from_pos"))
    display_target = normalize_position(data.get("to_pos"))
    source = (
        transform_position(display_source, flipped)
        if display_source is not None
        else None
    )
    target = (
        transform_position(display_target, flipped)
        if display_target is not None
        else None
    )
    rejection_reason = None
    updates = []
    promotion_prompt = None
    async with match.lock:
        # The match might have closed while this request waited.
        if active_matches.get(requested_match_id) is not match:
            rejection_reason = "This match is already closed."
        elif match.result is not None:
            rejection_reason = (
                "The game has ended. Accept the result to start a new game."
            )
        # Do not allow another move while a promotion choice is pending.
        elif requested_match_id in pending_promotions:
            rejection_reason = "Choose a promotion before making another move."
        elif match.pending_action_request is not None:
            rejection_reason = "Resolve the pending opponent request before moving."
        elif match.active_player.session_id != session_id:
            rejection_reason = "It is not your turn."
        elif source is None or target is None:
            rejection_reason = "Invalid source or destination position."
        else:
            player_colour = "black" if session_id == match.p2.session_id else "white"
            engine_moves = engine.show_movement(
                requested_match_id,
                source,
                player_colour,
            )
            # Only movable (red) destinations count; cosmetic opponent moves
            # shown in blue are never valid targets.
            possible_positions = [
                position
                for overlay_type in ("square", "dot")
                for colour, positions in engine_moves.get(overlay_type, {}).items()
                if colour == engine.MOVABLE_COLOUR
                for position in positions
            ]
            if target not in possible_positions:
                rejection_reason = "Invalid movement destination."
            else:
                # Inspect the board before the move so we can identify
                # whether this is a Rook/Horse fusion.
                board_before_move = engine.show_state(requested_match_id)
                moving_piece = board_before_move[source[0]][source[1]]
                knooklear_fusion = is_knooklear_fusion_move(
                    board_before_move,
                    source,
                    target,
                )
                engine_state_before_move = engine.snapshot_game_state(
                    requested_match_id
                )
                match_state_before_move = {
                    "active_player_sid": match.active_player.session_id,
                    "last_turn_source_position": (
                        match.last_turn_source_position[:]
                        if match.last_turn_source_position is not None
                        else None
                    ),
                    "last_turn_position": (
                        match.last_turn_position[:]
                        if match.last_turn_position is not None
                        else None
                    ),
                    "result": match.result,
                }
                move_succeeded = engine.do_movement(
                    requested_match_id,
                    source,
                    target,
                    player_colour,
                )
                if move_succeeded:
                    reset_match_inactivity(match)
                    # The engine applies the move's capture list, which
                    # clears the occupied squares in the 3x3 explosion.
                    # Replace the surviving piece at the center with a Knook.
                    if knooklear_fusion:
                        knook_piece = KNOOK if moving_piece > 0 else -KNOOK
                        if not engine.promote_piece(
                            requested_match_id,
                            target,
                            knook_piece,
                        ):
                            raise RuntimeError(
                                "Knooklear Fusion succeeded, but Knook "
                                "placement failed."
                            )
                    match.undo_history.append(
                        {
                            "engine_state": engine_state_before_move,
                            **match_state_before_move,
                        }
                    )
                    match.last_turn_source_position = source[:]
                    match.last_turn_position = target[:]
                    # Check promotion against the canonical engine board.
                    board = engine.show_state(requested_match_id)
                    promotion_options = get_promotion_options(
                        board,
                        target,
                        player_colour,
                    )
                    if promotion_options:
                        # Store the pending promotion in canonical coordinates.
                        pending_promotions[requested_match_id] = {
                            "session_id": session_id,
                            "position": target[:],
                            "player_colour": player_colour,
                            "options": promotion_options,
                        }
                        # Send the promotion square in the player's display
                        # coordinates because the frontend uses that orientation.
                        promotion_prompt = {
                            "type": "PROMOTION_REQUIRED",
                            "match_id": requested_match_id,
                            "position": transform_position(target, flipped),
                            "options": promotion_options,
                        }
                    # Do not switch turns until promotion is resolved.
                    else:
                        # No promotion required: switch to the opponent.
                        opponent = get_match_opponent(match, session_id)
                        if opponent is not None:
                            match.active_player = opponent
                        match.result = engine.get_game_result(requested_match_id)
                # Broadcast the current state to both players.
                updates = [
                    (
                        recipient,
                        build_game_state_payload(
                            match,
                            recipient.session_id,
                        ),
                    )
                    for recipient in (match.p1, match.p2)
                ]
    if rejection_reason:
        await safe_send(
            websocket,
            {
                "type": "MOVE_REJECTED",
                "reason": rejection_reason,
            },
        )
        return
    for recipient, payload in updates:
        await send_to_player(recipient, payload)
    # Send the promotion request only to the player who must choose.
    if promotion_prompt is not None:
        await safe_send(websocket, promotion_prompt)

async def handle_promotion(
    websocket: WebSocket,
    player: Player,
    session_id: str,
    data: dict,
) -> None:
    """Validate and apply a player's promotion choice."""
    requested_match_id = data.get("match_id") or player.active_match_id
    if not isinstance(requested_match_id, str):
        await safe_send(
            websocket,
            {
                "type": "MOVE_REJECTED",
                "reason": "Invalid match ID.",
            },
        )
        return
    match = active_matches.get(requested_match_id)
    if (
        match is None
        or not player_belongs_to_match(match, session_id)
        or player.active_match_id != requested_match_id
    ):
        await send_player_to_current_location(player)
        return
    selected_piece = data.get("piece")
    rejection_reason = None
    updates = []
    async with match.lock:
        # Verify that the match is still active.
        if active_matches.get(requested_match_id) is not match:
            rejection_reason = "This match is already closed."
        else:
            pending = pending_promotions.get(requested_match_id)
            # There must be a promotion waiting to be completed.
            if pending is None:
                rejection_reason = "There is no pending promotion."
            # Only the player who made the move may choose.
            elif pending["session_id"] != session_id:
                rejection_reason = "You cannot choose the other player's promotion."
            # The promoting player still owns the current turn.
            elif match.active_player.session_id != session_id:
                rejection_reason = "It is not your turn."
            # Reject strings, booleans, and other invalid piece codes.
            elif type(selected_piece) is not int:
                rejection_reason = "Invalid promotion piece."
            # The choice must be among the server-approved options.
            elif selected_piece not in pending["options"]:
                rejection_reason = "That promotion choice is not allowed."
            else:
                # Update the engine's internal board.
                promotion_succeeded = engine.promote_piece(
                    requested_match_id,
                    pending["position"],
                    selected_piece,
                )
                if not promotion_succeeded:
                    rejection_reason = "The promotion could not be completed."
                else:
                    reset_match_inactivity(match)
                    # Clear the pending promotion only after success.
                    pending_promotions.pop(
                        requested_match_id,
                        None,
                    )
                    # Give the next turn to the opponent.
                    opponent = get_match_opponent(
                        match,
                        session_id,
                    )
                    if opponent is not None:
                        match.active_player = opponent
                    match.result = engine.get_game_result(requested_match_id)
                    # Prepare an updated board for both players.
                    updates = [
                        (
                            recipient,
                            build_game_state_payload(
                                match,
                                recipient.session_id,
                            ),
                        )
                        for recipient in (match.p1, match.p2)
                    ]
    # Report errors without closing the promotion dialog.
    if rejection_reason:
        await safe_send(
            websocket,
            {
                "type": "MOVE_REJECTED",
                "reason": rejection_reason,
            },
        )
        return
    # Tell the promoting player's frontend to close the dialog.
    await safe_send(
        websocket,
        {
            "type": "PROMOTION_COMPLETED",
            "match_id": requested_match_id,
        },
    )
    # Send the promoted board and new turn to both players.
    for recipient, payload in updates:
        await send_to_player(recipient, payload)

async def handle_action_request(
    websocket: WebSocket,
    player: Player,
    session_id: str,
    data: dict,
    action: str,
) -> None:
    """Create an undo/new-game request and notify both participants."""
    requested_match_id = data.get("match_id") or player.active_match_id
    if not isinstance(requested_match_id, str):
        await safe_send(websocket, {
            "type": "ACTION_REQUEST_ERROR",
            "action": action,
            "reason": "Invalid match ID.",
        })
        return
    match = active_matches.get(requested_match_id)
    if (
        match is None
        or not player_belongs_to_match(match, session_id)
        or player.active_match_id != requested_match_id
    ):
        await safe_send(websocket, {
            "type": "ACTION_REQUEST_ERROR",
            "action": action,
            "reason": "This match is no longer active.",
        })
        return
    rejection_reason = None
    opponent = None
    request = None
    updates = []
    async with match.lock:
        if active_matches.get(requested_match_id) is not match:
            rejection_reason = "This match is no longer active."
        elif match.pending_action_request is not None:
            rejection_reason = "Another request is already waiting for a response."
        elif requested_match_id in pending_promotions:
            rejection_reason = "Complete the pending promotion before requesting this action."
        elif action == "UNDO" and match.result is not None:
            rejection_reason = "Undo is unavailable after the game has ended."
        elif action == "UNDO" and match.active_player.session_id == session_id:
            rejection_reason = "You can request an undo only during your opponent's turn."
        elif action == "UNDO" and not match.undo_history:
            rejection_reason = "There is no previous move to undo."
        elif action not in ("UNDO", "NEW_GAME"):
            rejection_reason = "Unknown action request."
        else:
            opponent = get_match_opponent(match, session_id)
            if opponent is None:
                rejection_reason = "Could not find your opponent."
            else:
                request = {
                    "request_id": generate_random_string(12),
                    "action": action,
                    "requester_sid": session_id,
                    "target_sid": opponent.session_id,
                    "requester_username": player.username,
                }
                match.pending_action_request = request
                updates = [
                    (recipient, build_game_state_payload(match, recipient.session_id))
                    for recipient in (match.p1, match.p2)
                ]
    if rejection_reason:
        await safe_send(websocket, {
            "type": "ACTION_REQUEST_ERROR",
            "action": action,
            "reason": rejection_reason,
        })
        return
    # Mark the requester as waiting before the opponent can respond.
    await send_to_player(player, {
        "type": "ACTION_REQUEST_SENT",
        "match_id": requested_match_id,
        "request_id": request["request_id"],
        "action": action,
        "target_sid": opponent.session_id,
    })
    await send_to_player(opponent, {
        "type": "ACTION_REQUEST",
        "match_id": requested_match_id,
        "request_id": request["request_id"],
        "action": action,
        "from_sid": session_id,
        "from_username": player.username,
    })
    for recipient, payload in updates:
        await send_to_player(recipient, payload)

async def complete_new_game_request(
    match_id: str,
    request_id: str,
    responder_sid: str,
):
    """Atomically approve a pending new-game request and replace the match."""
    async with state_lock:
        old_match = active_matches.get(match_id)
        if old_match is None:
            return None
        async with old_match.lock:
            request = old_match.pending_action_request
            if (
                active_matches.get(match_id) is not old_match
                or request is None
                or request.get("request_id") != request_id
                or request.get("action") != "NEW_GAME"
                or request.get("target_sid") != responder_sid
                or not player_belongs_to_match(old_match, responder_sid)
            ):
                return None
            # Preserve references to both original players.
            player_a, player_b = old_match.p1, old_match.p2
            # Find the requester and the player accepting the request.
            participants = {
                player_a.session_id: player_a,
                player_b.session_id: player_b,
            }
            requester = participants.get(request.get("requester_sid"))
            accepting_player = participants.get(responder_sid)
            # Verify both players belong to this match.
            if requester is None or accepting_player is None:
                return None
            new_match_id = get_unique_match_id()
            # Match.p1 is White, so the accepter gets White.
            # Match.p2 is Black, so the requester gets Black.
            new_match = Match(
                new_match_id,
                accepting_player,
                requester,
            )
            engine.create_game(
                new_match_id,
                accepting_player.session_id,
                requester.session_id,
            )
            # Replace the old match with the new one.
            cancel_match_inactivity(old_match)
            active_matches.pop(match_id, None)
            active_matches[new_match_id] = new_match
            player_a.active_match_id = new_match_id
            player_b.active_match_id = new_match_id
            pending_promotions.pop(match_id, None)
            engine.remove_game(match_id)
            reset_match_inactivity(new_match)
            print(f"New game request accepted: {match_id} -> {new_match_id}")
            return old_match, new_match, dict(request)

async def handle_action_request_response(
    websocket: WebSocket,
    player: Player,
    session_id: str,
    data: dict,
) -> None:
    """Apply an opponent's accept/reject response to an outstanding request."""
    requested_match_id = data.get("match_id") or player.active_match_id
    request_id = data.get("request_id")
    accepted = data.get("accepted")
    if not isinstance(requested_match_id, str) or not isinstance(request_id, str) or type(accepted) is not bool:
        await safe_send(websocket, {
            "type": "ACTION_REQUEST_ERROR",
            "reason": "Invalid request response.",
            "request_id": request_id if isinstance(request_id, str) else None,
        })
        return
    match = active_matches.get(requested_match_id)
    if (
        match is None
        or not player_belongs_to_match(match, session_id)
        or player.active_match_id != requested_match_id
    ):
        await safe_send(websocket, {
            "type": "ACTION_REQUEST_ERROR",
            "reason": "This request is no longer active.",
            "request_id": request_id,
        })
        return
    async with match.lock:
        pending = match.pending_action_request
        if (
            pending is None
            or pending.get("request_id") != request_id
            or pending.get("target_sid") != session_id
        ):
            pending_action = None
        else:
            pending_action = pending.get("action")
    if pending_action is None:
        await safe_send(websocket, {
            "type": "ACTION_REQUEST_ERROR",
            "reason": "This request has already been handled or is not addressed to you.",
            "request_id": request_id,
        })
        return
    if pending_action == "NEW_GAME" and accepted:
        completed = await complete_new_game_request(
            requested_match_id,
            request_id,
            session_id,
        )
        if completed is None:
            await safe_send(websocket, {
                "type": "ACTION_REQUEST_ERROR",
                "reason": "The new-game request is no longer active.",
                "request_id": request_id,
            })
            return
        old_match, new_match, request = completed
        for recipient in (old_match.p1, old_match.p2):
            await send_to_player(recipient, {
                "type": "ACTION_REQUEST_RESOLVED",
                "request_id": request_id,
                "action": "NEW_GAME",
                "accepted": True,
                "message": "The new-game request was accepted.",
            })
        await send_game_start(new_match)
        return
    rejection_reason = None
    resolution = None
    updates = []
    async with match.lock:
        pending = match.pending_action_request
        if (
            active_matches.get(requested_match_id) is not match
            or pending is None
            or pending.get("request_id") != request_id
            or pending.get("target_sid") != session_id
        ):
            rejection_reason = "This request has already been handled."
        elif pending.get("action") != pending_action:
            rejection_reason = "The pending request changed; please refresh the game."
        elif accepted and pending_action != "UNDO":
            rejection_reason = "This action cannot be completed from this response."
        elif accepted and (requested_match_id in pending_promotions or not match.undo_history):
            rejection_reason = "The previous move can no longer be undone."
        elif accepted and match.result is not None:
            rejection_reason = "Undo is unavailable after the game has ended."
        else:
            resolution = dict(pending)
            match.pending_action_request = None
            if accepted:
                snapshot = match.undo_history[-1]
                if not engine.restore_game_state(
                    requested_match_id,
                    snapshot["engine_state"],
                ):
                    match.pending_action_request = pending
                    rejection_reason = "The previous game state could not be restored."
                else:
                    match.undo_history.pop()
                    active_player_sid = snapshot["active_player_sid"]
                    match.active_player = (
                        match.p1 if match.p1.session_id == active_player_sid else match.p2
                    )
                    match.last_turn_source_position = snapshot["last_turn_source_position"]
                    match.last_turn_position = snapshot["last_turn_position"]
                    match.result = snapshot["result"]
                    reset_match_inactivity(match)
                    pending_promotions.pop(requested_match_id, None)
            if rejection_reason is None:
                updates = [
                    (recipient, build_game_state_payload(match, recipient.session_id))
                    for recipient in (match.p1, match.p2)
                ]
    if rejection_reason:
        await safe_send(websocket, {
            "type": "ACTION_REQUEST_ERROR",
            "reason": rejection_reason,
            "request_id": request_id,
        })
        return
    response_message = {
        "type": "ACTION_REQUEST_RESOLVED",
        "request_id": request_id,
        "action": pending_action,
        "accepted": accepted,
        "message": (
            "Undo completed." if pending_action == "UNDO" and accepted
            else "Undo request rejected." if pending_action == "UNDO"
            else "New-game request rejected."
        ),
    }
    for recipient in (match.p1, match.p2):
        await send_to_player(recipient, response_message)
    for recipient, payload in updates:
        await send_to_player(recipient, payload)

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    player: Optional[Player] = None
    generation: Optional[int] = None
    old_websocket: Optional[WebSocket] = None
    async with state_lock:
        player = players.get(session_id)
        if player is None:
            await safe_send(websocket, {"type": "INVALID_SESSION"})
            await websocket.close(code=1008)
            return
        old_websocket = player.websocket
        player.connection_generation += 1
        generation = player.connection_generation
        player.websocket = websocket
        cancel_expiration(player)
        print(f"Client connected/re-connected: {player.username} ({session_id})")
    if old_websocket is not None and old_websocket is not websocket:
        with suppress(Exception):
            await old_websocket.close(
                code=1000, reason="Reconnected from another connection"
            )
    try:
        await safe_send(
            websocket,
            {"type": "LOBBY_READY", "sid": session_id, "username": player.username},
        )
        if player.active_match_id:
            match = active_matches.get(player.active_match_id)
            if match is not None and player_belongs_to_match(match, session_id):
                async with match.lock:
                    await safe_send(
                        websocket, build_game_state_payload(match, session_id)
                    )
        elif session_id in lobby_users:
            await broadcast_lobby_update()
        while True:
            data = await websocket.receive_json()
            if player.connection_generation != generation:
                break
            if not isinstance(data, dict):
                continue
            message_type = data.get("type")
            # ------------------------------------------------
            # Lobby membership confirmation
            # ------------------------------------------------
            if message_type == "JOIN_LOBBY":
                async with state_lock:
                    if players.get(session_id) is not player:
                        await safe_send(websocket, {"type": "INVALID_SESSION"})
                        continue
                    if player.active_match_id is None:
                        cancel_expiration(player)
                        lobby_users[session_id] = player
                        await broadcast_lobby_update()
            # ------------------------------------------------
            # Request game state
            # ------------------------------------------------
            elif message_type in ("JOIN_GAME", "GET_GAME_STATE"):
                requested_match_id = data.get("match_id") or player.active_match_id
                match = active_matches.get(requested_match_id or "")
                if (
                    match is None
                    or not player_belongs_to_match(match, session_id)
                    or player.active_match_id != requested_match_id
                ):
                    await send_player_to_current_location(player)
                    continue
                async with match.lock:
                    await safe_send(
                        websocket, build_game_state_payload(match, session_id)
                    )
            # ------------------------------------------------
            # Lobby challenge
            # ------------------------------------------------
            elif message_type == "CHALLENGE":
                target_public_id = data.get("target_public_id")

                if not isinstance(target_public_id, str):
                    continue

                async with state_lock:
                    challenger = lobby_users.get(session_id)

                    target = next(
                        (
                            p
                            for p in lobby_users.values()
                            if p.public_id == target_public_id
                        ),
                        None,
                    )

                    if (
                        challenger is None
                        or target is None
                        or challenger.session_id == target.session_id
                    ):
                        print(
                            "CHALLENGE rejected: "
                            f"challenger_in_lobby={challenger is not None}, "
                            f"target_found={target is not None}"
                        )
                        await send_to_player(
                            player,
                            {
                                "type": "MATCH_ERROR",
                                "message": (
                                    "Could not challenge that player. "
                                    "Make sure they are in the lobby."
                                ),
                            },
                        )
                        continue

                    await send_to_player(
                        target,
                        {
                            "type": "MATCH_REQUEST",
                            "from_public_id": challenger.public_id,
                            "from_username": challenger.username,
                        },
                    )
            # ------------------------------------------------
            # Accept challenge
            # ------------------------------------------------
            elif message_type == "ACCEPT_CHALLENGE":
                challenger_public_id = data.get("challenger_public_id")

                if not isinstance(challenger_public_id, str):
                    continue

                async with state_lock:
                    challenger = next(
                        (
                            p
                            for p in lobby_users.values()
                            if p.public_id == challenger_public_id
                        ),
                        None,
                    )

                    if challenger is None:
                        print(
                            "ACCEPT_CHALLENGE rejected: challenger "
                            f"{challenger_public_id} not found in lobby"
                        )
                        await send_to_player(
                            player,
                            {
                                "type": "MATCH_ERROR",
                                "message": (
                                    "That player is no longer available. "
                                    "Please try again."
                                ),
                            },
                        )
                        continue

                    challenger_sid = challenger.session_id
                    challenger_name = challenger.username

                match = await start_match(challenger_sid, session_id)
                if match is None:
                    print(
                        "start_match failed: "
                        f"challenger={challenger_name}({challenger_sid}) "
                        f"vs accepter={player.username}({session_id})"
                    )
                    await send_to_player(
                        player,
                        {
                            "type": "MATCH_ERROR",
                            "message": (
                                "Could not start the match. Please try again."
                            ),
                        },
                    )
                    challenger_now = players.get(challenger_sid)
                    if challenger_now is not None:
                        await send_to_player(
                            challenger_now,
                            {
                                "type": "MATCH_ERROR",
                                "message": (
                                    "The match could not be started. "
                                    "Please challenge again."
                                ),
                            },
                        )
                    await broadcast_lobby_update()
            # ------------------------------------------------
            # Get movement options (display coordinates in, display coordinates out)
            # ------------------------------------------------
            elif message_type == "SHOW_MOVEMENT":
                requested_match_id = data.get("match_id") or player.active_match_id
                match = active_matches.get(requested_match_id or "")
                if (
                    match is None
                    or not player_belongs_to_match(match, session_id)
                    or player.active_match_id != requested_match_id
                ):
                    await send_player_to_current_location(player)
                    continue
                display_position = normalize_position(data.get("position"))
                flipped = session_id == match.p2.session_id
                engine_position = (
                    transform_position(display_position, flipped)
                    if display_position is not None
                    else None
                )
                async with match.lock:
                    if active_matches.get(requested_match_id) is not match:
                        continue
                    if engine_position is None:
                        moves_for_view = {
                            "square": {},
                            "dot": {},
                        }
                    else:
                        player_colour = (
                            "black" if session_id == match.p2.session_id else "white"
                        )
                        engine_moves = engine.show_movement(
                            requested_match_id,
                            engine_position,
                            player_colour,
                        )
                        moves_for_view = {
                            "square": {},
                            "dot": {},
                        }
                        for overlay_type in ("square", "dot"):
                            for colour, positions in engine_moves.get(
                                overlay_type,
                                {},
                            ).items():
                                moves_for_view[overlay_type][colour] = [
                                    transform_position(position, flipped)
                                    for position in positions
                                ]
                    await safe_send(
                        websocket,
                        {
                            "type": "MOVEMENT_OPTIONS",
                            "match_id": requested_match_id,
                            "position": display_position,
                            "moves": moves_for_view,
                        },
                    )
            # ------------------------------------------------
            # Execute movement
            # ------------------------------------------------
            elif message_type == "DO_MOVEMENT":
                await handle_do_movement(
                    websocket,
                    player,
                    session_id,
                    data,
                )
            elif message_type == "PROMOTE":
                await handle_promotion(
                    websocket,
                    player,
                    session_id,
                    data,
                )
            # ------------------------------------------------
            # New Game: replace this match with a fresh match for both players.
            # ------------------------------------------------
            elif message_type == "REQUEST_UNDO":
                await handle_action_request(websocket, player, session_id, data, "UNDO")
            elif message_type in ("REQUEST_NEW_GAME", "NEW_GAME"):
                await handle_action_request(websocket, player, session_id, data, "NEW_GAME")
            elif message_type == "RESPOND_ACTION_REQUEST":
                await handle_action_request_response(websocket, player, session_id, data)
            # ------------------------------------------------
            # Back to Lobby: close the match for both players.
            # ------------------------------------------------
            elif message_type in ("BACK_TO_LOBBY", "LEAVE_GAME"):
                requested_match_id = data.get("match_id") or player.active_match_id
                if not isinstance(requested_match_id, str):
                    await send_player_to_current_location(player)
                    continue
                closed = await close_match_to_lobby(
                    requested_match_id,
                    session_id,
                )
                if closed is None:
                    await send_player_to_current_location(player)
    except WebSocketDisconnect:
        print(f"Client disconnected: {session_id}")
    except Exception as exc:
        print(f"WebSocket error for {session_id}: {exc}")
    finally:
        should_broadcast = False
        async with state_lock:
            current_player = players.get(session_id)
            if (
                current_player is player
                and player.connection_generation == generation
                and player.websocket is websocket
            ):
                player.websocket = None
                if (
                    player.active_match_id is None
                    and lobby_users.get(session_id) is player
                ):
                    schedule_expiration(player)
                    should_broadcast = True
        if should_broadcast:
            await broadcast_lobby_update()
