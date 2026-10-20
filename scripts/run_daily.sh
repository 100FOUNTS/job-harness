#!/bin/zsh
# Daily runner (launchd). Usage: run_daily.sh <slug>
# - random start delay (0–20 min) so it never runs at the exact same minute
# - lock: never two runs at once; STOP file: kill switch; logs per day
# - discovery and triage are scripts (no LLM); Claude only judges, writes and applies
set -u
SLUG="${1:?usage: run_daily.sh <slug>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAND="$ROOT/candidates/$SLUG"
LOGDIR="$CAND/logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%F).log"
LOCK="/tmp/job-harness-$SLUG.lock"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

exec >>"$LOG" 2>&1
echo "=== $(date) start ($SLUG)"
[[ -f "$ROOT/STOP" || -f "$CAND/STOP" ]] && { echo "STOP file present, exiting"; exit 0; }
mkdir "$LOCK" 2>/dev/null || { echo "another run is active, exiting"; exit 0; }
trap 'rmdir "$LOCK"' EXIT

[[ "${JOB_NO_DELAY:-0}" == "1" ]] || sleep $(( RANDOM % 1200 ))
cd "$ROOT"

python3 scripts/discover.py "$SLUG" || echo "discover failed"
python3 scripts/triage.py "$SLUG" || echo "triage failed"

# Claude: judge the shortlist, tailor documents, apply (or dry-run), report. A cheaper model is enough here.
caffeinate -i claude -p "/job-daily $SLUG" \
  --chrome \
  --model "${JOB_MODEL:-sonnet}" \
  --permission-mode acceptEdits \
  --allowedTools "Agent Bash(python3 scripts/*) Bash(bin/job *) Bash(./bin/job *) Bash(pdftoppm *) Read Write Edit Glob Grep mcp__claude-in-chrome__*" \
  --output-format text || echo "claude run failed"

python3 scripts/report.py "$SLUG" --notify || true
echo "=== $(date) end"
