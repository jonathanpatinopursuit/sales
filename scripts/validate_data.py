"""Intake validation for weekly sales exports.

Called per-file from common.load_data(), after that file's date, numeric
(quantity/price/discount/profit), and text (customer/product/category/region)
columns have already been coerced/normalized and discount has been converted
from a 0-100 percentage to a 0-1 rate where applicable -- validate() assumes
that's already done, so its own checks are catching genuine bad data, not
raw formatting.

Every row gets a `dq_flag` column (None for clean rows). Each check tags the
rows it affects with a label describing the issue and the action taken (e.g.
"skipped:bad_date", "clamped:discount") *before* dropping or adjusting them.
A row affected by more than one check keeps every label, ";"-joined --
tag_dq_flag() appends rather than overwrites.

Rows that get skipped (bad date, invalid quantity/price) are removed from
the returned dataframe, so their dq_flag never reaches any downstream
metric -- correctly, since a dropped row can't have contributed to any
total. Rows that are kept (blank region/category, clamped discount,
negative profit, duplicates) carry their dq_flag all the way through
common.py's concatenation and period split into analysis.py's per-group
aggregations, so a metric only ever shows an inline data-quality flag when
one of the rows *actually used to compute that specific number* was tagged.

Halting problems (missing columns, too many bad dates) raise ValueError.
common.load_data() catches that, excludes just that file, and keeps going
with whatever files remain rather than crashing the whole run -- the halt
still shows up as a HALT banner in the generated report.

Non-halting problems are also collected as a flat list of banner-level issue
dicts: {"level": "skip" | "warn", "message": str, "count": int} -- separate
from dq_flag, this drives only the aggregate counts in the report's
top-of-page Data Quality banner.
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = [
    "date",
    "product",
    "category",
    "quantity",
    "price",
    "profit",
]

# Optional -- a file missing these still gets a full report. common.py fills
# in the default (before validate() ever sees the row) when a column is
# absent from the source entirely, and tells validate() which columns it
# filled so the blank-value checks below don't fire on every single row for
# data that was never tracked in the first place.
OPTIONAL_COLUMNS = {
    "customer": "Unknown",
    "region": "Unknown",
    "discount": 0.0,
}

# Full business-column shape (required + optional) in a fixed order -- used
# wherever code needs "every column a row can carry" rather than "the
# columns a file must have to be accepted" (de-duplication, reindexing).
ALL_COLUMNS = ["date", "customer", "product", "category", "region", "quantity", "price", "discount", "profit"]

DATE_HALT_THRESHOLD = 0.05  # halt the file if more than this fraction of dates are bad

# Plain-language text for each dq_flag label, used when a report shows a row's
# reason inline -- a first-time user should never need to look up what a label
# like "clamped:discount" means.
DQ_LABEL_TEXT = {
    "flagged:invalid_region": "missing region",
    "flagged:invalid_category": "missing category",
    "clamped:discount": "discount was out of the valid 0-100% range and was corrected",
    "flagged:negative_profit": "negative profit on this row",
    "flagged:duplicate": "duplicate row",
    "flagged:invalid_customer": "missing customer",
}


def tag_dq_flag(df: pd.DataFrame, mask: pd.Series, label: str) -> None:
    """Tag df.loc[mask, 'dq_flag'] with `label`, in place. Appends (";"-joined)
    to any label a row already carries from an earlier check rather than
    overwriting it, so a row affected by two different issues keeps both --
    but won't duplicate the same label twice on one row."""
    if not mask.any():
        return

    def _combine(existing):
        if pd.isna(existing):
            return label
        labels = existing.split(";")
        return existing if label in labels else f"{existing};{label}"

    df.loc[mask, "dq_flag"] = df.loc[mask, "dq_flag"].apply(_combine)


