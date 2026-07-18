#!/bin/bash
set -e
export PATH="/opt/homebrew/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")"

echo "=== $(date) ==="
/opt/homebrew/bin/python3 fetch_data.py

if ! git diff --quiet data/metrics.json; then
  git add data/metrics.json
  git commit -m "Auto-refresh metrics $(date '+%Y-%m-%d %H:%M')"
  git push
  echo "Pushed update."
else
  echo "No change, skipping push."
fi
