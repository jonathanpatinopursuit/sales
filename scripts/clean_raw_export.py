"""Cleaning for raw sales-export CSV/TSV files whose columns and formatting
don't already match common.py's ALL_COLUMNS shape -- unlike an .xlsx
export (numbers are already native numeric cells), a raw CSV/TSV export
commonly has currency/percent formatting baked into strings, double-dash
negatives, inconsistent capitalization, and an order-ID column not part of
the report schema at all.

This module only fixes *formatting* -- it renames columns onto the target
schema and turns "--$3,600.00" / "10%" strings into real numbers so the
existing scripts/validate_data.py:validate() (missing/blank fields, bad
dates, negative profit, duplicates) can run unmodified afterward. Business
rules live in exactly one place either way.

Two raw layouts are recognized by header, matched case-insensitively:

  "Underscore" format -- column mapping onto common.py's schema:
    Order_Date  -> date          Customer_Name    -> customer
    Product     -> product       Product_Category -> category
    Region      -> region        Units_Sold       -> quantity
    Unit_Price  -> price         Discount_Pct     -> discount
    Profit      -> profit

  Tableau "Sample - Superstore" format -- same target schema, but there's
  no unit-price column to map: `Sales` is already the line's total revenue
  (quantity * unit price * (1 - discount)), not a per-unit price. `price`
  is derived by inverting the report's own revenue formula:
    price = Sales / (Quantity * (1 - Discount))
    Order Date  -> date          Customer Name -> customer
    Product Name -> product      Category      -> category
    Region      -> region        Quantity      -> quantity
    Discount    -> discount      Profit        -> profit
    Sales       -> (used to derive price, then dropped)

Order_ID / Order ID is renamed to `order_id` and kept (not dropped) --
besides catching the same ID being reused across two different orders
(e.g. a typo'd SO-10032 that should read SO-10033), it's what lets
downstream order-level KPIs (distinct order count, average order value,
profit per order) roll multi-line orders up correctly.
"""

from __future__ import annotations

import pandas as pd

UNDERSCORE_COLUMN_MAP = {
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

SUPERSTORE_COLUMN_MAP = {
    "Order Date": "date",
    "Customer Name": "customer",
    "Product Name": "product",
    "Category": "category",
    "Region": "region",
    "Quantity": "quantity",
    "Discount": "discount",
    "Profit": "profit",
    "Sales": "sales",
}

RAW_FORMATS = [UNDERSCORE_COLUMN_MAP, SUPERSTORE_COLUMN_MAP]


def _lower_map(column_map: dict) -> dict:
    return {k.lower(): v for k, v in column_map.items()}


def _matching_format(columns) -> dict | None:
    """Return whichever known raw-export column map has every column it
    needs present in `columns` (matched case-insensitively), or None."""
    lowered = {str(c).strip().lower() for c in columns}
    for column_map in RAW_FORMATS:
        if set(_lower_map(column_map)).issubset(lowered):
            return column_map
    return None


def looks_like_raw_export(columns) -> bool:
    """True if `columns` matches a known raw-export format -- used to decide
    which pipeline a file goes through by its actual headers, not its file
    extension. A raw export can be saved as .xlsx just as easily as
    .csv/.tsv, so the extension alone isn't a reliable signal of which
    schema is inside."""
    return _matching_format(columns) is not None


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

    column_map = _matching_format(df.columns)
    is_superstore = column_map is SUPERSTORE_COLUMN_MAP
    lower_map = _lower_map(column_map)

    # Order_ID: the same ID on two different orders is a labeling problem,
    # not a real duplicate -- their business data differs, so both rows are
    # kept (dropping either would lose real revenue), just flagged so
    # whoever owns the export knows to go fix the ID. Matched
    # case-insensitively, same as the rest of this function's columns.
    #
    # Not checked for the Superstore format: there, one Order ID legitimately
    # spans multiple rows (one per line item in a multi-product order), so
    # a repeated ID is normal, not a data-quality problem -- flagging it would
    # be a false positive on nearly every multi-item order in the file.
    #
    # Either way the ID column itself is kept (renamed to order_id), not
    # dropped -- it's what lets downstream KPIs (distinct order count, AOV,
    # profit per order) roll multi-line orders up correctly instead of
    # counting every line item as its own order.
    order_id_col = None if is_superstore else next((c for c in df.columns if c.lower() == "order_id"), None)
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
        df = df.rename(columns={order_id_col: "order_id"})
    elif is_superstore:
        order_id_col = next((c for c in df.columns if c.lower() == "order id"), None)
        if order_id_col:
            df = df.rename(columns={order_id_col: "order_id"})

    rename_map = {c: lower_map[c.lower()] for c in df.columns if c.lower() in lower_map}
    df = df.rename(columns=rename_map)

    df["profit"] = _clean_currency(df["profit"])
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

    if is_superstore:
        # Discount here is already a 0-1 rate (e.g. 0.2), not a "20%"
        # string -- no percent-string parsing needed, just numeric coercion.
        df["discount"] = pd.to_numeric(df["discount"], errors="coerce")
        df["sales"] = _clean_currency(df["sales"])
        denominator = (df["quantity"] * (1 - df["discount"])).replace(0, pd.NA)
        df["price"] = df["sales"] / denominator
        df = df.drop(columns=["sales"])
    else:
        df["price"] = _clean_currency(df["price"])
        df["discount"] = _clean_percent(df["discount"])

    # Inconsistent capitalization ("electronics" vs "Electronics") would
    # otherwise split one real category into two groups downstream.
    df["category"] = df["category"].fillna("").astype(str).str.strip().str.title()
    df["region"] = df["region"].fillna("").astype(str).str.strip().str.title()
    df["customer"] = df["customer"].fillna("").astype(str).str.strip()
    df["product"] = df["product"].fillna("").astype(str).str.strip()

    keep_cols = ["date", "customer", "product", "category", "region", "quantity", "price", "discount", "profit"]
    if "order_id" in df.columns:
        keep_cols.append("order_id")
    return df[keep_cols], issues
