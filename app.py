"""Sales Organizer -- Streamlit web UI.

Run locally:
    streamlit run app.py

Lets you upload a weekly sales export (.xlsx) in the browser and see the
report immediately, instead of dropping the file into data/ and running
scripts/generate_report.py from the command line.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Sales Organizer", page_icon="📊", layout="wide")

st.title("📊 Sales Organizer")
st.write(
    "Upload your weekly sales export (`.xlsx`) below to generate a report -- "
    "no command line required."
)

uploaded_file = st.file_uploader("Weekly sales export", type=["xlsx"])

if uploaded_file is None:
    st.info(
        "Drop a `.xlsx` file above to get started. Expected columns: "
        "date, customer, product, category, region, quantity, price, discount, profit."
    )
    st.stop()

# Skeleton: just prove the file made it in. Validation and report generation
# are wired in next.
raw_df = pd.read_excel(uploaded_file)
st.success(f"Loaded '{uploaded_file.name}' -- {len(raw_df)} row(s).")
st.dataframe(raw_df.head(20))
