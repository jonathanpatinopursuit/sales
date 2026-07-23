"""Intake validation for weekly sales exports.

Called per-file from common.load_data(), after that file's date column has
been parsed (pd.to_datetime(errors="coerce")) and its numeric columns coerced
and discount normalized to a 0-1 rate — validate() assumes that's already
done, so its own checks are catching genuine bad data, not raw formatting.
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = [
    "date",
    "customer",
    "product",
    "category",
    "region",
    "quantity",
    "price",
    "discount",
    "profit",
]

DATE_HALT_THRESHOLD = 0.05  # halt the file if more than this fraction of dates are bad


def validate(df: pd.DataFrame, filename: str = "input") -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []

    # Check 1: missing required columns
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"HALT: Missing required column(s) in {filename}: {missing}")

    # Check 2: unparseable/blank dates (already NaT by the time this runs)
    bad_dates = df["date"].isna()
    pct = bad_dates.mean() if len(df) else 0.0
    if pct > DATE_HALT_THRESHOLD:
        raise ValueError(
            f"HALT: {pct:.1%} of dates unparseable in {filename} — likely wrong column/format."
        )
    elif bad_dates.any():
        warnings.append(f"Skipped {bad_dates.sum()} row(s) with unparseable/blank dates in {filename} ({pct:.1%}).")
        df = df[~bad_dates]

    # Check 3: non-positive quantity or negative price
    bad_qty = (df["quantity"] <= 0) | (df["price"] < 0)
    if bad_qty.any():
        warnings.append(f"Skipped {bad_qty.sum()} row(s) with non-positive quantity or negative price in {filename}.")
        df = df[~bad_qty]

    # Check 4: discount outside 0-100% (post-normalization, so this really is bad data)
    bad_disc = (df["discount"] < 0) | (df["discount"] > 1)
    if bad_disc.any():
        warnings.append(f"Clamped {bad_disc.sum()} discount value(s) to [0, 1] in {filename}.")
        df = df.copy()
        df["discount"] = df["discount"].clip(0, 1)

    # Check 5: duplicate rows within this file
    dupes = int(df.duplicated().sum())
    if dupes:
        warnings.append(f"Found {dupes} duplicate row(s) within {filename} — not removed.")

    return df, warnings
