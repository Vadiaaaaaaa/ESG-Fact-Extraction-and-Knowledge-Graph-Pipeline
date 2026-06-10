import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_ROOT / 'pipeline'), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import streamlit as st
import subprocess
import json
from pathlib import Path

st.set_page_config(page_title="ESG Pipeline", page_icon="🌱", layout="wide")
st.title("🌱 ESG Pipeline Runner")

with st.form("pipeline_form"):
    col1, col2 = st.columns(2)

    with col1:
        pdf_path = st.text_input(
            "PDF path",
            placeholder=r"C:\path\to\annual_report.pdf",
        )
        company_id = st.text_input("Company ID", "nestle_india")
        company_name = st.text_input("Company name", "Nestlé India Limited")
        year = st.number_input("Reporting year", 2018, 2030, 2024)

    with col2:
        calendar_type = st.selectbox("Calendar type", ["indian_fiscal", "calendar_year"])
        sector = st.text_input("Sector", "FMCG")
        country = st.text_input("Country", "India")

    col3, col4, col5 = st.columns(3)
    pass1_only = col3.checkbox("Pass 1 only")
    pass2_only = col4.checkbox("Pass 2 only")
    no_kg = col5.checkbox("Skip KG load")
    force_continue = st.checkbox("Override HIGH coverage risk")

    submitted = st.form_submit_button("🚀 Run Pipeline", type="primary")

if submitted and pdf_path and company_id:
    cmd = [
        "python", "run_pipeline.py",
        "--pdf", pdf_path,
        "--company", company_id,
        "--company-name", company_name,
        "--year", str(int(year)),
        "--calendar-type", calendar_type,
        "--sector", sector,
        "--country", country,
    ]
    if pass1_only:
        cmd.append("--pass1-only")
    if pass2_only:
        cmd.append("--pass2-only")
    if no_kg:
        cmd.append("--no-kg")
    if force_continue:
        cmd.append("--force-continue")

    st.code(" ".join(cmd), language="bash")

    with st.spinner(f"Running pipeline for {company_name} {year}..."):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_ROOT),
        )

    if result.returncode == 0:
        st.success("Pipeline completed successfully")
        st.code(result.stdout)
    else:
        st.error("Pipeline failed")
        st.code(result.stderr)
        if result.stdout:
            st.code(result.stdout)
elif submitted:
    st.warning("Please fill in PDF path and Company ID")
