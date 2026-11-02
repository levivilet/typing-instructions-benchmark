#!/usr/bin/env bash
set -euo pipefail
openbox > /tmp/plaintext-cpu-openbox.log 2>&1 &
desktop_pid=$!
trap 'kill "$desktop_pid" 2>/dev/null || true' EXIT
for attempt in {1..100}; do
  if xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id'; then break; fi
  sleep .05
done
python3 scripts/compare_plaintext_cpu.py --baseline .tmp/plaintext-baseline.js --candidate .tmp/plaintext-candidate.js
