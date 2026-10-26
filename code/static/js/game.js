// static/js/game.js
(() => {
    "use strict";
// =====================================================
// CONFIGURATION
// =====================================================
    const BOARD_SIZE = 10;
    const EMPTY = 0;
    const PIECE_IMAGE_DIRECTORY = "/static/svg/";
    const RECONNECT_BASE_DELAY = 1000;
    const RECONNECT_MAX_DELAY = 5000;
    const FILES = "ABCDEFGHIJ";
    const root = document.getElementById("game-container");
    const boardElement = document.getElementById("chessboard");
    if (!root || !boardElement) {
        console.error("Game container or chessboard element is missing.");
        return;
    }
    const sessionId = root.dataset.sessionId;
    let matchId = root.dataset.matchId;
// =====================================================
// CLIENT STATE
// =====================================================
    let websocket = null;
    let board = Array.from(
        { length: BOARD_SIZE },
        () => Array(BOARD_SIZE).fill(EMPTY)
    );
    let selectedPosition = null;
// All positions that can currently be clicked as destinations.
    let movementTargets = new Set();
// Movement overlays received from the server.
    let movementOverlays = {
        square: {},
        dot: {}
    };
// Last successful move's destination, in this player's orientation.
    let lastTurnSourcePosition = null;
    let lastTurnPosition = null;
    let activePlayerSid = null;
    let playerASid = null;
    let playerBSid = null;
    let canMove = false;
    let reconnectTimer = null;
    let reconnectAttempts = 0;
    let intentionalNavigation = false;
    let actionPending = false;
    let canRequestUndo = false;
    let pendingOutgoingActionRequest = null;
    let pendingIncomingActionRequest = null;
    let actionRequestResponding = false;
// Promotion dialog state.
    let promotionDialogOpen = false;
    let promotionSubmitting = false;
    let currentPromotionOptions = [];
    let gameResultDialogOpen = false;
    let gameResultSubmitting = false;
// =====================================================
// HTML ELEMENT REFERENCES
// =====================================================
    const connectionIndicator =
        document.getElementById("connection-indicator");
    const connectionText =
        document.getElementById("connection-text");
    const gameStatus =
        document.getElementById("game-status");
    const footerStatus =
        document.getElementById("footer-game-status");
    const moveHistory =
        document.getElementById("move-history");
    const notifications =
        document.getElementById("game-notifications");
    const newGameButton =
        document.getElementById("new-game-btn");
    const undoButton =
        document.getElementById("undo-btn");
    const lobbyButton =
        document.getElementById("lobby-btn");
    const gameResultOverlay =
        document.getElementById("game-result-overlay");
    const gameResultTitle =
        document.getElementById("game-result-title");
    const gameResultAcceptButton =
        document.getElementById("game-result-accept");
    const promotionOverlay =
        document.getElementById("promotion-overlay");
    const promotionOptionsElement =
        document.getElementById("promotion-options");
    const promotionStatus =
        document.getElementById("promotion-status");
    const actionRequestOverlay =
        document.getElementById("action-request-overlay");
    const actionRequestTitle =
        document.getElementById("action-request-title");
    const actionRequestDescription =
        document.getElementById("action-request-description");
    const actionRequestStatus =
        document.getElementById("action-request-status");
    const actionRequestAcceptButton =
        document.getElementById("action-request-accept");
    const actionRequestRejectButton =
        document.getElementById("action-request-reject");
// =====================================================
// INITIALIZATION
// =====================================================
    function initialize() {
        renderBoard();
        connectWebSocket();
// New Game button.
        newGameButton.addEventListener(
            "click",
            () => requestNewGame(false)
        );
        undoButton.addEventListener("click", requestUndo);
        actionRequestAcceptButton.addEventListener(
            "click",
            () => respondToActionRequest(true)
        );
        actionRequestRejectButton.addEventListener(
            "click",
            () => respondToActionRequest(false)
        );
// Back to Lobby button.
        lobbyButton.addEventListener(
            "click",
            requestBackToLobby
        );
        gameResultAcceptButton.addEventListener(
            "click",
            acceptGameResult
        );
// Handle clicks on all 100 squares.
        boardElement.addEventListener("click", event => {
            const square = event.target.closest(".chess-square");
            if (!square || !boardElement.contains(square)) {
                return;
            }
            const row = Number(square.dataset.row);
            const col = Number(square.dataset.col);
            handleSquareClick(row, col);
        });
        setGameStatus("Connecting to game...");
        setActionButtonsDisabled(gameResultDialogOpen);
        updateActionButtons();
    }
// =====================================================
// WEBSOCKET CONNECTION
// =====================================================
    function getWebSocketURL() {
        const protocol =
            window.location.protocol === "https:"
                ? "wss:"
                : "ws:";
        return (
            `${protocol}//${window.location.host}` +
            `/ws/${encodeURIComponent(sessionId)}`
        );
    }
    function connectWebSocket() {
        if (intentionalNavigation || !sessionId || !matchId) {
            return;
        }
        if (
            websocket &&
            (
                websocket.readyState === WebSocket.OPEN ||
                websocket.readyState === WebSocket.CONNECTING
            )
        ) {
            return;
        }
        clearTimeout(reconnectTimer);
        setConnectionStatus(false, "Connecting...");
        const socket = new WebSocket(getWebSocketURL());
        websocket = socket;
        socket.onopen = () => {
            if (websocket !== socket) {
                return;
            }
            reconnectAttempts = 0;
            setConnectionStatus(true, "Connected");
// Request the authoritative game state.
            sendMessage({
                type: "GET_GAME_STATE",
                match_id: matchId
            });
        };
        socket.onmessage = event => {
            if (websocket !== socket) {
                return;
            }
            let message;
            try {
                message = JSON.parse(event.data);
            } catch (error) {
                console.error(
                    "Invalid server message:",
                    error
                );
                return;
            }
            handleServerMessage(message);
        };
        socket.onerror = error => {
            console.error("WebSocket error:", error);
        };
        socket.onclose = () => {
// Ignore events from an old connection.
            if (websocket !== socket) {
                return;
            }
            websocket = null;
            if (intentionalNavigation) {
                return;
            }
            setConnectionStatus(false, "Disconnected");
            setGameStatus(
                "Connection lost. Reconnecting..."
            );
            scheduleReconnect();
        };
    }
    function scheduleReconnect() {
        if (intentionalNavigation) {
            return;
        }
        clearTimeout(reconnectTimer);
        const delay = Math.min(
            RECONNECT_BASE_DELAY * (2 ** reconnectAttempts),
            RECONNECT_MAX_DELAY
        );
        reconnectAttempts++;
        reconnectTimer = setTimeout(
            connectWebSocket,
            delay
        );
    }
    function disconnectWebSocket() {
        clearTimeout(reconnectTimer);
        if (!websocket) {
            return;
        }
        const socket = websocket;
        websocket = null;
        try {
            socket.close();
        } catch (error) {
            console.error(
                "Error closing WebSocket:",
                error
            );
        }
    }
    function sendMessage(message) {
        if (
            !websocket ||
            websocket.readyState !== WebSocket.OPEN
        ) {
            setGameStatus(
                "Not connected to the server. Reconnecting..."
            );
            return false;
        }
        websocket.send(JSON.stringify(message));
        return true;
    }
// =====================================================
// NEW GAME AND BACK TO LOBBY
// =====================================================
    function setActionButtonsDisabled(disabled) {
        actionPending = disabled;
        updateActionButtons();
    }
    function updateActionButtons() {
        const requestBusy = Boolean(
            pendingOutgoingActionRequest ||
            pendingIncomingActionRequest ||
            actionRequestResponding
        );
        newGameButton.disabled = actionPending || requestBusy || promotionDialogOpen;
        undoButton.disabled = (
            actionPending ||
            requestBusy ||
            promotionDialogOpen ||
            gameResultDialogOpen ||
            !canRequestUndo
        );
        lobbyButton.disabled = actionPending;
        if (pendingOutgoingActionRequest && pendingOutgoingActionRequest.action === "NEW_GAME") {
            newGameButton.textContent = "Waiting for response...";
        } else if (actionPending) {
            newGameButton.textContent = "Please wait...";
        } else {
            newGameButton.textContent = "New Game";
        }
    }
    function requestNewGame(fromGameResult = false) {
        if (
            pendingOutgoingActionRequest ||
            pendingIncomingActionRequest ||
            actionRequestResponding ||
            promotionDialogOpen ||
            (!fromGameResult && (actionPending || gameResultDialogOpen))
        ) {
            return;
        }
        const sent = sendMessage({
            type: "REQUEST_NEW_GAME",
            match_id: matchId
        });
        if (!sent) {
            return;
        }
        pendingOutgoingActionRequest = {
            action: "NEW_GAME",
            request_id: null
        };
        if (fromGameResult) {
            gameResultSubmitting = true;
            gameResultAcceptButton.disabled = true;
            gameResultAcceptButton.textContent = "WAITING FOR OPPONENT...";
        }
        updateActionButtons();
        setGameStatus("New-game request sent to your opponent.");
    }
    function requestUndo() {
        if (
            !canRequestUndo ||
            actionPending ||
            pendingOutgoingActionRequest ||
            pendingIncomingActionRequest ||
            actionRequestResponding ||
            promotionDialogOpen ||
            gameResultDialogOpen
        ) {
            return;
        }
        const sent = sendMessage({
            type: "REQUEST_UNDO",
            match_id: matchId
        });
        if (!sent) {
            return;
        }
        pendingOutgoingActionRequest = {
            action: "UNDO",
            request_id: null
        };
        updateActionButtons();
        setGameStatus("Undo request sent to your opponent.");
    }
    function requestBackToLobby() {
        if (actionPending) {
            return;
        }
        const confirmed = window.confirm(
            "Close this match for both players and return to the lobby?"
        );
        if (!confirmed) {
            return;
        }
        const sent = sendMessage({
            type: "BACK_TO_LOBBY",
            match_id: matchId
        });
        if (sent) {
            setActionButtonsDisabled(true);
            setGameStatus(
                "Closing match and returning both players to the lobby..."
            );
        }
    }
    function showGameResult(result) {
        if (!["DRAW", "WHITE WINS", "BLACK WINS"].includes(result)) {
            return;
        }
        const firstDisplay = !gameResultDialogOpen;
        gameResultDialogOpen = true;
        canMove = false;
        gameResultTitle.textContent = result;
        gameResultAcceptButton.textContent = gameResultSubmitting
            ? "WAITING FOR OPPONENT..."
            : "REQUEST NEW GAME";
        gameResultAcceptButton.disabled = gameResultSubmitting;
        gameResultOverlay.hidden = false;
        setActionButtonsDisabled(true);
        updateTurnIndicator();
        setGameStatus(result);
        if (firstDisplay) {
            gameResultAcceptButton.focus();
        }
    }
    function acceptGameResult() {
        if (!gameResultDialogOpen || gameResultSubmitting) {
            return;
        }
        requestNewGame(true);
    }
    function navigateIntentionally(url) {
        if (!url) {
            return;
        }
        intentionalNavigation = true;
        disconnectWebSocket();
        window.location.href = url;
    }
// =====================================================
// SERVER MESSAGE HANDLING
// =====================================================
    function showIncomingActionRequest(message) {
        if (message.match_id && message.match_id !== matchId) {
            return;
        }
        if (!message.request_id || !["UNDO", "NEW_GAME"].includes(message.action)) {
            return;
        }
        if (pendingIncomingActionRequest?.request_id === message.request_id) {
            return;
        }
        pendingIncomingActionRequest = {
            request_id: message.request_id,
            action: message.action,
            from_username: message.from_username || "Your opponent"
        };
        actionRequestResponding = false;
        actionRequestTitle.textContent = message.action === "UNDO"
            ? "Undo Request"
            : "New Game Request";
        actionRequestDescription.textContent = message.action === "UNDO"
            ? `${pendingIncomingActionRequest.from_username} requests to undo their previous move. Accept?`
            : `${pendingIncomingActionRequest.from_username} requests to start a new game. Accept?`;
        actionRequestStatus.textContent = "Choose Accept or Reject.";
        actionRequestAcceptButton.disabled = false;
        actionRequestRejectButton.disabled = false;
        actionRequestOverlay.hidden = false;
        updateActionButtons();
        actionRequestRejectButton.focus();
    }
    function respondToActionRequest(accepted) {
        if (!pendingIncomingActionRequest || actionRequestResponding) {
            return;
        }
        const sent = sendMessage({
            type: "RESPOND_ACTION_REQUEST",
            match_id: matchId,
            request_id: pendingIncomingActionRequest.request_id,
            accepted
        });
        if (!sent) {
            actionRequestStatus.textContent = "Not connected. Reconnect before responding.";
            return;
        }
        actionRequestResponding = true;
        actionRequestAcceptButton.disabled = true;
        actionRequestRejectButton.disabled = true;
        actionRequestStatus.textContent = accepted
            ? "Sending acceptance..."
            : "Sending rejection...";
        updateActionButtons();
    }
    function handleActionRequestSent(message) {
        if (message.match_id && message.match_id !== matchId) {
            return;
        }
        pendingOutgoingActionRequest = {
            action: message.action,
            request_id: message.request_id
        };
        updateActionButtons();
        setGameStatus(message.action === "UNDO"
            ? "Undo request sent. Waiting for your opponent."
            : "New-game request sent. Waiting for your opponent.");
    }
    function handleActionRequestResolved(message) {
        if (message.request_id && pendingOutgoingActionRequest &&
            pendingOutgoingActionRequest.request_id &&
            pendingOutgoingActionRequest.request_id !== message.request_id) {
            return;
        }
        if (message.request_id && pendingIncomingActionRequest &&
            pendingIncomingActionRequest.request_id !== message.request_id) {
            return;
        }
        const action = message.action ||
            pendingIncomingActionRequest?.action ||
            pendingOutgoingActionRequest?.action;
        pendingOutgoingActionRequest = null;
        pendingIncomingActionRequest = null;
        actionRequestResponding = false;
        actionRequestOverlay.hidden = true;
        actionRequestAcceptButton.disabled = false;
        actionRequestRejectButton.disabled = false;
        if (action === "NEW_GAME") {
            gameResultSubmitting = false;
            gameResultAcceptButton.disabled = false;
            gameResultAcceptButton.textContent = "REQUEST NEW GAME";
        }
        const text = message.message || (message.accepted
            ? `${action === "UNDO" ? "Undo" : "New-game"} request accepted.`
            : `${action === "UNDO" ? "Undo" : "New-game"} request rejected.`);
        addNotification(text, message.accepted ? "info" : "warning");
        setGameStatus(text);
        updateActionButtons();
    }
    function handleActionRequestError(message) {
        const requestId = message.request_id;
        if (pendingOutgoingActionRequest &&
            (!requestId || !pendingOutgoingActionRequest.request_id ||
             pendingOutgoingActionRequest.request_id === requestId)) {
            pendingOutgoingActionRequest = null;
        }
        if (pendingIncomingActionRequest &&
            (!requestId || pendingIncomingActionRequest.request_id === requestId)) {
            pendingIncomingActionRequest = null;
            actionRequestOverlay.hidden = true;
        }
        actionRequestResponding = false;
        actionRequestAcceptButton.disabled = false;
        actionRequestRejectButton.disabled = false;
        if (message.action === "NEW_GAME" || gameResultSubmitting) {
            gameResultSubmitting = false;
            gameResultAcceptButton.disabled = false;
            gameResultAcceptButton.textContent = "REQUEST NEW GAME";
        }
        const reason = message.reason || "The request could not be processed.";
        setGameStatus(reason);
        addNotification(reason, "warning");
        updateActionButtons();
    }
    function syncPendingActionRequest(request) {
        if (!request || !request.request_id || !request.action) {
            if (pendingOutgoingActionRequest || pendingIncomingActionRequest) {
                pendingOutgoingActionRequest = null;
                pendingIncomingActionRequest = null;
                actionRequestResponding = false;
                actionRequestOverlay.hidden = true;
                actionRequestAcceptButton.disabled = false;
                actionRequestRejectButton.disabled = false;
                updateActionButtons();
            }
            return;
        }
        if (request.requester_sid === sessionId) {
            pendingOutgoingActionRequest = {
                action: request.action,
                request_id: request.request_id
            };
            updateActionButtons();
            setGameStatus(request.action === "UNDO"
                ? "Undo request sent. Waiting for your opponent."
                : "New-game request sent. Waiting for your opponent.");
        } else if (request.target_sid === sessionId) {
            showIncomingActionRequest({
                match_id: matchId,
                request_id: request.request_id,
                action: request.action,
                from_username: request.requester_username
            });
        }
    }
    function handleServerMessage(message) {
        switch (message.type) {
            case "LOBBY_READY":
                break;
            case "GAME_STATE":
                handleGameState(message);
                break;
            case "ACTION_REQUEST":
                showIncomingActionRequest(message);
                break;
            case "ACTION_REQUEST_SENT":
                handleActionRequestSent(message);
                break;
            case "ACTION_REQUEST_RESOLVED":
                handleActionRequestResolved(message);
                break;
            case "ACTION_REQUEST_ERROR":
                handleActionRequestError(message);
                break;
            case "MOVEMENT_OPTIONS":
                handleMovementOptions(message);
                break;
            case "PROMOTION_REQUIRED":
                handlePromotionRequired(message);
                break;
            case "PROMOTION_COMPLETED":
                if (message.match_id === matchId) {
                    hidePromotionDialog();
                    addNotification("Promotion completed.", "info");
                }
                break;
            case "MOVE_REJECTED": {
                if (!gameResultDialogOpen && !pendingOutgoingActionRequest && !pendingIncomingActionRequest) {
                    setActionButtonsDisabled(false);
                }
                const reason =
                    message.reason || "The action was rejected.";
// Keep the promotion dialog open if the server rejects
// a promotion choice, allowing the player to try again.
                if (promotionDialogOpen) {
                    promotionSubmitting = false;
                    setPromotionChoicesDisabled(false);
                    promotionStatus.textContent =
                        `${reason} Please choose again.`;
                }
                setGameStatus(reason);
                addNotification(reason, "warning");
                break;
            }
            case "GAME_START":
                if (message.match_id) {
                    matchId = message.match_id;
                }
                navigateIntentionally(message.redirect_url);
                break;
            case "GAME_OVER":
                canMove = false;
                updateTurnIndicator();
                setGameStatus(
                    message.reason || "The match has ended."
                );
                break;
            case "RETURN_TO_LOBBY":
                navigateIntentionally(
                    message.redirect_url ||
                    `/lobby?sid=${encodeURIComponent(sessionId)}`
                );
                break;
            case "INVALID_SESSION":
                intentionalNavigation = true;
                disconnectWebSocket();
                setGameStatus(
                    "Invalid session. Returning to the home page..."
                );
                addNotification(
                    "Your session is no longer valid.",
                    "error"
                );
                window.setTimeout(() => {
                    window.location.href = "/";
                }, 1200);
                break;
            default:
                console.log(
                    "Unhandled server message:",
                    message
                );
        }
    }
// =====================================================
// PROMOTION DIALOG
// =====================================================
// Absolute piece codes from constants.py.
    const PROMOTION_PIECE_NAMES = {
        1: "King",
        2: "Queen",
        3: "Bishop",
        4: "Rook",
        5: "Horse",
        6: "Checker",
        7: "Knook"
    };
    function handlePromotionRequired(message) {
        if (message.match_id !== matchId) {
            return;
        }
        if (!Array.isArray(message.options) || message.options.length === 0) {
            console.error("Promotion request did not include valid options.");
            return;
        }
// Accept only recognized, non-zero signed piece codes and remove duplicates.
        const options = [...new Set(message.options.filter(piece =>
            Number.isInteger(piece) &&
            piece !== 0 &&
            Object.prototype.hasOwnProperty.call(
                PROMOTION_PIECE_NAMES,
                Math.abs(piece)
            )
        ))];
        if (options.length === 0) {
            console.error("No valid promotion choices were supplied.");
            return;
        }
        currentPromotionOptions = options;
        promotionDialogOpen = true;
        promotionSubmitting = false;
        renderPromotionOptions();
        promotionStatus.textContent = "Choose one of the available pieces.";
        promotionOverlay.hidden = false;
// Clear any selected move while the choice is pending.
        selectedPosition = null;
        movementTargets.clear();
        movementOverlays = { square: {}, dot: {} };
        renderBoard();
        setGameStatus("Choose a piece to complete your promotion.");
        const firstOption = promotionOptionsElement.querySelector("button");
        if (firstOption) {
            firstOption.focus();
        }
    }
    function renderPromotionOptions() {
        promotionOptionsElement.replaceChildren();
        for (const pieceCode of currentPromotionOptions) {
            const pieceName = PROMOTION_PIECE_NAMES[Math.abs(pieceCode)];
            const button = document.createElement("button");
            button.type = "button";
            button.className = "promotion-option-button";
            button.setAttribute("aria-label", `Promote to ${pieceName}`);
            const image = document.createElement("img");
            image.className = "promotion-piece-image";
            image.src = `${PIECE_IMAGE_DIRECTORY}${pieceCode}.svg`;
            image.alt = pieceName;
            image.draggable = false;
            image.onerror = () => {
                image.classList.add("promotion-image-unavailable");
                image.alt = `${pieceName} image unavailable`;
            };
            const label = document.createElement("span");
            label.className = "promotion-piece-name";
            label.textContent = pieceName;
            button.append(image, label);
            button.addEventListener("click", () => choosePromotion(pieceCode));
            promotionOptionsElement.appendChild(button);
        }
    }
    function choosePromotion(pieceCode) {
        if (
            !promotionDialogOpen ||
            promotionSubmitting ||
            !currentPromotionOptions.includes(pieceCode)
        ) {
            return;
        }
        const sent = sendMessage({
            type: "PROMOTE",
            match_id: matchId,
            piece: pieceCode
        });
        if (!sent) {
            promotionStatus.textContent =
                "Not connected. Reconnect before choosing a promotion.";
            return;
        }
        promotionSubmitting = true;
        setPromotionChoicesDisabled(true);
        promotionStatus.textContent =
            `Promoting to ${PROMOTION_PIECE_NAMES[Math.abs(pieceCode)]}...`;
        setGameStatus("Submitting your promotion choice...");
    }
    function setPromotionChoicesDisabled(disabled) {
        promotionOptionsElement.querySelectorAll("button").forEach(button => {
            button.disabled = disabled;
        });
    }
    function hidePromotionDialog() {
        promotionOverlay.hidden = true;
        promotionDialogOpen = false;
        promotionSubmitting = false;
        currentPromotionOptions = [];
        promotionOptionsElement.replaceChildren();
    }
// =====================================================
// GAME STATE
// =====================================================
    function handleGameState(message) {
        if (
            !Array.isArray(message.board) ||
            message.board.length !== BOARD_SIZE ||
            message.board.some(
row =>
                    !Array.isArray(row) ||
                    row.length !== BOARD_SIZE
            )
        ) {
            console.error(
                "Server returned a board that is not 10x10."
            );
            return;
        }
// The server sends the board oriented for this player.
        board = message.board.map(row => row.slice());
        matchId = message.match_id || matchId;
        activePlayerSid = message.active_player_sid;
        playerASid = message.player_a_sid;
        playerBSid = message.player_b_sid;
        canMove = message.can_move === true;
        canRequestUndo = message.can_request_undo === true;
        // Read and validate the last move's destination.
        // Read and validate the source and destination of the last move.
        function parseLastTurnPosition(position) {
            let row = null;
            let col = null;

            if (Array.isArray(position) && position.length === 2) {
                [row, col] = position;
            } else if (position && typeof position === "object") {
                row = position.row ?? position[0] ?? null;
                col = position.col ?? position[1] ?? null;
            }

            if (
                Number.isInteger(row) &&
                Number.isInteger(col) &&
                row >= 0 &&
                row < BOARD_SIZE &&
                col >= 0 &&
                col < BOARD_SIZE
            ) {
                return { row, col };
            }

            return null;
        }

        lastTurnSourcePosition = parseLastTurnPosition(
            message.last_turn_source_position
        );

        lastTurnPosition = parseLastTurnPosition(
            message.last_turn_position
        );
        // Clear any old selection after a state update.
        selectedPosition = null;
        movementTargets.clear();
        movementOverlays = {
            square: {},
            dot: {}
        };
        updatePlayerNames(message);
        renderBoard();
        renderHistory(message.history || []);
        updateTurnIndicator();
        setConnectionStatus(true, "Connected");
        if (message.game_result) {
            showGameResult(message.game_result);
        } else {
            setActionButtonsDisabled(false);
        }
        syncPendingActionRequest(message.pending_action_request);
        updateActionButtons();
        document.getElementById("match-id").textContent =
            matchId;
    }
    function updatePlayerNames(message) {
        const aName =
            message.player_a_username || "Player A";
        const bName =
            message.player_b_username || "Player B";
        const isPlayerA = sessionId === playerASid;
        const ownName = isPlayerA ? aName : bName;
        const opponentName = isPlayerA ? bName : aName;
        const ownLabel = isPlayerA
            ? "PLAYER A · YOU"
            : "PLAYER B · YOU";
        const opponentLabel = isPlayerA
            ? "PLAYER B · OPPONENT"
            : "PLAYER A · OPPONENT";
        document.querySelector(
            "#white-player .player-color"
        ).textContent = ownLabel;
        document.querySelector(
            "#black-player .player-color"
        ).textContent = opponentLabel;
        document.getElementById(
            "white-player-name"
        ).textContent = ownName;
        document.getElementById(
            "black-player-name"
        ).textContent = opponentName;
    }
// =====================================================
// TURN INDICATOR
// =====================================================
    function updateTurnIndicator() {
        const ownIndicator =
            document.getElementById("white-turn-indicator");
        const opponentIndicator =
            document.getElementById("black-turn-indicator");
        const isOwnTurn = activePlayerSid === sessionId;
        ownIndicator.classList.toggle(
            "active",
            isOwnTurn
        );
        opponentIndicator.classList.toggle(
            "active",
            Boolean(activePlayerSid) && !isOwnTurn
        );
        if (isOwnTurn) {
            setGameStatus(
                "Your turn. Select a piece, then choose a highlighted destination."
            );
            footerStatus.textContent = "Your turn";
        } else {
            const opponentName =
                sessionId === playerASid
                    ? "Player B"
                    : "Player A";
            setGameStatus(
                `${opponentName}'s turn. ` +
                "You can inspect pieces but cannot move yet."
            );
            footerStatus.textContent =
                `Waiting for ${opponentName}`;
        }
    }
// =====================================================
// BOARD RENDERING
// =====================================================
    function renderBoard() {
        const fragment =
            document.createDocumentFragment();
        for (let row = 0; row < BOARD_SIZE; row++) {
            for (let col = 0; col < BOARD_SIZE; col++) {
                const square =
                    document.createElement("button");
                square.type = "button";
                square.className = "chess-square";
                square.dataset.row = String(row);
                square.dataset.col = String(col);
                square.setAttribute("role", "gridcell");
                square.classList.add(
                    (row + col) % 2 === 0
                        ? "light"
                        : "dark"
                );
                square.setAttribute(
                    "aria-label",
                    `Square ${FILES[col]}${BOARD_SIZE - row}`
                );
// Rank labels.
                if (col === 0) {
                    const rankLabel =
                        document.createElement("span");
                    rankLabel.className =
                        "square-coordinate rank";
                    rankLabel.textContent =
                        String(BOARD_SIZE - row);
                    square.appendChild(rankLabel);
                }
// File labels.
                if (row === BOARD_SIZE - 1) {
                    const fileLabel =
                        document.createElement("span");
                    fileLabel.className =
                        "square-coordinate file";
                    fileLabel.textContent = FILES[col];
                    square.appendChild(fileLabel);
                }
                const piece = board[row][col];
                if (piece !== EMPTY) {
                    renderPiece(square, piece);
                }
// Selected square.
                if (
                    selectedPosition &&
                    selectedPosition.row === row &&
                    selectedPosition.col === col
                ) {
                    square.classList.add("selected");
                    square.setAttribute(
                        "aria-pressed",
                        "true"
                    );
                } else {
                    square.setAttribute(
                        "aria-pressed",
                        "false"
                    );
                }
// Movement dots and capture borders.
// Draw server-defined movement borders and dots.
                renderMovementOverlays(square, row, col);
// Highlight the destination of the last successful move.
                renderLastTurnHighlight(square, row, col);
                fragment.appendChild(square);
            }
        }
        boardElement.replaceChildren(fragment);
    }
    function renderPiece(square, pieceValue) {
        const image = document.createElement("img");
        image.className = "chess-piece-image";
// Positive values load files like 5.svg.
// Negative values load files like -5.svg.
        image.src = `${PIECE_IMAGE_DIRECTORY}${pieceValue}.svg`;
        const pieceType = Math.abs(pieceValue);
        const pieceColour = pieceValue > 0 ? "White" : "Black";
        image.alt = `${pieceColour} piece type ${pieceType}`;
        image.draggable = false;
        image.onerror = () => {
            image.remove();
            const fallback = document.createElement("span");
            fallback.className = "piece-fallback";
            fallback.textContent = String(pieceValue);
            fallback.setAttribute(
                "aria-label",
                `${pieceColour} piece type ${pieceType}`
            );
            square.appendChild(fallback);
        };
        square.appendChild(image);
    }
// =====================================================
// SELECTING AND DESELECTING PIECES
// =====================================================
    function handleSquareClick(row, col) {
        if (
            row < 0 ||
            row >= BOARD_SIZE ||
            col < 0 ||
            col >= BOARD_SIZE
        ) {
            return;
        }
        if (
            actionPending ||
            pendingOutgoingActionRequest ||
            pendingIncomingActionRequest ||
            actionRequestResponding ||
            promotionDialogOpen ||
            gameResultDialogOpen
        ) {
            return;
        }
        const key = positionKey(row, col);
// Clicking a highlighted destination attempts a move.
        if (
            selectedPosition &&
            movementTargets.has(key)
        ) {
            if (!canMove) {
                setGameStatus(
                    "It is not your turn. You can inspect destinations " +
                    "but cannot move."
                );
                return;
            }
            executeMovement(row, col);
            return;
        }
// Clicking the selected square again deselects it.
        if (
            selectedPosition &&
            selectedPosition.row === row &&
            selectedPosition.col === col
        ) {
            selectedPosition = null;
            movementTargets.clear();
            movementOverlays = {
                square: {},
                dot: {}
            };
            renderBoard();
            setGameStatus(
                canMove
                    ? "Selection cleared. Select a piece."
                    : "Selection cleared. It is not your turn."
            );
            return;
        }
// Selecting another square replaces the old selection.
        selectedPosition = { row, col };
        movementTargets.clear();
        movementOverlays = {
            square: {},
            dot: {}
        };
        renderBoard();
// Ask the server to query the engine.
        const sent = sendMessage({
            type: "SHOW_MOVEMENT",
            match_id: matchId,
            position: [row, col]
        });
        if (sent) {
            setGameStatus(
                `Selected ${FILES[col]}${BOARD_SIZE - row}. ` +
                "Checking destinations..."
            );
        }
    }
    function handleMovementOptions(message) {
        if (
            !selectedPosition ||
            message.match_id !== matchId
        ) {
            return;
        }
        const requested = message.position;
// Ignore results for an outdated selection.
        if (
            !Array.isArray(requested) ||
            requested[0] !== selectedPosition.row ||
            requested[1] !== selectedPosition.col
        ) {
            return;
        }
        movementTargets.clear();
        movementOverlays = {
            square: {},
            dot: {}
        };
        const moves = message.moves;
        if (
            !moves ||
            typeof moves !== "object" ||
            Array.isArray(moves)
        ) {
            renderBoard();
            setGameStatus("No movement destinations were returned.");
            return;
        }
        for (const overlayType of ["square", "dot"]) {
            const colourGroups = moves[overlayType];
            if (
                !colourGroups ||
                typeof colourGroups !== "object" ||
                Array.isArray(colourGroups)
            ) {
                continue;
            }
            for (const [colour, positions] of Object.entries(colourGroups)) {
                if (!Array.isArray(positions)) {
                    continue;
                }
// Retain the server-provided colour for rendering.
                movementOverlays[overlayType][colour] = [];
                for (const position of positions) {
                    if (
                        !Array.isArray(position) ||
                        position.length !== 2 ||
                        !Number.isInteger(position[0]) ||
                        !Number.isInteger(position[1]) ||
                        position[0] < 0 ||
                        position[0] >= BOARD_SIZE ||
                        position[1] < 0 ||
                        position[1] >= BOARD_SIZE
                    ) {
                        continue;
                    }
                    movementOverlays[overlayType][colour].push(position);
                    movementTargets.add(
                        positionKey(position[0], position[1])
                    );
                }
            }
        }
        renderBoard();
        if (movementTargets.size === 0) {
            setGameStatus(
                "This square has no available destinations."
            );
        } else if (canMove) {
            setGameStatus(
                "Select a highlighted destination to move."
            );
        } else {
            setGameStatus(
                "Destinations shown. Wait for your turn before moving."
            );
        }
    }
// =====================================================
// EXECUTING MOVES
// =====================================================
    function executeMovement(targetRow, targetCol) {
        if (!selectedPosition || !canMove) {
            setGameStatus(
                "You cannot move out of turn."
            );
            return;
        }
        const sent = sendMessage({
            type: "DO_MOVEMENT",
            match_id: matchId,
            from_pos: [
                selectedPosition.row,
                selectedPosition.col
            ],
            to_pos: [
                targetRow,
                targetCol
            ]
        });
        if (sent) {
            setGameStatus(
                "Sending movement to the engine..."
            );
        }
    }
// =====================================================
// MOVE HISTORY
// =====================================================
    function renderHistory(history) {
        moveHistory.replaceChildren();
        if (
            !Array.isArray(history) ||
            history.length === 0
        ) {
            const empty =
                document.createElement("p");
            empty.className = "empty-message";
            empty.textContent = "No history yet.";
            moveHistory.appendChild(empty);
            return;
        }
        for (const entry of history) {
            const item =
                document.createElement("div");
            item.className = "move-history-row";
// Treat history entries as text, not HTML.
            item.textContent = String(entry);
            moveHistory.appendChild(item);
        }
        moveHistory.scrollTop =
            moveHistory.scrollHeight;
    }
// =====================================================
// STATUS AND NOTIFICATIONS
// =====================================================
    function setGameStatus(message) {
        gameStatus.textContent = message;
        footerStatus.textContent = message;
    }
    function setConnectionStatus(connected, message) {
        connectionText.textContent = message;
        connectionIndicator.classList.toggle(
            "connected",
            connected
        );
        connectionIndicator.classList.toggle(
            "disconnected",
            !connected
        );
    }
    function addNotification(message, type = "info") {
        const item =
            document.createElement("div");
        item.className = "notification-item";
        if (
            type === "error" ||
            type === "warning"
        ) {
            item.classList.add(type);
        }
        item.textContent = message;
        notifications.prepend(item);
// Limit the number of visible notifications.
        while (notifications.children.length > 20) {
            notifications.lastElementChild.remove();
        }
    }
// =====================================================
// UTILITIES
// =====================================================
    function hasOverlayPosition(positions, row, col) {
        return positions.some(
position =>
                position[0] === row &&
                position[1] === col
        );
    }
    function renderMovementOverlays(square, row, col) {
        for (const [colour, positions] of Object.entries(
            movementOverlays.square
        )) {
            if (!hasOverlayPosition(positions, row, col)) {
                continue;
            }
            const border = document.createElement("span");
            border.className = "movement-square-overlay";
            border.style.setProperty("--movement-colour", colour);
            border.setAttribute("aria-hidden", "true");
            square.appendChild(border);
        }
        for (const [colour, positions] of Object.entries(
            movementOverlays.dot
        )) {
            if (!hasOverlayPosition(positions, row, col)) {
                continue;
            }
            const dot = document.createElement("span");
            dot.className = "movement-dot-overlay";
            dot.style.setProperty("--movement-colour", colour);
            dot.setAttribute("aria-hidden", "true");
            square.appendChild(dot);
        }
    }
    function renderLastTurnHighlight(square, row, col) {
        const isLastMoveSource =
            lastTurnSourcePosition !== null &&
            lastTurnSourcePosition.row === row &&
            lastTurnSourcePosition.col === col;

        const isLastMoveDestination =
            lastTurnPosition !== null &&
            lastTurnPosition.row === row &&
            lastTurnPosition.col === col;

        square.classList.toggle(
            "last-turn-highlight",
            isLastMoveSource || isLastMoveDestination
        );
    }
    function positionKey(row, col) {
        return `${row},${col}`;
    }
// =====================================================
// CLEANUP
// =====================================================
    window.addEventListener("beforeunload", () => {
        clearTimeout(reconnectTimer);
        if (websocket) {
            try {
                websocket.close();
            } catch (_error) {
// The browser may already have closed the socket.
            }
        }
    });
// Start the game interface.
    initialize();
})();
