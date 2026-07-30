"""Core analysis functions used by the report generator."""

from __future__ import annotations

import pandas as pd

from common import pct_change
from validate_data import DQ_LABEL_TEXT

DECLINE_FLAG_THRESHOLD = -15.0   # % revenue drop vs prior period
LOW_MARGIN_THRESHOLD = 0.10      # margin below 10% is flagged
HIGH_DISCOUNT_THRESHOLD = 0.15   # average discount above 15% is "big"
NEGATIVE_PROFIT_FLAG = True      # always flag any segment with negative total profit


def _dq_summary(flags: pd.Series):
    """Plain-language summary of dq_flag values among one group's rows, or
    None if none of them are tagged. Only rows actually inside this group
    are considered, so a metric is only annotated when a row that literally
    contributed to it was flagged -- never because something nearby was.
    Uses DQ_LABEL_TEXT so the reason is self-explanatory without needing to
    know what an internal label like "clamped:discount" means."""
    flagged = flags.dropna()
    if flagged.empty:
        return None
    counts: dict[str, int] = {}
    for val in flagged:
        for label in str(val).split(";"):
            counts[label] = counts.get(label, 0) + 1
    parts = [f"{DQ_LABEL_TEXT.get(label, label)} ({n})" for label, n in sorted(counts.items())]
    row_word = "row" if len(flagged) == 1 else "rows"
    return f"{len(flagged)} {row_word} affected: " + ", ".join(parts)


