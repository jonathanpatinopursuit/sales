"""Sales Organizer -- Streamlit web UI.

Run locally:
    streamlit run app.py

Lets you upload a weekly sales export (.xlsx) in the browser and see the
report immediately, instead of dropping the file into data/ and running
scripts/generate_report.py from the command line. Every step here --
validation, analysis, and the report itself -- calls straight into
common.py / analysis.py / generate_report.py, the same code the CLI uses,
so the two never drift apart.
"""

from __future__ import annotations

import io
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import analysis
import common
import create_sample_data
import generate_report

st.set_page_config(page_title="Sales Organizer", page_icon="📊", layout="wide")

st.title("📊 Sales Organizer")

# --- Step 1: upload. Step 2: an explicit Generate Report click -- nothing
# else competes for attention above these two actions. Report state lives in
# session_state so it survives the reruns that later download-button clicks
# trigger, and resets if a different file is uploaded.
uploaded_file = st.file_uploader("Upload Data (.xlsx, .csv, .tsv)", type=["xlsx", "csv", "tsv"])

if uploaded_file is not None and st.session_state.get("uploaded_name") != uploaded_file.name:
    st.session_state["generated"] = False
    st.session_state["uploaded_name"] = uploaded_file.name
    st.session_state["use_sample"] = False

# No data on hand? A synthetic two-period dataset stands in for a real
# upload -- it's run through the exact same pipeline below, just sourced
# from create_sample_data.sample_dataframe() instead of the file uploader.
if uploaded_file is None:
    st.info(
        "Drop a `.xlsx` file above to get started -- only date and price are required, "
        "everything else (product, category, quantity, customer, region, discount, "
        "profit) is optional and defaults if missing -- or a raw `.csv`/`.tsv` export "
        "(columns: Order_Date, Customer_Name, Product, Product_Category, Region, "
        "Units_Sold, Unit_Price, Discount_Pct, Profit) -- currency/percent formatting "
        "and an Order_ID column are handled automatically."
    )
    if st.button("Don't have data? Generate a sample report", use_container_width=True):
        st.session_state["generated"] = True
        st.session_state["use_sample"] = True
else:
    if st.button("Generate Report", type="primary", use_container_width=True):
        st.session_state["generated"] = True
        st.session_state["use_sample"] = False

if not st.session_state.get("generated"):
    st.stop()

if st.session_state.get("use_sample"):
    source_file = io.BytesIO()
    create_sample_data.sample_dataframe().to_excel(source_file, index=False)
    source_file.seek(0)
    source_name = "sample_sales.xlsx"
else:
    source_file, source_name = uploaded_file, uploaded_file.name

# --- Run the file through the exact same pipeline the CLI uses --
# process_file() figures out from the column headers whether this is a raw
# export (see scripts/clean_raw_export.py) or the already-clean shape ---
df, file_issues, halt_msg = common.process_file(source_file, source_name)

if halt_msg:
    st.error(f"🚫 {halt_msg}")
    st.stop()

data, issues = common.finalize_data([df], file_issues)
current_df, prior_df, current_period, prior_period = common.split_periods(data)

category_df = analysis.category_summary(current_df, prior_df)
region_df = analysis.region_summary(current_df, prior_df)
product_df = analysis.product_summary(current_df, prior_df)
discount_product_df = analysis.discount_analysis(current_df, "product")
discount_category_df = analysis.discount_analysis(current_df, "category")
flags = analysis.generate_flags(category_df, region_df, product_df)
flags_df = pd.DataFrame(flags) if flags else pd.DataFrame(columns=["dimension", "name", "reason", "severity"])

summary_text = analysis.build_summary_paragraph(
    current_df, prior_df, current_period, prior_period, category_df, region_df, flags
)

total_revenue, total_profit, overall_margin = analysis.compute_headline_totals(current_df)
prior_revenue = prior_df["revenue"].sum() if not prior_df.empty else None
revenue_change = common.pct_change(total_revenue, prior_revenue) if prior_revenue else None

# --- Render the exact same report the CLI writes to reports/latest.html ---
# (no halts to show here -- a halted file already stopped above -- so pass [])
report_html = generate_report.render_html(
    summary_text, current_period, prior_period,
    datetime.now().strftime("%Y-%m-%d %H:%M"),
    category_df, region_df, discount_product_df, discount_category_df, flags,
    total_revenue, total_profit, overall_margin, revenue_change,
    issues, [],
)

if issues:
    st.warning(f"⚠ {len(issues)} data quality issue(s) were found -- see the banner in the report below.")

components.html(report_html, height=900, scrolling=True)

# --- Downloads, using the same write_excel()/render_html() the CLI uses ---
xlsx_buffer = io.BytesIO()
generate_report.write_excel(
    xlsx_buffer, summary_text, current_period, prior_period,
    category_df, region_df, discount_product_df, discount_category_df, flags_df,
    issues, [],
)

col1, col2 = st.columns(2)
with col1:
    st.download_button(
        "⬇ Download Excel report", xlsx_buffer.getvalue(),
        file_name="sales_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with col2:
    st.download_button(
        "⬇ Download HTML report", report_html,
        file_name="sales_report.html", mime="text/html",
    )
