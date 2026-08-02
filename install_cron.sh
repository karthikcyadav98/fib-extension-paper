#!/bin/bash
# Runs the paper account every hour so the 7-day test keeps advancing.
# Forex bars are 1h and crypto 4h, so hourly is the right cadence.
#
#   ./install_cron.sh          install
#   ./install_cron.sh remove   uninstall
#
# Safe to re-run: it replaces its own line and leaves other crontab entries alone.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3)"
TAG="# fib-extension-paper"
LINE="0 * * * * cd $DIR && $PY run.py update >> $DIR/state/cron.log 2>&1 $TAG"

current="$(crontab -l 2>/dev/null || true)"
cleaned="$(printf '%s\n' "$current" | grep -v -F "$TAG" || true)"

if [ "${1:-install}" = "remove" ]; then
  printf '%s\n' "$cleaned" | crontab -
  echo "removed the hourly update job"
else
  printf '%s\n%s\n' "$cleaned" "$LINE" | grep -v '^$' | crontab -
  echo "installed: hourly 'run.py update'"
  echo "log -> $DIR/state/cron.log"
  echo
  echo "If cron is blocked by macOS privacy settings, grant Full Disk Access to"
  echo "/usr/sbin/cron in System Settings > Privacy & Security, or just run"
  echo "'python3 run.py update' by hand a few times a day instead."
fi
