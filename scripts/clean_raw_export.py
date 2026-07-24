"""Cleaning for raw sales-export CSV/TSV files whose columns and formatting
don't already match common.py's REQUIRED_COLUMNS shape -- unlike an .xlsx
export (numbers are already native numeric cells), a raw CSV/TSV export
commonly has currency/percent formatting baked into strings, double-dash
negatives, inconsistent capitalization, and an order-ID column not part of
the report schema at all.

This module only fixes *formatting* -- it renames columns onto the target
schema and turns "--$3,600.00" / "10%" strings into real numbers so the
existing scripts/validate_data.py:validate() (missing/blank fields, bad
dates, negative profit, duplicates) can run unmodified afterward. Business
rules live in exactly one place either way.

Column mapping onto common.py's schema:
    Order_Date  -> date          Customer_Name    -> customer
    Product     -> product       Product_Category -> category
    Region      -> region        Units_Sold       -> quantity
    Unit_Price  -> price         Discount_Pct     -> discount
    Profit      -> profit

Order_ID is *not* part of the report schema and is dropped after use --
it exists here only to catch the same ID being reused across two
different orders (e.g. a typo'd SO-10032 that should read SO-10033).
"""

from __future__ import annotations

import pandas as pd

RAW_COLUMN_MAP = {
    "Order_Date": "date",
    "Customer_Name": "customer",
    "Product": "product",
    "Product_Category": "category",
    "Region": "region",
    "Units_Sold": "quantity",
    "Unit_Price": "price",
    "Discount_Pct": "discount",
    "Profit": "profit",
}
_RAW_COLUMN_MAP_LOWER = {k.lower(): v for k, v in RAW_COLUMN_MAP.items()}


def looks_like_raw_export(columns) -> bool:
    """True if `columns` has every column this raw-export format needs,
    matched case-insensitively -- used to decide which pipeline a file goes
    through by its actual headers, not its file extension. A raw export can
    be saved as .xlsx just as easily as .csv/.tsv, so the extension alone
    isn't a reliable signal of which schema is inside."""
    lowered = {str(c).strip().lower() for c in columns}
    return set(_RAW_COLUMN_MAP_LOWER).issubset(lowered)


def _clean_currency(series: pd.Series) -> pd.Series:
    """'--$3,600.00' -> -3600.00. A leading '--' is this export's stand-in
    for a minus sign (not two separate values), so it's collapsed to a
    single '-' before the '$' and thousands-comma are stripped."""
    s = series.astype(str).str.strip()
    s = s.str.replace(r"^--", "-", regex=True)
    s = s.str.replace(r"[$,]", "", regex=True)
    return pd.to_numeric(s, errors="coerce")


def _clean_percent(series: pd.Series) -> pd.Series:
    """'10%' -> 0.10, matching the 0-1 discount rate the rest of the
    pipeline already expects (see common.py)."""
    s = series.astype(str).str.strip().str.replace("%", "", regex=False)
    return pd.to_numeric(s, errors="coerce") / 100.0


def clean_raw_export(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Clean a raw Order_ID/Order_Date/.../Profit-shaped export into
    common.py's (date, customer, product, category, region, quantity,
    price, discount, profit) shape.

    Returns (df, issues) -- issues uses the same {level, message, count}
    shape validate_data.py's checks produce, so it folds into the same
    Data Quality banner rather than a second, separate one. Nothing here
    raises: every problem found is flagged in `issues`, not stopped on.
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    issues: list[dict] = []

    # Order_ID: the same ID on two different orders is a labeling problem,
    # not a real duplicate -- their business data differs, so both rows are
    # kept (dropping either would lose real revenue), just flagged so
    # whoever owns the export knows to go fix the ID. Matched
    # case-insensitively, same as the rest of this function's columns.
    order_id_col = next((c for c in df.columns if c.lower() == "order_id"), None)
    if order_id_col:
        dupe_ids = sorted(df.loc[df[order_id_col].duplicated(keep=False), order_id_col].astype(str).unique().tolist())
        if dupe_ids:
            issues.append({
                "level": "warn",
                "message": (
                    f"Order_ID reused across different orders: {', '.join(dupe_ids)} -- "
                    f"likely a typo (e.g. a repeated ID that should be the next number in "
                    f"sequence). Rows were kept since their order details differ, but the "
                    f"ID(s) need fixing at the source."
                ),
                "count": len(dupe_ids),
            })
        df = df.drop(columns=[order_id_col])

    rename_map = {c: _RAW_COLUMN_MAP_LOWER[c.lower()] for c in df.columns if c.lower() in _RAW_COLUMN_MAP_LOWER}
    df = df.rename(columns=rename_map)

    df["price"] = _clean_currency(df["price"])
    df["profit"] = _clean_currency(df["profit"])
    df["discount"] = _clean_percent(df["discount"])
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

    # Inconsistent capitalization ("electronics" vs "Electronics") would
    # otherwise split one real category into two groups downstream.
    df["category"] = df["category"].fillna("").astype(str).str.strip().str.title()
    df["region"] = df["region"].fillna("").astype(str).str.strip().str.title()
    df["customer"] = df["customer"].fillna("").astype(str).str.strip()
    df["product"] = df["product"].fillna("").astype(str).str.strip()

    keep_cols = ["date", "customer", "product", "category", "region", "quantity", "price", "discount", "profit"]
    return df[keep_cols], issues
