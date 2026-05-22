#!/usr/bin/env bash
# Install qreviews as a per-user launchd agent.
#
# Usage:   ./deploy/install-launchd.sh
# Reverse: ./deploy/uninstall-launchd.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_SRC="$REPO_ROOT/deploy/com.mozilla.qreviews.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.mozilla.qreviews.plist"
LABEL="com.mozilla.qreviews"

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
    echo "error: $REPO_ROOT/.venv/bin/python missing — run 'uv venv && uv pip install -e .' first" >&2
    exit 1
fi
if [[ ! -f "$REPO_ROOT/.env" ]]; then
    echo "error: $REPO_ROOT/.env missing — copy .env.example and fill in your tokens" >&2
    exit 1
fi

mkdir -p "$REPO_ROOT/logs" "$HOME/Library/LaunchAgents"

# Substitute the repo path into the plist template.
sed "s|@REPO@|$REPO_ROOT|g" "$PLIST_SRC" > "$PLIST_DST"

# Reload if already installed.
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST_DST"

echo "installed launchd agent: $LABEL"
echo "  plist:  $PLIST_DST"
echo "  logs:   $REPO_ROOT/logs/qreviews.{out,err}"
echo
echo "status: launchctl print gui/$UID/$LABEL | head -30"
echo "stop:   ./deploy/uninstall-launchd.sh"
