#!/bin/zsh
# Daily runner in prepare mode (scripts only). Thin wrapper: the logic is in run_prepare.py (also used on Windows/Linux).
# Usage: run_prepare.sh <slug>
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 scripts/run_prepare.py "$@"; fi
exec python scripts/run_prepare.py "$@"
