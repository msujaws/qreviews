#!/usr/bin/env bash
# Launcher for the combined poller + dashboard process on Railway.
# Runs the polling daemon in the background and uvicorn in the foreground;
# both share the SQLite file at $QREVIEWS_DB_PATH (mounted on a Railway volume).
# Forwards SIGTERM/SIGINT to both children so deploys/restarts are clean.

set -euo pipefail

POLL_PID=0
DASH_PID=0

cleanup() {
  trap - TERM INT
  if [[ "$POLL_PID" -ne 0 ]]; then kill -TERM "$POLL_PID" 2>/dev/null || true; fi
  if [[ "$DASH_PID" -ne 0 ]]; then kill -TERM "$DASH_PID" 2>/dev/null || true; fi
  wait || true
}
trap cleanup TERM INT

# Idempotent: creates tables on a fresh volume, no-op afterwards.
python -m qreviews init-db

# Idempotent: rebinds renamed reviewer-group slugs so a group keeps its history
# across a config rename (see SLUG_RENAMES in qreviews/state.py). No-op once the
# old slugs no longer appear.
python -m qreviews migrate

python -m qreviews poll &
POLL_PID=$!

python -m qreviews dashboard --host 0.0.0.0 --port "${PORT:-8000}" &
DASH_PID=$!

# If either child exits, tear down both so Railway notices and restarts.
wait -n "$POLL_PID" "$DASH_PID"
cleanup
