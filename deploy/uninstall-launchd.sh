#!/usr/bin/env bash
# Uninstall the qreviews launchd agent.
set -euo pipefail

LABEL="com.mozilla.qreviews"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || echo "(agent was not loaded)"
rm -f "$PLIST_DST"
echo "uninstalled $LABEL"