def validate(
    df: pd.DataFrame, filename: str = "input", missing_optional: frozenset[str] = frozenset()
) -> tuple[pd.DataFrame, list[dict]]:
    """`missing_optional` names OPTIONAL_COLUMNS that weren't in the source
    file at all (common.py filled them with a default before calling this).
    Their per-row blank-value checks are skipped -- every row would otherwise
    "fail" the same check, which would just be noise for a column the file
    never had, not a real data-quality problem."""
    # Check 1: missing required columns -- halts
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required column(s) in {filename}: {missing}")

    issues: list[dict] = []
    df = df.copy()
    df["dq_flag"] = None

    # Check 2: unparseable/blank dates (already NaT by the time this runs) -- halts above threshold
    bad_dates = df["date"].isna()
    tag_dq_flag(df, bad_dates, "skipped:bad_date")
    pct = bad_dates.mean() if len(df) else 0.0
    if pct > DATE_HALT_THRESHOLD:
        raise ValueError(
            f"'{filename}' can't be used — {pct:.0%} of its rows don't have a valid date, "
            f"so this file was skipped entirely. Fix: open the file and check the 'date' "
            f"column — make sure it's named exactly 'date' and every row has a real date "
            f"(e.g. 2026-07-15), then run the report again."
        )
    elif bad_dates.any():
        issues.append({
            "level": "skip",
            "message": f"Skipped {bad_dates.sum()} row(s) in {filename} — the 'date' column was blank or unreadable for those rows.",
            "count": int(bad_dates.sum()),
        })
        df = df[~bad_dates]

    # Check 3: non-positive quantity or negative price -- skipped
    bad_qty = (df["quantity"] <= 0) | (df["price"] < 0)
    tag_dq_flag(df, bad_qty, "skipped:invalid_qty_price")
    if bad_qty.any():
        issues.append({
            "level": "skip",
            "message": f"Skipped {bad_qty.sum()} row(s) in {filename} — quantity was zero/negative or price was negative.",
            "count": int(bad_qty.sum()),
        })
        df = df[~bad_qty]

    # Check 4: blank/missing region -- kept (dropping would lose real revenue), just flagged.
    # Skipped when the file never had a region column at all (see missing_optional above).
    if "region" not in missing_optional:
        bad_region = df["region"].astype(str).str.strip() == ""
        tag_dq_flag(df, bad_region, "flagged:invalid_region")
        if bad_region.any():
            issues.append({
                "level": "warn",
                "message": f"{bad_region.sum()} row(s) have a blank/missing region in {filename}.",
                "count": int(bad_region.sum()),
            })

    # Check 5: blank/missing category -- kept, just flagged
    bad_category = df["category"].astype(str).str.strip() == ""
    tag_dq_flag(df, bad_category, "flagged:invalid_category")
    if bad_category.any():
        issues.append({
            "level": "warn",
            "message": f"{bad_category.sum()} row(s) have a blank/missing category in {filename}.",
            "count": int(bad_category.sum()),
        })

    # Check 5b: blank/missing customer -- kept, just flagged (same reasoning as region/category)
    if "customer" not in missing_optional:
        bad_customer = df["customer"].astype(str).str.strip() == ""
        tag_dq_flag(df, bad_customer, "flagged:invalid_customer")
        if bad_customer.any():
            issues.append({
                "level": "warn",
                "message": f"{bad_customer.sum()} row(s) have a blank/missing customer in {filename}.",
                "count": int(bad_customer.sum()),
            })

    # Check 6: discount outside 0-100% (post-normalization, so this really is bad data) -- clamped, kept
    bad_disc = (df["discount"] < 0) | (df["discount"] > 1)
    tag_dq_flag(df, bad_disc, "clamped:discount")
    if bad_disc.any():
        issues.append({
            "level": "warn",
            "message": f"Corrected {bad_disc.sum()} discount value(s) in {filename} that were outside the valid 0-100% range.",
            "count": int(bad_disc.sum()),
        })
        df["discount"] = df["discount"].clip(0, 1)

    # Check 7: negative profit on a single row -- not necessarily wrong (could be a
    # real loss-leader or return), but worth surfacing since it can also be a
    # data-entry error -- kept either way, just flagged
    bad_profit = df["profit"] < 0
    tag_dq_flag(df, bad_profit, "flagged:negative_profit")
    if bad_profit.any():
        issues.append({
            "level": "warn",
            "message": f"{bad_profit.sum()} row(s) have negative profit in {filename}.",
            "count": int(bad_profit.sum()),
        })

    # Check 8: duplicate rows within this file (not removed -- legit repeat orders can
    # look identical). Must run last, and compares only the business columns (not
    # dq_flag), or two otherwise-identical rows tagged differently by earlier checks
    # would wrongly look distinct.
    dupe_mask = df.duplicated(subset=ALL_COLUMNS, keep=False)
    tag_dq_flag(df, dupe_mask, "flagged:duplicate")
    dupes = int(df.duplicated(subset=ALL_COLUMNS).sum())
    if dupes:
        issues.append({
            "level": "warn",
            "message": f"Found {dupes} duplicate row(s) within {filename} — not removed.",
            "count": dupes,
        })

    return df, issues
