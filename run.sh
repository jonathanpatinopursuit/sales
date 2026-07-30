#!/bin/bash
# Generates the Sales Organizer report from every .xlsx file in data/.
#
# Usage:
#     ./run.sh
#
# If sales_data.csv exists in the project root, it's cleaned first (see
# scripts/clean_sales_data.py) and the result dropped into data/, before
# the report is generated from everything in data/.
#
# Writes reports/latest.html and reports/latest.xlsx (always the newest
# report, same filename every time) plus a dated copy of each.
set -e
cd "$(dirname "$0")"
if [ -f "sales_data.csv" ]; then
    python3 scripts/clean_sales_data.py sales_data.csv
fi
python3 scripts/generate_report.py
