#!/usr/bin/env python3
"""Extended analysis workbook for a cleaned Superstore-shaped export --
Region x Category breakdowns, product/region/segment/month performance,
monthly trend, bottom-10%-by-profit underperformers, discount-vs-profit
impact, and a Top 10 products chart.

Kept independent of the scripts/common.py + generate_report.py pipeline,
same as clean_sales_data.py -- it works directly on the original
Title Case Superstore columns (Product Name, Region, Category, Order
Date, ...), not the lowercase date/price/... schema that pipeline expects.

Usage:
    python3 scripts/calculations.py [input.csv] [-o output_dir]

Reads data/sales_data_cleaned.csv by default (the file
clean_sales_data.py writes) and writes sales_calculations.xlsx plus
three chart PNGs into reports/ by default.
"""

from __future__ import annotations

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INPUT = os.path.join(BASE_DIR, "data", "sales_data_cleaned.csv")
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "reports")


def build_workbook(df: pd.DataFrame, output_dir: str) -> str:
    df = df.copy()
    df["Month"] = df["Order Date"].dt.to_period("M").astype(str)

    # 1. Sales by Region & Category
    region_category = df.groupby(["Region", "Category"])["Sales"].sum().reset_index()

    # 2. Performance by Product, Region, Segment, Time
    perf = df.groupby(["Product Name", "Region", "Segment", "Month"]).agg(
        Total_Sales=("Sales", "sum"), Total_Profit=("Profit", "sum")).reset_index()

    # 3. Monthly summary
    monthly_summary = df.groupby("Month").agg(Sales=("Sales", "sum"), Profit=("Profit", "sum")).reset_index()

    # 4. Underperformers (bottom 10% by profit)
    underperform = df.groupby(["Category", "Region"])["Profit"].sum().reset_index()
    underperform = underperform[underperform["Profit"] < underperform["Profit"].quantile(0.1)]

    # 5. Discount impact on profit
    discount_impact = df.groupby("Discount %").agg(
        Avg_Profit=("Profit", "mean"), Orders=("Order ID", "count")).reset_index()

    # 6. Region x Category pivot (wide format, complements Region_Category)
    region_pivot = df.pivot_table(values="Sales", index="Region", columns="Category", aggfunc="sum", fill_value=0)

    # 7. Top 10 products by sales
    top_products = df.groupby("Product Name")["Sales"].sum().sort_values(ascending=False).head(10).reset_index()

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "sales_calculations.xlsx")
    chart_png = os.path.join(output_dir, "top_products_chart.png")
    region_chart_png = os.path.join(output_dir, "region_category_chart.png")
    monthly_chart_png = os.path.join(output_dir, "monthly_trend_chart.png")

    # Export report
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        region_category.to_excel(writer, sheet_name="Region_Category", index=False)
        perf.to_excel(writer, sheet_name="Product_Performance", index=False)
        monthly_summary.to_excel(writer, sheet_name="Monthly_Trend", index=False)
        underperform.to_excel(writer, sheet_name="Underperformers", index=False)
        discount_impact.to_excel(writer, sheet_name="Discount_Impact", index=False)
        region_pivot.to_excel(writer, sheet_name="Region_by_Category")
        top_products.to_excel(writer, sheet_name="Top_Products", index=False)

    # Add bar chart image for Top Products
    plt.figure(figsize=(10, 6))
    plt.bar(top_products["Product Name"], top_products["Sales"])
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.title("Top 10 Products by Sales")
    plt.tight_layout()
    plt.savefig(chart_png, dpi=150)
    plt.close()

    # Region by Category chart (stacked bar)
    plt.figure(figsize=(8, 4))
    region_pivot.plot(kind="bar", stacked=True, ax=plt.gca())
    plt.title("Sales by Region and Category")
    plt.tight_layout()
    plt.savefig(region_chart_png, dpi=150)
    plt.close()

    # Monthly Trend chart (line)
    plt.figure(figsize=(8, 4))
    plt.plot(monthly_summary["Month"], monthly_summary["Sales"], marker="o")
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.title("Monthly Sales Trend")
    plt.tight_layout()
    plt.savefig(monthly_chart_png, dpi=150)
    plt.close()

    wb = load_workbook(out_path)
    wb["Top_Products"].add_image(XLImage(chart_png), "E2")
    wb["Region_by_Category"].add_image(XLImage(region_chart_png), "H2")
    wb["Monthly_Trend"].add_image(XLImage(monthly_chart_png), "D2")
    wb.save(out_path)

    return out_path


def main():
    parser = argparse.ArgumentParser(description="Build the extended sales calculations workbook.")
    parser.add_argument("input", nargs="?", default=DEFAULT_INPUT,
                         help=f"Path to the cleaned CSV (default: {DEFAULT_INPUT})")
    parser.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR,
                         help=f"Directory to write the workbook and charts to (default: {DEFAULT_OUTPUT_DIR})")
    args = parser.parse_args()

    try:
        df = pd.read_csv(args.input, parse_dates=["Order Date", "Ship Date"])
    except FileNotFoundError:
        raise SystemExit(f"'{args.input}' not found.")

    out_path = build_workbook(df, args.output_dir)
    print(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
