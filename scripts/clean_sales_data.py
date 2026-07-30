#!/usr/bin/env python3
"""Standalone cleaning pass for a raw sales_data.csv export shaped like
Order Date/Ship Date/Discount/Profit -- kept independent of the
scripts/common.py + validate_data.py upload pipeline, which expects a
different (lowercase date/discount/profit) column schema and reads every
file out of data/ rather than one named CSV.

Usage:
    python3 scripts/clean_sales_data.py [input.csv] [-o output.csv]

Writes the cleaned file to data/<input>_cleaned.csv by default.
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def clean(df: pd.DataFrame) -> pd.DataFrame:
    # 1. Remove exact duplicate rows
    df = df.drop_duplicates().copy()

    # 2. Convert date columns to datetime (bad/unparseable values become NaT
    # instead of raising, so one malformed row doesn't kill the whole run)
    df["Order Date"] = pd.to_datetime(df["Order Date"], format="%m/%d/%Y", errors="coerce")
    df["Ship Date"] = pd.to_datetime(df["Ship Date"], format="%m/%d/%Y", errors="coerce")

    # 3. Format discount as a percentage for readability
    df["Discount %"] = (df["Discount"] * 100).round(1)

    # 4. Flag negative profit orders (not an error -- just loss-making sales)
    df["Loss_Flag"] = df["Profit"] < 0

    return df


def main():
    parser = argparse.ArgumentParser(description="Clean a raw sales_data.csv export.")
    parser.add_argument("input", nargs="?", default="sales_data.csv",
                         help="Path to the raw CSV (default: sales_data.csv)")
    parser.add_argument("-o", "--output", help="Path to write the cleaned CSV "
                         "(default: data/<input>_cleaned.csv)")
    args = parser.parse_args()

    try:
        try:
            df = pd.read_csv(args.input, encoding="utf-8")
        except UnicodeDecodeError:
            # Not every CSV export is UTF-8 -- Excel on Windows commonly saves
            # as cp1252 (e.g. the Tableau "Sample - Superstore" dataset), where
            # bytes like 0xa0 (non-breaking space) are valid text, not garbage.
            df = pd.read_csv(args.input, encoding="cp1252")
    except FileNotFoundError:
        sys.exit(f"'{args.input}' not found.")

    missing = [c for c in ("Order Date", "Ship Date", "Discount", "Profit") if c not in df.columns]
    if missing:
        sys.exit(f"'{args.input}' is missing required column(s): {', '.join(missing)}")

    df = clean(df)

    # 5. Check for missing values
    print("Missing values per column:")
    print(df.isnull().sum())

    if args.output:
        output = args.output
    else:
        os.makedirs(DATA_DIR, exist_ok=True)
        base = os.path.splitext(os.path.basename(args.input))[0]
        output = os.path.join(DATA_DIR, f"{base}_cleaned.csv")

    df.to_csv(output, index=False)
    print(f"\nCleaned data written to {output}")


if __name__ == "__main__":
    main()
