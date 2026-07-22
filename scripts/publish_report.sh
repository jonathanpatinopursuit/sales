#!/usr/bin/env bash
# Publish the latest generated report to the public GitHub Pages site.
#
# This is a deliberate, manual step (not run automatically by
# generate_report.py) because docs/index.html is committed to a PUBLIC repo.
# Only run this if reports/latest.html is safe to publish publicly.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f reports/latest.html ]; then
  echo "reports/latest.html not found - run 'python3 scripts/generate_report.py' first." >&2
  exit 1
fi

cp reports/latest.html docs/index.html
git add docs/index.html
git commit -m "Publish updated sales report to GitHub Pages"
git push
echo "Published. It may take a minute for GitHub Pages to update."
