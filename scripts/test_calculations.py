#!/usr/bin/env python3
"""Test suite for the KPI formulas in scripts/analysis.py
(compute_kpis, discount_band_summary) -- verifies each calculated number
against a hand-computed expected value on a small fixture, the same way
test_validation.py checks validate_data.py.

Run with:
    python3 scripts/test_calculations.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from analysis import compute_kpis, discount_band_summary

_failures = 0


def _check(condition: bool, ok_msg: str, fail_msg: str) -> None:
    global _failures
    if condition:
        print(f"  ✅ {ok_msg}")
    else:
        _failures += 1
        print(f"  ❌ FAIL: {fail_msg}")


def _approx(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol


def make_df() -> pd.DataFrame:
    """Two orders: O1 has two line items (a discounted one, a plain one);
    O2 is a single discounted line with negative profit. Mirrors what
    common.finalize_data() hands to analysis.py -- one row per line item,
    with gross_sales/discount_amount/revenue/profit/order_id/customer/
    quantity/discount already computed."""
    rows = [
        # order_id, customer, quantity, price, discount, profit
        ("O1", "Alice", 2, 100.0, 0.10, 30.0),   # gross 200, disc 20, net 180
        ("O1", "Alice", 1, 50.0, 0.0, 10.0),     # gross 50, disc 0, net 50
        ("O2", "Bob", 1, 40.0, 0.25, -5.0),      # gross 40, disc 10, net 30
    ]
    df = pd.DataFrame(rows, columns=["order_id", "customer", "quantity", "price", "discount", "profit"])
    df["gross_sales"] = df["quantity"] * df["price"]
    df["discount_amount"] = df["gross_sales"] * df["discount"]
    df["revenue"] = df["gross_sales"] - df["discount_amount"]
    return df


def test_gross_net_discount():
    kpis = compute_kpis(make_df())
    _check(_approx(kpis["gross_sales"], 290.0), f"gross_sales = {kpis['gross_sales']}", f"expected 290.0, got {kpis['gross_sales']}")
    _check(_approx(kpis["discount_amount"], 30.0), f"discount_amount = {kpis['discount_amount']}", f"expected 30.0, got {kpis['discount_amount']}")
    _check(_approx(kpis["net_sales"], 260.0), f"net_sales = {kpis['net_sales']}", f"expected 260.0, got {kpis['net_sales']}")
    _check(_approx(kpis["discount_rate"], 30.0 / 290.0 * 100), f"discount_rate = {kpis['discount_rate']:.4f}%",
           f"expected {30.0/290.0*100:.4f}%, got {kpis['discount_rate']}")


def test_order_level_kpis():
    kpis = compute_kpis(make_df())
    _check(kpis["num_orders"] == 2, f"num_orders = {kpis['num_orders']} (2 distinct order_id)",
           f"expected 2, got {kpis['num_orders']}")
    _check(kpis["units_sold"] == 4, f"units_sold = {kpis['units_sold']}", f"expected 4, got {kpis['units_sold']}")
    _check(_approx(kpis["avg_order_value"], 260.0 / 2), f"avg_order_value = {kpis['avg_order_value']}",
           f"expected 130.0, got {kpis['avg_order_value']}")
    _check(_approx(kpis["avg_selling_price"], 260.0 / 4), f"avg_selling_price = {kpis['avg_selling_price']}",
           f"expected 65.0, got {kpis['avg_selling_price']}")
    _check(_approx(kpis["profit_per_order"], 35.0 / 2), f"profit_per_order = {kpis['profit_per_order']}",
           f"expected 17.5, got {kpis['profit_per_order']}")
    _check(kpis["distinct_customers"] == 2, f"distinct_customers = {kpis['distinct_customers']}",
           f"expected 2, got {kpis['distinct_customers']}")
    _check(kpis["negative_profit_orders"] == 1, f"negative_profit_orders = {kpis['negative_profit_orders']} (O2 nets -5)",
           f"expected 1, got {kpis['negative_profit_orders']}")
    _check(kpis["discounted_orders"] == 2, f"discounted_orders = {kpis['discounted_orders']} (both orders have >0 discount)",
           f"expected 2, got {kpis['discounted_orders']}")


def test_no_order_id_falls_back_to_row_count():
    """A file with no order/invoice ID column at all -- common.py's
    _ensure_order_id() normally synthesizes one per row before analysis.py
    ever sees the data, but compute_kpis() should still degrade gracefully
    (one row == one order) if order_id is genuinely absent."""
    df = make_df().drop(columns=["order_id"])
    kpis = compute_kpis(df)
    _check(kpis["num_orders"] == len(df), f"num_orders = {kpis['num_orders']} (row count fallback)",
           f"expected {len(df)}, got {kpis['num_orders']}")


def test_target_achievement():
    df = make_df()
    df["sales_target"] = 200.0  # 200 per row -> sum 600 for the fixture
    kpis = compute_kpis(df)
    _check(_approx(kpis["sales_target"], 600.0), f"sales_target = {kpis['sales_target']}", f"expected 600.0, got {kpis['sales_target']}")
    _check(_approx(kpis["target_achievement"], 260.0 / 600.0 * 100), f"target_achievement = {kpis['target_achievement']:.4f}%",
           f"expected {260.0/600.0*100:.4f}%, got {kpis['target_achievement']}")


def test_target_achievement_not_available():
    kpis = compute_kpis(make_df())
    _check(kpis["sales_target"] is None, "sales_target is None when the column isn't present",
           f"expected None, got {kpis['sales_target']}")
    _check(kpis["target_achievement"] is None, "target_achievement is None when there's no target",
           f"expected None, got {kpis['target_achievement']}")


def test_growth_vs_prior():
    prior = make_df()
    prior["revenue"] = prior["revenue"] * 0.5
    prior["profit"] = prior["profit"] * 0.5
    kpis = compute_kpis(make_df(), prior)
    _check(_approx(kpis["sales_growth"], 100.0), f"sales_growth = {kpis['sales_growth']}%", f"expected 100.0%, got {kpis['sales_growth']}")
    _check(_approx(kpis["profit_growth"], 100.0), f"profit_growth = {kpis['profit_growth']}%", f"expected 100.0%, got {kpis['profit_growth']}")


def test_empty_df_returns_all_none():
    kpis = compute_kpis(make_df().iloc[0:0])
    _check(all(v is None for v in kpis.values()), "every KPI is None for an empty dataframe (not 0)",
           f"expected all None, got {kpis}")


def test_discount_bands():
    bands = discount_band_summary(make_df())
    row_by_band = {r["band"]: r for _, r in bands.iterrows()}
    _check("No discount" in row_by_band, "No discount band present", f"bands found: {list(row_by_band)}")
    _check(row_by_band["No discount"]["orders"] == 1, "1 order line has 0% discount",
           f"expected 1, got {row_by_band['No discount']['orders']}")
    _check("Above 0% through 5%" not in row_by_band or row_by_band.get("Above 0% through 5%") is not None,
           "no rows fall in the 0-5% band for this fixture", "unexpected band contents")
    ten_band = row_by_band.get("Above 5% through 10%")
    _check(ten_band is not None and ten_band["orders"] == 1, "the 10%-discount line lands in the 5-10% band",
           f"got {ten_band}")
    twenty_band = row_by_band.get("Above 20%")
    _check(twenty_band is not None and twenty_band["orders"] == 1, "the 25%-discount line lands in the >20% band",
           f"got {twenty_band}")
    total_orders = bands["orders"].sum()
    _check(total_orders == 3, f"band order counts sum to {total_orders} (3 line items total)",
           f"expected 3, got {total_orders}")


if __name__ == "__main__":
    tests = [
        ("Gross / Discount / Net Sales", test_gross_net_discount),
        ("Order-Level KPIs", test_order_level_kpis),
        ("No order_id Falls Back to Row Count", test_no_order_id_falls_back_to_row_count),
        ("Target Achievement", test_target_achievement),
        ("Target Achievement Not Available", test_target_achievement_not_available),
        ("Sales/Profit Growth vs Prior Period", test_growth_vs_prior),
        ("Empty DataFrame Returns All None", test_empty_df_returns_all_none),
        ("Discount Bands", test_discount_bands),
    ]
    for label, fn in tests:
        print(f"\n--- {label} ---")
        fn()

    print()
    if _failures:
        print(f"❌ {_failures} check(s) failed.")
        sys.exit(1)
    else:
        print("✅ All checks passed.")
