#!/usr/bin/env bash
#
# build-docker.sh - turn the code/ source into a Docker image (and optionally push it).
#
# Usage:
#   ./script/build-docker.sh [clean|build|tag|verify|smoke|push|all]
#
#   all    (default)  clean -> build -> tag -> verify -> smoke -> push
#
# Each step can also be run on its own, e.g. `./script/build-docker.sh build`.
#
# Overridable via environment variables:
#   IMAGE_NAME     local image name          (default: anarchy-chess)
#   IMAGE_TAG      tag                       (default: latest)
#   PUSH_IMAGE     hub target for push       (default: blazeleo2005/anarchy-chess)
#   SMOKE_PORT     host port for smoke test  (default: 8123)
#   SKIP_PUSH=1    skip the final push step

set -euo pipefail

# --- locate the repo root (parent of this script's directory) -------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CODE_DIR="$ROOT/code"
DOCKERFILE="$CODE_DIR/Dockerfile"

IMAGE_NAME="${IMAGE_NAME:-anarchy-chess}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
LOCAL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
PUSH_IMAGE="${PUSH_IMAGE:-blazeleo2005/anarchy-chess}"
SMOKE_PORT="${SMOKE_PORT:-8123}"
SMOKE_CONTAINER="anarchy-smoke-$$"

# App files that must be byte-identical between the image and the repo.
CORE_FILES=(
  main.py
  engine.py
  go_where.py
  constants.py
  promote.py
  guide.md
  static/js/game.js
  static/css/style.css
  templates/game.html
  templates/index.html
)

log() { printf '\n\033[1;34m== %s ==\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
# clean: remove temp artifacts so they are not baked into the image
# ---------------------------------------------------------------------------
cmd_clean() {
  log "clean: removing temp artifacts"
  find "$CODE_DIR" \
    \( -name "_verify*" -o -name "_trace*" -o -name "repro_*" -o -name "*.pyc" \) \
    -type f -print -delete 2>/dev/null || true
  find "$CODE_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
  echo "cleaned."
}

# ---------------------------------------------------------------------------
# build: docker build from the code/ context
# ---------------------------------------------------------------------------
cmd_build() {
  log "build: $LOCAL_IMAGE"
  [ -f "$DOCKERFILE" ] || { echo "no Dockerfile at $DOCKERFILE"; exit 1; }
  docker build -f "$DOCKERFILE" -t "$LOCAL_IMAGE" "$CODE_DIR"
}

# ---------------------------------------------------------------------------
# tag: re-tag the local image under the hub name
# ---------------------------------------------------------------------------
cmd_tag() {
  log "tag: ${PUSH_IMAGE}:${IMAGE_TAG}"
  docker tag "$LOCAL_IMAGE" "${PUSH_IMAGE}:${IMAGE_TAG}"
}

# ---------------------------------------------------------------------------
# verify: every core file in the image matches the repo; no stray temp files
# ---------------------------------------------------------------------------
cmd_verify() {
  log "verify: image contents match repo"
  local img_hashes fail=0
  img_hashes="$(docker run --rm --entrypoint sh "$LOCAL_IMAGE" \
    -c "cd /app && md5sum ${CORE_FILES[*]}" 2>&1)" || {
      echo "verify: could not read files from image:"; echo "$img_hashes"; exit 1; }

  local file ih rh
  for file in "${CORE_FILES[@]}"; do
    ih="$(printf '%s\n' "$img_hashes" | awk -v f="$file" '$2==f{print $1; exit}')"
    rh="$(md5sum "$CODE_DIR/$file" 2>/dev/null | awk '{print $1}')"
    if [ -n "$ih" ] && [ "$ih" = "$rh" ]; then
      printf '  SAME   %s\n' "$file"
    else
      printf '  DIFFER %s (image=%s repo=%s)\n' "$file" "${ih:-missing}" "${rh:-missing}"
      fail=1
    fi
  done

  local strays
  strays="$(docker run --rm --entrypoint sh "$LOCAL_IMAGE" \
    -c 'ls /app/_verify* /app/_trace* /app/repro_* 2>/dev/null || true')"
  if [ -n "$strays" ]; then
    echo "  stray temp files found in image:"; echo "$strays"; fail=1
  fi

  if [ "$fail" -ne 0 ]; then echo "VERIFY FAILED"; exit 1; fi
  echo "verify passed."
}

# ---------------------------------------------------------------------------
# smoke: run a container and probe the key endpoints
# ---------------------------------------------------------------------------
cmd_smoke() {
  log "smoke: run container and probe endpoints"
  docker rm -f "$SMOKE_CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$SMOKE_CONTAINER" -p "${SMOKE_PORT}:8000" "$LOCAL_IMAGE" >/dev/null

  local base="http://127.0.0.1:${SMOKE_PORT}" i
  for i in $(seq 1 30); do
    curl -sf -o /dev/null "$base/" && break
    sleep 1
  done

  local sid
  sid="$(curl -s -X POST "$base/api/create-session" \
    -H 'Content-Type: application/json' -d '{"username":"smoke"}' \
    | sed -n 's/.*"sid":"\([^"]*\)".*/\1/p')"
  if [ -z "$sid" ]; then
    echo "smoke: failed to create a session"; docker rm -f "$SMOKE_CONTAINER" >/dev/null 2>&1; exit 1
  fi

  local path code ok=0
  for path in "/" "/lobby?sid=$sid" "/guide?sid=$sid" "/static/js/game.js" "/static/css/style.css"; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$base$path")"
    printf '  HTTP %s  %s\n' "$code" "$path"
    [ "$code" = "200" ] || ok=1
  done

  if docker logs "$SMOKE_CONTAINER" 2>&1 | grep -qiE 'traceback|exception'; then
    echo "smoke: found errors in container logs"; ok=1
  fi

  docker rm -f "$SMOKE_CONTAINER" >/dev/null 2>&1 || true
  if [ "$ok" -ne 0 ]; then echo "SMOKE FAILED"; exit 1; fi
  echo "smoke passed."
}

# ---------------------------------------------------------------------------
# push: push to Docker Hub (skippable with SKIP_PUSH=1)
# ---------------------------------------------------------------------------
cmd_push() {
  if [ "${SKIP_PUSH:-0}" = "1" ]; then
    log "push: skipped (SKIP_PUSH=1)"
    return
  fi
  log "push: ${PUSH_IMAGE}:${IMAGE_TAG}"
  docker push "${PUSH_IMAGE}:${IMAGE_TAG}"
}

# ---------------------------------------------------------------------------
step="${1:-all}"
case "$step" in
  clean)  cmd_clean ;;
  build)  cmd_build ;;
  tag)    cmd_tag ;;
  verify) cmd_verify ;;
  smoke)  cmd_smoke ;;
  push)   cmd_push ;;
  all)
    cmd_clean; cmd_build; cmd_tag; cmd_verify; cmd_smoke; cmd_push
    ;;
  *)
    echo "unknown step: $step" >&2
    echo "usage: $0 [clean|build|tag|verify|smoke|push|all]" >&2
    exit 2
    ;;
esac
