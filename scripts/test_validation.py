#!/usr/bin/env python3
"""Test suite for scripts/validate_data.py's validation logic.

Run with:
    python3 scripts/test_validation.py

Each check prints a pass/fail-style result, and the script exits non-zero
if anything failed, so problems are easy to spot when run. This is a
lightweight, dependency-free suite (no pytest) so it runs anywhere this
project runs.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from validate_data import OPTIONAL_COLUMNS, validate

_failures = 0


def _check(condition: bool, ok_msg: str, fail_msg: str) -> None:
    global _failures
    if condition:
        print(f"  ✅ {ok_msg}")
    else:
        _failures += 1
        print(f"  ❌ FAIL: {fail_msg}")


def make_clean_df(n: int = 25) -> pd.DataFrame:
    """n rows of clean data. Needs to be large enough that a single bad row
    stays under the 5% halt threshold (1/25 = 4%) for the "warn" tests, while
    a small fixture would push even one bad row over 5% and halt instead."""
    return pd.DataFrame({
        "date": [f"2024-01-{(i % 28) + 1:02d}" for i in range(n)],
        "customer": [f"Cust{i}" for i in range(n)],
        "quantity": [((i % 5) + 1) * 2 for i in range(n)],
        "price": [50.0 + i for i in range(n)],
        "discount": [0.1] * n,
        "profit": [100.0 + i for i in range(n)],
        "category": ["A" if i % 2 == 0 else "B" for i in range(n)],
        "region": ["West" if i % 2 == 0 else "East" for i in range(n)],
        "product": ["P1" if i % 2 == 0 else "P2" for i in range(n)],
    })


def test_missing_column():
    df = make_clean_df().drop(columns=["price"])
    try:
        validate(df, "test_missing_col")
        _check(False, "", "should have halted on a missing required column")
    except ValueError as e:
        _check(True, f"HALT caught: {e}", "")


def test_missing_optional_columns_ok():
    """Everything in OPTIONAL_COLUMNS (customer/region/discount/profit/
    product/category/quantity) is optional -- validate() itself still
    expects them present (common.py fills defaults before calling it), but
    given missing_optional it should skip their per-row blank/negative
    checks rather than flagging every row for a column the file never had."""
    df = make_clean_df()
    for col, default in OPTIONAL_COLUMNS.items():
        df[col] = default
    result, issues = validate(df, "test_missing_optional", missing_optional=frozenset(OPTIONAL_COLUMNS))
    _check(len(result) == len(df), "no rows dropped", f"expected {len(df)} rows, got {len(result)}")
    noisy = [
        i for i in issues
        if "missing region" in i["message"] or "missing customer" in i["message"]
        or "missing category" in i["message"] or "negative profit" in i["message"]
    ]
    _check(not noisy, "no blank/negative noise for a column the file never had",
           f"unexpected issues: {noisy}")
    _check(result["dq_flag"].isna().all(), "no rows tagged invalid_region/invalid_customer/invalid_category/negative_profit",
           f"unexpectedly tagged: {result['dq_flag'].dropna().tolist()}")


def test_bad_dates_warn():
    df = make_clean_df()
    df.loc[0, "date"] = None
    result, issues = validate(df, "test_bad_dates_warn")
    _check(len(result) == len(df) - 1, f"rows remaining: {len(result)} (expected {len(df) - 1})",
           f"expected {len(df) - 1} rows remaining, got {len(result)}")
    skip_issues = [i for i in issues if i["level"] == "skip" and "bad_date" in i["message"]]
    _check(bool(skip_issues), f"warning recorded: {skip_issues}",
           "expected a skip warning for the bad date")
    _check(result["dq_flag"].isna().all(), "remaining rows are untagged (the tagged row was dropped)",
           f"remaining rows unexpectedly tagged: {result['dq_flag'].tolist()}")


def test_bad_dates_halt():
    df = make_clean_df()
    df["date"] = None
    try:
        validate(df, "test_bad_dates_halt")
        _check(False, "", "should have halted when >5% of dates are bad")
    except ValueError as e:
        _check(True, f"HALT caught: {e}", "")


def test_invalid_qty_price():
    df = make_clean_df()
    df.loc[1, "quantity"] = -5
    result, issues = validate(df, "test_invalid_qty_price")
    _check(len(result) == len(df) - 1, f"rows remaining: {len(result)} (expected {len(df) - 1})",
           f"expected {len(df) - 1} rows remaining, got {len(result)}")
    skip_issues = [i for i in issues if i["level"] == "skip" and "invalid_qty_price" in i["message"]]
    _check(bool(skip_issues), f"warning recorded: {skip_issues}",
           "expected a skip warning for invalid quantity/price")
    # The affected row is dropped, so its tag isn't visible in the returned df --
    # what we CAN verify is that the rows left behind weren't mistagged.
    _check(result["dq_flag"].isna().all(), "remaining rows are untagged",
           f"remaining rows unexpectedly tagged: {result['dq_flag'].tolist()}")


def test_discount_clamp():
    df = make_clean_df()
    df.loc[0, "discount"] = 1.5
    result, issues = validate(df, "test_discount_clamp")
    _check(len(result) == len(df), "row kept, not dropped", f"expected {len(df)} rows, got {len(result)}")
    _check(result.loc[0, "discount"] == 1.0, f"discount clamped to {result.loc[0, 'discount']}",
           f"expected 1.0, got {result.loc[0, 'discount']}")
    _check(result.loc[0, "dq_flag"] == "clamped:discount", f"dq_flag = {result.loc[0, 'dq_flag']!r}",
           f"expected 'clamped:discount', got {result.loc[0, 'dq_flag']!r}")
    _check(pd.isna(result.loc[1, "dq_flag"]), "untouched rows stay untagged",
           f"row 1 unexpectedly tagged: {result.loc[1, 'dq_flag']!r}")
    warn_issues = [i for i in issues if i["level"] == "warn" and "Corrected" in i["message"]]
    _check(bool(warn_issues), f"warning recorded: {warn_issues}", "expected a clamp warning")


def test_invalid_region():
    df = make_clean_df()
    df.loc[2, "region"] = "  "
    result, issues = validate(df, "test_invalid_region")
    _check(len(result) == len(df), "row kept, not dropped", f"expected {len(df)} rows, got {len(result)}")
    _check(result.loc[2, "dq_flag"] == "flagged:invalid_region", f"dq_flag = {result.loc[2, 'dq_flag']!r}",
           f"unexpected dq_flag {result.loc[2, 'dq_flag']!r}")
    warn_issues = [i for i in issues if "blank/missing region" in i["message"]]
    _check(bool(warn_issues), f"warning recorded: {warn_issues}", "expected a blank-region warning")


def test_invalid_category():
    df = make_clean_df()
    df.loc[1, "category"] = ""
    result, issues = validate(df, "test_invalid_category")
    _check(len(result) == len(df), "row kept, not dropped", f"expected {len(df)} rows, got {len(result)}")
    _check(result.loc[1, "dq_flag"] == "flagged:invalid_category", f"dq_flag = {result.loc[1, 'dq_flag']!r}",
           f"unexpected dq_flag {result.loc[1, 'dq_flag']!r}")
    warn_issues = [i for i in issues if "blank/missing category" in i["message"]]
    _check(bool(warn_issues), f"warning recorded: {warn_issues}", "expected a blank-category warning")


def test_negative_profit():
    df = make_clean_df()
    df.loc[0, "profit"] = -50.0
    result, issues = validate(df, "test_negative_profit")
    _check(len(result) == len(df), "row kept, not dropped", f"expected {len(df)} rows, got {len(result)}")
    _check(result.loc[0, "dq_flag"] == "flagged:negative_profit", f"dq_flag = {result.loc[0, 'dq_flag']!r}",
           f"unexpected dq_flag {result.loc[0, 'dq_flag']!r}")
    warn_issues = [i for i in issues if "negative profit" in i["message"]]
    _check(bool(warn_issues), f"warning recorded: {warn_issues}", "expected a negative-profit warning")


def test_duplicates():
    base = make_clean_df()
    df = pd.concat([base, base.iloc[[0]]], ignore_index=True)
    result, issues = validate(df, "test_duplicates")
    _check(len(result) == len(df), "duplicate row kept, not removed", f"expected {len(df)} rows, got {len(result)}")
    dup_tags = int((result["dq_flag"] == "flagged:duplicate").sum())
    _check(dup_tags == 2, f"{dup_tags} rows tagged flagged:duplicate (both copies)",
           f"expected 2 rows tagged, got {dup_tags}")
    warn_issues = [i for i in issues if "duplicate" in i["message"]]
    _check(bool(warn_issues), f"warning recorded: {warn_issues}", "expected a duplicate warning")


def test_multiple_issues_on_one_row():
    """A row hit by two independent checks should keep both labels, not overwrite."""
    df = make_clean_df()
    df.loc[0, "discount"] = 1.5
    df.loc[0, "region"] = ""
    result, issues = validate(df, "test_multiple_issues")
    tag = result.loc[0, "dq_flag"]
    _check(
        "clamped:discount" in tag and "flagged:invalid_region" in tag,
        f"row carries both labels: {tag!r}",
        f"expected both labels present, got {tag!r}",
    )


if __name__ == "__main__":
    tests = [
        ("Missing Column", test_missing_column),
        ("Missing Optional Columns OK", test_missing_optional_columns_ok),
        ("Bad Dates - Warn (<=5%)", test_bad_dates_warn),
        ("Bad Dates - Halt (>5%)", test_bad_dates_halt),
        ("Invalid Quantity/Price", test_invalid_qty_price),
        ("Discount Clamp", test_discount_clamp),
        ("Invalid Region", test_invalid_region),
        ("Invalid Category", test_invalid_category),
        ("Negative Profit", test_negative_profit),
        ("Duplicates", test_duplicates),
        ("Multiple Issues On One Row", test_multiple_issues_on_one_row),
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
