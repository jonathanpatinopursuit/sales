"""Vercel entrypoint -- Flask wrapper around the existing report pipeline.

Vercel's Python runtime requires this exact file (api/app.py) to export a
top-level `app` variable. All the report logic already lives in scripts/
(common.py, analysis.py, generate_report.py) and is shared with the CLI
(scripts/generate_report.py) and the Streamlit UI (app.py) -- this file adds
no new logic, it just calls that same pipeline and serves the HTML string
generate_report.render_html() already returns.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from flask import Flask

import analysis
import common
import generate_report

app = Flask(__name__)

LANDING_HTML = (
    '<div class="summary" style="margin-bottom:20px;">'
    '<strong>Sales Organizer</strong> turns a weekly sales export (.xlsx) into an instant report: '
    'revenue and margin by category and region, biggest discounts by product, and automatic flags '
    'for declining segments or thin margins. The report below is generated live from sample data '
    'on every request.'
    '</div>'
)


def build_report_html() -> str:
    data, issues, halts = common.load_data()
    current_df, prior_df, current_period, prior_period = common.split_periods(data)

    category_df = analysis.category_summary(current_df, prior_df)
    region_df = analysis.region_summary(current_df, prior_df)
    product_df = analysis.product_summary(current_df, prior_df)
    discount_product_df = analysis.discount_analysis(current_df, "product")
    discount_category_df = analysis.discount_analysis(current_df, "category")
    flags = analysis.generate_flags(category_df, region_df, product_df)

    summary_text = analysis.build_summary_paragraph(
        current_df, prior_df, current_period, prior_period, category_df, region_df, flags
    )

    total_revenue = current_df["revenue"].sum()
    total_profit = current_df["profit"].sum()
    overall_margin = (total_profit / total_revenue * 100) if total_revenue else 0
    prior_revenue = prior_df["revenue"].sum() if not prior_df.empty else None
    revenue_change = common.pct_change(total_revenue, prior_revenue) if prior_revenue else None

    html = generate_report.render_html(
        summary_text, current_period, prior_period,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        category_df, region_df, discount_product_df, discount_category_df, flags,
        total_revenue, total_profit, overall_margin, revenue_change,
        issues, halts,
    )

    # Slot a short intro card in above the report, reusing the report's own
    # ".summary" styling so it matches without adding any new CSS.
    anchor = '<div class="wrap">\n  <h1>Sales Organizer Report</h1>'
    if anchor in html:
        html = html.replace(anchor, f'<div class="wrap">\n  {LANDING_HTML}\n  <h1>Sales Organizer Report</h1>', 1)
    return html


@app.route("/")
def index():
    try:
        return build_report_html()
    except FileNotFoundError as e:
        return f"<p>{e}</p>", 500
