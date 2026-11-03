#!/bin/zsh
# Daily runner with Claude + browser. Thin wrapper: the logic is in run_daily.py.
# Usage: run_daily.sh <slug>
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 scripts/run_daily.py "$@"; fi
exec python scripts/run_daily.py "$@"
