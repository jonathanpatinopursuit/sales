#!/usr/bin/env python3
"""Generate a synthetic sample export with two periods (current + prior month)
so generate_report.py has something to compute period-over-period change and
flags against.

Usage:
    python3 scripts/create_sample_data.py

Writes data/sample_sales.xlsx.
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Base line items: (region, category, product, sales, discount_pct, profit)
CURRENT_MONTH = [
    ("North", "Electronics", "Laptop", 5000, 10, 1200),
    ("South", "Electronics", "Phone", 3000, 5, 800),
    ("East", "Furniture", "Chair", 1200, 15, 200),
    ("West", "Furniture", "Desk", 800, 20, 100),
    ("North", "Clothing", "Jacket", 400, 25, 50),
    ("South", "Clothing", "Shoes", 300, 30, 30),
    ("East", "Electronics", "Tablet", 2500, 8, 600),
    ("West", "Furniture", "Sofa", 150, 35, 10),
]

# Prior month: West and Clothing are deliberately weaker so the report's
# decline/margin flags have something to catch; everything else grows modestly.
PRIOR_MONTH = [
    ("North", "Electronics", "Laptop", 4600, 10, 1050),
    ("South", "Electronics", "Phone", 2800, 5, 720),
    ("East", "Furniture", "Chair", 1100, 15, 180),
    ("West", "Furniture", "Desk", 2200, 12, 350),
    ("North", "Clothing", "Jacket", 900, 15, 180),
    ("South", "Clothing", "Shoes", 700, 15, 140),
    ("East", "Electronics", "Tablet", 2300, 8, 550),
    ("West", "Furniture", "Sofa", 1300, 15, 220),
]


def _rows_for_month(items, date):
    rows = []
    for region, category, product, sales, discount_pct, profit in items:
        discount_rate = discount_pct / 100.0
        # quantity=1, price backed out so quantity*price*(1-discount) == sales
        # (this project's revenue formula, see scripts/common.py)
        price = round(sales / (1 - discount_rate), 2)
        rows.append({
            "date": date,
            "customer": "Sample Customer",
            "product": product,
            "category": category,
            "region": region,
            "quantity": 1,
            "price": price,
            "discount": discount_rate,
            "profit": profit,
        })
    return rows


def create_sample_data():
    rows = _rows_for_month(PRIOR_MONTH, datetime(2026, 6, 15)) + \
        _rows_for_month(CURRENT_MONTH, datetime(2026, 7, 15))

    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "sample_sales.xlsx")
    pd.DataFrame(rows).to_excel(path, index=False)
    print(f"{path} created!")


if __name__ == "__main__":
    create_sample_data()
