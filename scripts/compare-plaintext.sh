#!/usr/bin/env bash
set -euo pipefail
openbox > /tmp/plaintext-comparison-openbox.log 2>&1 &
desktop_pid=$!
trap 'kill "$desktop_pid" 2>/dev/null || true' EXIT
for attempt in {1..100}; do
  if xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id'; then break; fi
  sleep .05
done
sudo --preserve-env=DISPLAY,XAUTHORITY,BENCHMARK_RUN_URL python3 scripts/compare_plaintext.py \
  --perf "$1" --baseline .tmp/plaintext-baseline.js --candidate .tmp/plaintext-candidate.js --repeats 30
