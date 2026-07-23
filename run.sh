#!/bin/bash
# Generates the Sales Organizer report from every .xlsx file in data/.
#
# Usage:
#     ./run.sh
#
# Writes reports/latest.html and reports/latest.xlsx (always the newest
# report, same filename every time) plus a dated copy of each.
set -e
cd "$(dirname "$0")"
python3 scripts/generate_report.py