def _attach_dq_notes(df: pd.DataFrame, source_df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Merge a per-group dq_note column onto df, computed from source_df's
    dq_flag column grouped by `by`. source_df must be the exact rows that
    were aggregated to produce df's numbers (e.g. current_df), so the note
    is always period- and group-scoped correctly."""
    if "dq_flag" not in source_df.columns or source_df.empty:
        df["dq_note"] = None
        return df
    notes = source_df.groupby(by)["dq_flag"].apply(_dq_summary).reset_index(name="dq_note")
    return df.merge(notes, on=by, how="left")


def compute_headline_totals(current_df: pd.DataFrame):
    """Total revenue/profit/margin for the current period. `total_profit` and
    `overall_margin` come back as None when no row in current_df has a real
    profit value (profit is optional -- see validate_data.OPTIONAL_COLUMNS),
    so callers can hide profit/margin from a report instead of showing a
    misleading $0 / 0%."""
    total_revenue = current_df["revenue"].sum()
    # min_count=1: an all-NaN "profit" column (never provided) sums to NaN,
    # not pandas' default 0 for an empty/all-NaN sum -- that 0 would look
    # like a real (and alarmingly bad) total rather than "not available".
    total_profit = current_df["profit"].sum(min_count=1)
    if pd.isna(total_profit):
        return total_revenue, None, None
    overall_margin = (total_profit / total_revenue * 100) if total_revenue else 0.0
    return total_revenue, total_profit, overall_margin


def compute_kpis(current_df: pd.DataFrame, prior_df: pd.DataFrame | None = None) -> dict:
    """Order-, customer-, and target-level KPIs for the current period,
    following the published calculation spec:

        Gross Sales           = Quantity x Price
        Discount Amount       = Gross Sales x Discount %
        Net Sales             = Gross Sales - Discount Amount  (== `revenue`)
        Average Order Value   = Net Sales / distinct orders
        Average Selling Price = Net Sales / units sold
        Discount Rate %       = Discount Amount / Gross Sales x 100
        Profit per Order      = Total Profit / distinct orders
        Target Achievement %  = Net Sales / Sales Target x 100
        Sales/Profit Growth % = pct_change(current, prior)

    A metric whose formula needs a field this dataset doesn't have (no
    `order_id` column at all, no `sales_target`, no prior period) comes back
    None rather than 0 or a fabricated number -- callers should render None
    as "n/a" / "Not available from source data", never as a real value.
    """
    keys = (
        "gross_sales", "discount_amount", "net_sales", "total_profit", "overall_margin",
        "num_orders", "units_sold", "avg_order_value", "avg_selling_price", "discount_rate",
        "profit_per_order", "distinct_customers", "sales_target", "target_achievement",
        "sales_growth", "profit_growth", "negative_profit_orders", "discounted_orders",
    )
    if current_df.empty:
        return {k: None for k in keys}

    gross_sales = current_df["gross_sales"].sum()
    discount_amount = current_df["discount_amount"].sum()
    net_sales, total_profit, overall_margin = compute_headline_totals(current_df)

    has_order_id = "order_id" in current_df.columns
    num_orders = current_df["order_id"].nunique() if has_order_id else len(current_df)
    units_sold = current_df["quantity"].sum()

    avg_order_value = (net_sales / num_orders) if num_orders else None
    avg_selling_price = (net_sales / units_sold) if units_sold else None
    discount_rate = (discount_amount / gross_sales * 100) if gross_sales else None
    profit_per_order = (total_profit / num_orders) if (total_profit is not None and num_orders) else None
    distinct_customers = current_df["customer"].nunique() if "customer" in current_df.columns else None

    sales_target = None
    target_achievement = None
    if "sales_target" in current_df.columns:
        target_sum = current_df["sales_target"].sum(min_count=1)
        if pd.notna(target_sum) and target_sum:
            sales_target = target_sum
            target_achievement = net_sales / target_sum * 100

    sales_growth = None
    profit_growth = None
    if prior_df is not None and not prior_df.empty:
        prior_net_sales = prior_df["revenue"].sum()
        sales_growth = pct_change(net_sales, prior_net_sales)
        if total_profit is not None:
            prior_profit = prior_df["profit"].sum(min_count=1)
            if pd.notna(prior_profit):
                profit_growth = pct_change(total_profit, prior_profit)

    negative_profit_orders = None
    discounted_orders = None
    if has_order_id:
        if total_profit is not None:
            by_order_profit = current_df.groupby("order_id")["profit"].sum(min_count=1)
            negative_profit_orders = int((by_order_profit < 0).sum())
        by_order_discount = current_df.groupby("order_id")["discount_amount"].sum()
        discounted_orders = int((by_order_discount > 0).sum())

    return {
        "gross_sales": gross_sales,
        "discount_amount": discount_amount,
        "net_sales": net_sales,
        "total_profit": total_profit,
        "overall_margin": overall_margin,
        "num_orders": num_orders,
        "units_sold": units_sold,
        "avg_order_value": avg_order_value,
        "avg_selling_price": avg_selling_price,
        "discount_rate": discount_rate,
        "profit_per_order": profit_per_order,
        "distinct_customers": distinct_customers,
        "sales_target": sales_target,
        "target_achievement": target_achievement,
        "sales_growth": sales_growth,
        "profit_growth": profit_growth,
        "negative_profit_orders": negative_profit_orders,
        "discounted_orders": discounted_orders,
    }


# Discount bands, in evaluation order -- (lower bound exclusive, upper bound
# inclusive, label). A row with discount == 0 lands in "No discount" even
# though 0 also satisfies "> 0.0 through 0.05"; _discount_band checks that
# case first specifically so the two bands don't overlap.
DISCOUNT_BAND_ORDER = ["No discount", "Above 0% through 5%", "Above 5% through 10%", "Above 10% through 20%", "Above 20%"]


def _discount_band(discount: float) -> str:
    if pd.isna(discount) or discount <= 0:
        return "No discount"
    if discount <= 0.05:
        return "Above 0% through 5%"
    if discount <= 0.10:
        return "Above 5% through 10%"
    if discount <= 0.20:
        return "Above 10% through 20%"
    return "Above 20%"


def discount_band_summary(current_df: pd.DataFrame) -> pd.DataFrame:
    """Per-row discounts bucketed into bands (No discount / 0-5% / 5-10% /
    10-20% / >20%), each with distinct orders, gross sales, discount amount,
    net sales, profit, margin, and average order value -- lets a "how much
    are steep discounts actually costing us" question be answered directly
    instead of only per-product/per-category."""
    cols = ["band", "orders", "gross_sales", "discount_amount", "revenue", "profit", "margin", "avg_order_value"]
    if current_df.empty:
        return pd.DataFrame(columns=cols)

    df = current_df.copy()
    df["band"] = df["discount"].apply(_discount_band)
    has_order_id = "order_id" in df.columns

    agg = {
        "gross_sales": ("gross_sales", "sum"),
        "discount_amount": ("discount_amount", "sum"),
        "revenue": ("revenue", "sum"),
        "profit": ("profit", lambda s: s.sum(min_count=1)),
    }
    g = df.groupby("band").agg(**agg).reset_index()
    g["orders"] = df.groupby("band")["order_id"].nunique().values if has_order_id else df.groupby("band").size().values
    g["margin"] = (g["profit"] / g["revenue"].replace(0, pd.NA)).astype(float)
    g["avg_order_value"] = (g["revenue"] / g["orders"].replace(0, pd.NA)).astype(float)

    g["band"] = pd.Categorical(g["band"], categories=DISCOUNT_BAND_ORDER, ordered=True)
    g = g.sort_values("band").reset_index(drop=True)
    g["band"] = g["band"].astype(str)
    return g[cols]


def discount_band_product_summary(current_df: pd.DataFrame) -> pd.DataFrame:
    """Every product's discount-band breakdown -- same per-product metrics as
    discount_analysis() (avg discount, revenue, profit, margin, margin-risk
    flag), but grouped by (band, product) instead of product alone, so a
    report can show exactly which products fall in each band. Returns every
    product in every band (never capped) -- same reasoning as
    discount_analysis(): a display layer decides how much to show at once,
    this function never discards data."""
    cols = ["band", "product", "avg_discount", "revenue", "profit", "margin", "margin_risk"]
    if current_df.empty:
        return pd.DataFrame(columns=cols)
    df = current_df.copy()
    df["band"] = df["discount"].apply(_discount_band)
    g = df.groupby(["band", "product"]).agg(
        avg_discount=("discount", "mean"),
        revenue=("revenue", "sum"),
        profit=("profit", lambda s: s.sum(min_count=1)),
    ).reset_index()
    g["margin"] = (g["profit"] / g["revenue"].replace(0, pd.NA)).astype(float)
    g["margin_risk"] = (g["avg_discount"] >= HIGH_DISCOUNT_THRESHOLD) & (g["margin"] < LOW_MARGIN_THRESHOLD)
    g["band"] = pd.Categorical(g["band"], categories=DISCOUNT_BAND_ORDER, ordered=True)
    g = g.sort_values(["band", "avg_discount"], ascending=[True, False]).reset_index(drop=True)
    g["band"] = g["band"].astype(str)
    return g[cols]


def monthly_summary(data: pd.DataFrame) -> pd.DataFrame:
    """Revenue/profit/margin for every calendar month present in `data`,
    sorted chronologically -- lets a user look up any single month's totals
    (e.g. January) directly, not just the two most recent periods the rest
    of the report compares against each other. `data` should be the full,
    unsplit dataset (before common.split_periods()), so every month shows up
    here even though only the latest two ever become current/prior."""
    if data.empty:
        return pd.DataFrame(columns=["period", "revenue", "profit", "margin"])
    g = data.groupby("period").agg(
        revenue=("revenue", "sum"),
        profit=("profit", lambda s: s.sum(min_count=1)),
    ).reset_index()
    g = g.sort_values("period")
    g["margin"] = (g["profit"] / g["revenue"].replace(0, pd.NA)).astype(float)
    g["period"] = g["period"].astype(str)
    return g.reset_index(drop=True)


def grouped_summary(current_df: pd.DataFrame, prior_df: pd.DataFrame, by: str) -> pd.DataFrame:
    def agg(df):
        if df.empty:
            return pd.DataFrame(columns=[by, "revenue", "profit", "quantity", "avg_discount"])
        g = df.groupby(by).agg(
            revenue=("revenue", "sum"),
            profit=("profit", lambda s: s.sum(min_count=1)),
            quantity=("quantity", "sum"),
            avg_discount=("discount", "mean"),
        ).reset_index()
        return g

    cur = agg(current_df)
    pri = agg(prior_df)

    merged = cur.merge(pri[[by, "revenue"]].rename(columns={"revenue": "prior_revenue"}), on=by, how="left")
    merged["margin"] = (merged["profit"] / merged["revenue"].replace(0, pd.NA)).astype(float)
    merged["pct_change"] = merged.apply(
        lambda r: pct_change(r["revenue"], r["prior_revenue"]) if pd.notna(r.get("prior_revenue")) else None,
        axis=1,
    )
    merged = _attach_dq_notes(merged, current_df, by)
    return merged.sort_values("revenue", ascending=False).reset_index(drop=True)


def category_summary(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> pd.DataFrame:
    return grouped_summary(current_df, prior_df, "category")


def region_summary(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> pd.DataFrame:
    return grouped_summary(current_df, prior_df, "region")


def product_summary(current_df: pd.DataFrame, prior_df: pd.DataFrame) -> pd.DataFrame:
    return grouped_summary(current_df, prior_df, "product")


def discount_analysis(current_df: pd.DataFrame, group_col: str = "product", top_n: int | None = None) -> pd.DataFrame:
    """Every product/category with its average discount, revenue, profit,
    and margin-risk flag, sorted biggest-discount-first. Returns all of them
    by default (top_n=None) -- callers that only want to *display* a
    top-N-at-a-glance view (e.g. generate_report.py's HTML report) slice the
    returned dataframe themselves, so the full list is never discarded here
    and stays available (e.g. for "show all" or the Excel workbook)."""
    if current_df.empty:
        return pd.DataFrame(columns=[group_col, "avg_discount", "revenue", "profit", "margin", "margin_risk", "dq_note"])
    g = current_df.groupby(group_col).agg(
        avg_discount=("discount", "mean"),
        revenue=("revenue", "sum"),
        profit=("profit", lambda s: s.sum(min_count=1)),
    ).reset_index()
    g["margin"] = (g["profit"] / g["revenue"].replace(0, pd.NA)).astype(float)
    g["margin_risk"] = (g["avg_discount"] >= HIGH_DISCOUNT_THRESHOLD) & (g["margin"] < LOW_MARGIN_THRESHOLD)
    g = _attach_dq_notes(g, current_df, group_col)
    g = g.sort_values("avg_discount", ascending=False).reset_index(drop=True)
    return g.head(top_n) if top_n is not None else g


def generate_flags(category_df: pd.DataFrame, region_df: pd.DataFrame, product_df: pd.DataFrame) -> list[dict]:
    flags = []

    def scan(df, dim_label):
        for _, row in df.iterrows():
            name = row[dim_label if dim_label in df.columns else df.columns[0]]
            reasons = []
            severity = "warning"
            if pd.notna(row.get("pct_change")) and row["pct_change"] <= DECLINE_FLAG_THRESHOLD:
                reasons.append(f"revenue down {row['pct_change']:.1f}% vs prior period")
                severity = "critical" if row["pct_change"] <= 2 * DECLINE_FLAG_THRESHOLD else "warning"
            if pd.notna(row.get("margin")) and row["margin"] < LOW_MARGIN_THRESHOLD:
                reasons.append(f"margin only {row['margin'] * 100:.1f}%")
            if NEGATIVE_PROFIT_FLAG and row.get("profit", 0) < 0:
                reasons.append(f"negative total profit (${row['profit']:,.0f})")
                severity = "critical"
            if reasons:
                flags.append({
                    "dimension": dim_label,
                    "name": name,
                    "reason": "; ".join(reasons),
                    "severity": severity,
                })

    scan(category_df.rename(columns={"category": "category"}), "category")
    scan(region_df.rename(columns={"region": "region"}), "region")
    scan(product_df.rename(columns={"product": "product"}), "product")

    severity_order = {"critical": 0, "warning": 1}
    flags.sort(key=lambda f: severity_order.get(f["severity"], 2))
    return flags


def build_summary_bullets(current_df, prior_df, current_period, prior_period,
                           category_df, region_df, flags) -> list[str]:
    """One short, standalone sentence per bullet -- callers render this as a
    list (HTML <ul>, or "• "-prefixed lines in Excel), not a run-on paragraph,
    so the headline findings can be scanned at a glance."""
    total_revenue, total_profit, overall_margin = compute_headline_totals(current_df)

    period_label = str(current_period) if current_period is not None else "this period"

    if overall_margin is not None:
        bullets = [
            f"In {period_label}, total sales revenue was ${total_revenue:,.0f} "
            f"with ${total_profit:,.0f} in profit (a {overall_margin:.1f}% overall margin)."
        ]
    else:
        bullets = [
            f"In {period_label}, total sales revenue was ${total_revenue:,.0f}. "
            f"No profit data was provided, so profit and margin aren't shown."
        ]

    if prior_period is not None and not prior_df.empty:
        prior_revenue = prior_df["revenue"].sum()
        change = pct_change(total_revenue, prior_revenue)
        if change is not None:
            direction = "Up" if change >= 0 else "Down"
            bullets.append(f"{direction} {abs(change):.1f}% versus {prior_period} (${prior_revenue:,.0f}).")
    else:
        bullets.append("No prior period was found in the data yet, so period-over-period comparisons aren't available.")

    if not category_df.empty:
        top_cat = category_df.iloc[0]
        bullets.append(f"{top_cat['category']} was the top category by revenue (${top_cat['revenue']:,.0f}).")

    if len(region_df) > 1 and region_df["pct_change"].notna().any():
        worst = region_df.dropna(subset=["pct_change"]).sort_values("pct_change").iloc[0]
        best = region_df.dropna(subset=["pct_change"]).sort_values("pct_change").iloc[-1]
        if worst["pct_change"] < 0:
            bullets.append(f"{worst['region']} was the weakest region ({worst['pct_change']:.1f}%), "
                           f"while {best['region']} led growth ({best['pct_change']:+.1f}%).")

    n_critical = sum(1 for f in flags if f["severity"] == "critical")
    n_warning = sum(1 for f in flags if f["severity"] == "warning")
    if n_critical or n_warning:
        bullets.append(f"{n_critical} critical and {n_warning} warning flag(s) were raised below — see Flags for detail.")
    else:
        bullets.append("No critical issues were flagged this period.")

    return bullets


def analyze_sales(df: pd.DataFrame):
    """Flat (no current/prior split) sales analysis: totals by region, category,
    and product, discount impact on profit margin, and underperforming regions
    (revenue below 20% of the average region's revenue)."""
    by_region = df.groupby("region")["revenue"].sum().reset_index()
    by_category = df.groupby("category")["revenue"].sum().reset_index()
    by_product = df.groupby("product")["revenue"].sum().reset_index()

    discount_impact = df.groupby("product")[["revenue", "discount", "profit"]].sum().reset_index()
    discount_impact["profit_margin"] = (discount_impact["profit"] / discount_impact["revenue"] * 100).round(2)

    avg = by_region["revenue"].mean()
    flagged = by_region[by_region["revenue"] < avg * 0.2]

    return by_region, by_category, by_product, discount_impact, flagged
