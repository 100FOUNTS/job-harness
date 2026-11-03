#!/bin/sh
# Runs a Python script with the first interpreter that works (python3, python, py -3).
# `-c` runs the interpreter for real, so the Windows Store stub (it exists but does not run) is skipped.
ok='import sys; sys.exit(sys.version_info < (3, 9))'
export PYTHONUTF8=1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "$ok" >/dev/null 2>&1; then exec "$py" "$@"; fi
done
if command -v py >/dev/null 2>&1 && py -3 -c "$ok" >/dev/null 2>&1; then exec py -3 "$@"; fi
echo "[job-harness] no working Python 3.9+ found (tried python3, python, py -3)" >&2
exit 1
