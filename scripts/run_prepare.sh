#!/bin/zsh
# Daily runner in prepare mode: scripts only (no LLM, no browser).
# discover → triage → prepare (top jobs, documents, package) → report + notification.
set -u
SLUG="${1:?usage: run_prepare.sh <slug>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAND="$ROOT/candidates/$SLUG"
LOGDIR="$CAND/logs"; mkdir -p "$LOGDIR"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
exec >>"$LOGDIR/$(date +%F).log" 2>&1
echo "=== $(date) prepare start ($SLUG)"
[[ -f "$ROOT/STOP" || -f "$CAND/STOP" ]] && { echo "STOP file present, exiting"; exit 0; }
cd "$ROOT"
python3 scripts/discover.py "$SLUG" || echo "discover failed"
python3 scripts/triage.py "$SLUG" --max 40 || echo "triage failed"
python3 scripts/prepare.py "$SLUG" --max "${JOB_PREPARE_MAX:-15}" || echo "prepare failed"
MODE=$(python3 -c "import json;print(json.load(open('candidates/$SLUG/state.json'))['mode'])")
if [[ "$MODE" == "easy" || "$MODE" == "full" ]]; then
  python3 scripts/apply.py "$SLUG" || echo "apply failed"
fi
python3 scripts/cleanup.py "$SLUG" --days 15 || echo "cleanup failed"
python3 scripts/report.py "$SLUG" --notify || true
echo "=== $(date) prepare end"
