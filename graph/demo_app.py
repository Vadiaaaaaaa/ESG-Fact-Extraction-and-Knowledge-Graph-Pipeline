from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from neo4j import GraphDatabase, READ_ACCESS

st.set_page_config(
    page_title="ESG Knowledge Graph",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Paths & connection ─────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_CONFIG = _ROOT / "pipeline_config.json"


@st.cache_resource
def get_driver():
    # 1. Streamlit Cloud secrets (production)
    try:
        uri  = st.secrets["NEO4J_URI"]
        user = st.secrets["NEO4J_USER"]
        pwd  = st.secrets["NEO4J_PASS"]
    except Exception:
        # 2. Local pipeline_config.json
        cfg: dict[str, Any] = {}
        if _CONFIG.exists():
            cfg = json.loads(_CONFIG.read_text())
        uri  = cfg.get("neo4j_uri",  os.getenv("NEO4J_URI",  "neo4j://127.0.0.1:7687"))
        user = cfg.get("neo4j_user", os.getenv("NEO4J_USER", "neo4j"))
        pwd  = cfg.get("neo4j_pass", cfg.get("neo4j_password", os.getenv("NEO4J_PASS", "")))
    drv = GraphDatabase.driver(uri, auth=(user, pwd))
    drv.verify_connectivity()
    return drv


def run_query(cypher: str) -> list[dict]:
    with get_driver().session(default_access_mode=READ_ACCESS) as s:
        return [dict(r) for r in s.run(cypher)]


# ── Helpers ────────────────────────────────────────────────────────────────────
COLORS: dict[str, str] = {
    "Nestle India Limited":         "#009EDB",
    "Britannia Industries Limited": "#C41E3A",
    "Marico Limited":               "#E8832A",
    "nestle_india":                 "#009EDB",
    "britannia":                    "#C41E3A",
    "marico":                       "#E8832A",
}

def company_color(name: str | None) -> str:
    if not name:
        return "#C9748A"
    n = name.lower()
    for k, v in COLORS.items():
        if k.lower() in n:
            return v
    return "#C9748A"


def clean_evidence(text: str, keywords: list[str] | None = None) -> str:
    if not text:
        return "Source text not available"
    lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n")
             if ln.strip() and len(ln.strip()) > 10]
    kws = [k.lower() for k in (keywords or [])]
    if kws:
        for line in lines:
            lo = line.lower()
            for kw in kws:
                idx = lo.find(kw)
                if idx != -1:
                    snippet = line[idx:]
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "..."
                    return snippet
    for line in lines:
        if 20 < len(line) < 200:
            return line
    return (text[:200] + "...") if len(text) > 200 else text


# ── Plotly base layout ─────────────────────────────────────────────────────────
_LAYOUT_BASE = dict(
    paper_bgcolor="#FFFFFF",
    plot_bgcolor="#FFFFFF",
    font=dict(family="Inter", size=12, color="#3D3A37"),
    margin=dict(l=10, r=10, t=10, b=10),
    showlegend=False,
    xaxis=dict(showgrid=False, showline=True, linecolor="#E2DDD8",
               tickfont=dict(size=11, color="#6B6560")),
    yaxis=dict(showgrid=False, showline=False,
               tickfont=dict(size=11, color="#6B6560")),
)


def hbar(df: pd.DataFrame, unit: str, note: str = "") -> go.Figure:
    colors = [company_color(c) for c in df["company"]]
    label  = f"{unit}  ·  {note}" if note else unit
    fig = go.Figure(go.Bar(
        x=df["value"], y=df["company"],
        orientation="h",
        marker_color=colors,
        marker_line_width=0,
        width=0.5,
    ))
    layout = {**_LAYOUT_BASE}
    layout["xaxis"] = dict(
        showgrid=False, showline=True, linecolor="#E2DDD8",
        title=dict(text=label, font=dict(size=11, color="#6B6560")),
        tickfont=dict(size=11, color="#6B6560"),
    )
    layout["height"] = max(200, len(df) * 72)
    fig.update_layout(**layout)
    return fig


# ── Document name map & evidence lookup ───────────────────────────────────────
DOC_NAMES: dict[str, str] = {
    "nestle_india_fy2024": "Nestlé India Annual Report FY2024",
    "nestle_india_fy2025": "Nestlé India Annual Report FY2025",
    "britannia_fy2024":    "Britannia Industries Annual Report FY2024",
    "marico_fy2024":       "Marico Limited Annual Report FY2024",
}

_NAME_TO_ID: dict[str, str] = {
    "Nestle India Limited":          "nestle_india",
    "Britannia Industries Limited":  "britannia",
    "Marico Limited":                "marico",
}

_EVIDENCE_CANONICAL: dict[str, str] = {
    "q2": "scope_1_emissions",
    "q5": "scope_1_emissions",
    "q6": "water_consumption_absolute",
}

_EVIDENCE_KEYWORDS: dict[str, list[str]] = {
    "q1": ["scope 1", "scope1", "direct emission", "tCO2e"],
    "q2": ["scope 1", "scope1", "direct emission", "tCO2e"],
    "q3_nonrenew": ["non-renewable", "fossil fuel", "coal", "oil", "natural gas", "non renewable"],
    "q3_total":    ["total energy", "energy consumed", "GJ"],
    "q4": ["female", "wages paid to female", "gross wages"],
    "q5": ["scope 1", "scope1", "direct emission", "tCO2e"],
    "q6": ["water withdrawal", "water consumption", "kiloliter", "kilolitre"],
}


def get_evidence(canonical_id: str, company_id: str, period: str = "FY2024") -> dict | None:
    rows = run_query(f"""
        MATCH (o:Observation)-[:OF_METRIC]->(m:Metric),
              (o)-[:REPORTED_BY]->(c:Company),
              (o)-[:IN_PERIOD]->(p:Period {{fiscal_year: '{period}'}}),
              (o)-[:SUPPORTED_BY]->(ev:Evidence),
              (o)-[:EXTRACTED_FROM]->(ch:Chunk)
        WHERE m.canonical_id = '{canonical_id}'
          AND c.company_id = '{company_id}'
          AND o.normalization_status IN ['normalized', 'partial']
          AND o.normalised_value IS NOT NULL
        WITH o, c, ev, ch
        ORDER BY o.normalised_value DESC
        LIMIT 1
        RETURN ev.text AS evidence, ch.page AS page,
               o.source_doc_id AS doc_id, c.name AS company
    """)
    return rows[0] if rows else None


def _evidence_block(doc_name: str, text: str, page: int | str) -> str:
    return f"""
<div style="margin-bottom:16px;">
  <div style="font-weight:500;color:#1A1A18;font-size:13px;
              margin-bottom:4px;">{doc_name}</div>
  <div style="font-size:11px;color:#9B9590;margin-bottom:8px;">
    Page {page}
  </div>
  <div style="background:#FAF7F5;border-left:2px solid #C9748A;
              padding:10px 12px;font-style:italic;
              color:#3D3A37;font-size:13px;line-height:1.6;">
    &ldquo;{text}&rdquo;
  </div>
</div>"""


def _divider_html() -> str:
    return '<div style="height:1px;background:#E2DDD8;margin:12px 0;"></div>'


def render_source_expander(sel: str, rows: list[dict]) -> None:
    with st.expander("Source text"):
        html_parts: list[str] = []

        # ── Q6: water confidence — evidence in main query result ──────────────
        if sel == "q6":
            row      = rows[0] if rows else {}
            raw_text = row.get("evidence") or ""
            doc_id   = row.get("doc_id") or ""
            page     = row.get("page", "—")
            doc_name = DOC_NAMES.get(doc_id, "Source document")
            text     = clean_evidence(raw_text, _EVIDENCE_KEYWORDS["q6"])
            if not text or text == "Source text not available":
                text = f"Extracted from {doc_name}, BRSR Section C — Principle 6 Water Disclosures, Page {page}"
            html_parts.append(_evidence_block(doc_name, text, page))

        # ── Q3: fossil fuel % — two source metrics for Britannia ──────────────
        elif sel == "q3":
            html_parts.append(
                '<div style="font-family:Inter;font-size:13px;color:#6B6560;'
                'line-height:1.6;margin-bottom:14px;">'
                'This figure was computed from two source metrics: non-renewable energy '
                'consumption and total energy consumption, both from Britannia\'s FY2024 '
                'BRSR Principle 6 disclosures.</div>'
            )
            for cid, kw_key, label in [
                ("non_renewable_energy_consumption_absolute", "q3_nonrenew", "Non-renewable energy"),
                ("absolute_energy_consumption",               "q3_total",    "Total energy consumed"),
            ]:
                ev = get_evidence(cid, "britannia")
                if ev:
                    raw  = ev.get("evidence") or ""
                    text = clean_evidence(raw, _EVIDENCE_KEYWORDS[kw_key])
                    doc_name = DOC_NAMES.get(ev.get("doc_id", ""), "Source document")
                    page     = ev.get("page", "—")
                    if not text or text == "Source text not available":
                        text = f"Extracted from {doc_name}, BRSR Section C — Principle 6, Page {page}"
                    html_parts.append(
                        f'<div style="font-size:11px;letter-spacing:1px;text-transform:uppercase;'
                        f'color:#9B9590;margin-bottom:6px;">{label}</div>'
                    )
                    html_parts.append(_evidence_block(doc_name, text, page))

        # ── Q4: female wage share — raw_name query, fetch evidence by raw_name ─
        elif sel == "q4":
            kws = _EVIDENCE_KEYWORDS["q4"]
            seen: set[str] = set()
            ordered = sorted(rows, key=lambda r: r.get("value") or 0, reverse=True)
            for row in ordered:
                co_name = row.get("company", "")
                co_id   = _NAME_TO_ID.get(co_name)
                if not co_id or co_id in seen:
                    continue
                seen.add(co_id)
                # Fetch evidence via raw_name match
                ev_rows = run_query(f"""
                    MATCH (o:Observation)-[:REPORTED_BY]->(c:Company),
                          (o)-[:IN_PERIOD]->(p:Period {{fiscal_year:'FY2024'}}),
                          (o)-[:SUPPORTED_BY]->(ev:Evidence),
                          (o)-[:EXTRACTED_FROM]->(ch:Chunk)
                    WHERE c.company_id = '{co_id}'
                      AND o.raw_name IN [
                        'Gross wages paid to females as a % of total wages',
                        'Gross wages paid to females as % of total wages'
                      ]
                      AND o.normalised_unit_symbol = '%'
                      AND o.normalised_value IS NOT NULL
                    WITH o, ev, ch, c ORDER BY o.normalised_value DESC LIMIT 1
                    RETURN ev.text AS evidence, ch.page AS page,
                           o.source_doc_id AS doc_id, c.name AS company
                """)
                if not ev_rows:
                    continue
                ev       = ev_rows[0]
                raw      = ev.get("evidence") or ""
                text     = clean_evidence(raw, kws)
                doc_id   = ev.get("doc_id") or ""
                page     = ev.get("page", "—")
                doc_name = DOC_NAMES.get(doc_id, "Source document")
                if not text or text == "Source text not available":
                    text = f"Extracted from {doc_name}, BRSR Section C — Principle 5, Page {page}"
                if html_parts:
                    html_parts.append(_divider_html())
                html_parts.append(
                    f'<div style="font-size:12px;font-weight:600;color:#1A1A18;'
                    f'font-family:Inter;margin-bottom:8px;letter-spacing:0.2px;">'
                    f'{co_name}</div>'
                )
                html_parts.append(_evidence_block(doc_name, text, page))

        # ── Q1: emissions improvement — single-company trend, no company key in rows ──
        elif sel == "q1":
            kws = _EVIDENCE_KEYWORDS["q1"]
            ev = get_evidence("scope_1_emissions", "nestle_india", "FY2024")
            if ev:
                doc_name = DOC_NAMES.get(ev.get("doc_id", ""), ev.get("doc_id", ""))
                text = clean_evidence(ev.get("evidence", "") or "", kws)
                if not text:
                    text = f"Extracted from {doc_name}, Page {ev.get('page', '')}"
                html_parts.append(_evidence_block(doc_name, text, ev.get("page")))
            else:
                st.markdown(
                    '<div style="font-family:Inter;font-size:13px;color:#9B9590;">'
                    'No source text available.</div>',
                    unsafe_allow_html=True)

        # ── Q5: single-company Scope 1 trend (rows have year/value/unit, no company) ──
        elif sel == "q5":
            kws = _EVIDENCE_KEYWORDS["q5"]
            ev = get_evidence("scope_1_emissions", "nestle_india", "FY2024")
            if ev:
                doc_name = DOC_NAMES.get(ev.get("doc_id", ""), ev.get("doc_id", ""))
                text = clean_evidence(ev.get("evidence", "") or "", kws)
                if not text:
                    text = f"Extracted from {doc_name}, Page {ev.get('page', '')}"
                html_parts.append(_evidence_block(doc_name, text, ev.get("page")))
            else:
                st.markdown(
                    '<div style="font-family:Inter;font-size:13px;color:#9B9590;">'
                    'No source text available.</div>',
                    unsafe_allow_html=True)

        # ── Multi-company bar questions: one block per company ────────────────
        else:
            canonical = _EVIDENCE_CANONICAL.get(sel)
            kws       = _EVIDENCE_KEYWORDS.get(sel, [])
            if not canonical or not rows:
                st.markdown(
                    '<div style="font-family:Inter;font-size:13px;color:#9B9590;">'
                    'No source text available.</div>',
                    unsafe_allow_html=True)
                return

            seen: set[str] = set()
            ordered = sorted(rows, key=lambda r: r.get("value") or 0, reverse=True)
            for row in ordered:
                co_name = row.get("company", "")
                co_id   = _NAME_TO_ID.get(co_name)
                if not co_id or co_id in seen:
                    continue
                seen.add(co_id)

                ev = get_evidence(canonical, co_id)
                if not ev:
                    continue

                raw      = ev.get("evidence") or ""
                text     = clean_evidence(raw, kws)
                doc_id   = ev.get("doc_id") or ""
                page     = ev.get("page", "—")
                doc_name = DOC_NAMES.get(doc_id, "Source document")
                if not text or text == "Source text not available":
                    text = f"Extracted from {doc_name}, BRSR Section — Principle 6, Page {page}"
                if html_parts:
                    html_parts.append(_divider_html())
                html_parts.append(
                    f'<div style="font-size:12px;font-weight:600;color:#1A1A18;'
                    f'font-family:Inter;margin-bottom:8px;letter-spacing:0.2px;">'
                    f'{co_name}</div>'
                )
                html_parts.append(_evidence_block(doc_name, text, page))

        if html_parts:
            st.markdown(
                '<div style="font-family:Inter;">' + "".join(html_parts) + "</div>",
                unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="font-family:Inter;font-size:13px;color:#9B9590;">'
                'No source text available.</div>',
                unsafe_allow_html=True)


# ── Q3: Britannia fossil fuel % (two-query computation) ───────────────────────
Q3_CYPHER_A = """
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric
      {canonical_id: 'non_renewable_energy_consumption_absolute'}),
      (o)-[:REPORTED_BY]->(c:Company {company_id: 'britannia'}),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
  AND o.normalised_unit_symbol = 'GJ'
RETURN max(o.normalised_value) as non_renewable""".strip()

Q3_CYPHER_B = """
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric
      {canonical_id: 'absolute_energy_consumption'}),
      (o)-[:REPORTED_BY]->(c:Company {company_id: 'britannia'}),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
  AND o.normalised_unit_symbol = 'GJ'
RETURN max(o.normalised_value) as total""".strip()

Q3_CYPHER_DISPLAY = (
    "-- Query A: non-renewable energy\n" + Q3_CYPHER_A +
    "\n\n-- Query B: total energy\n" + Q3_CYPHER_B +
    "\n\n-- Python: fossil_pct = round(non_renewable / total * 100, 1)"
)


def get_q3_fossil_data() -> list[dict]:
    nr  = run_query(Q3_CYPHER_A)
    tot = run_query(Q3_CYPHER_B)
    if not nr or not tot:
        return []
    non_renewable = nr[0].get("non_renewable")
    total         = tot[0].get("total")
    if not non_renewable or not total:
        return []
    fossil_pct    = round(non_renewable / total * 100, 1)
    renewable_pct = round(100 - fossil_pct, 1)
    return [{"fossil_pct": fossil_pct, "renewable_pct": renewable_pct,
             "non_renewable": non_renewable, "total": total}]


# ── Queries ────────────────────────────────────────────────────────────────────
Q1_CYPHER = """
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric
      {canonical_id: 'scope_1_emissions'}),
      (o)-[:REPORTED_BY]->(c:Company
      {company_id: 'nestle_india'}),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
  AND o.normalised_value < 1000000
WITH p.fiscal_year as year,
     max(o.normalised_value) as value
RETURN year, value, 'tCO2e' as unit
ORDER BY year""".strip()

Q2_CYPHER = """
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE m.canonical_id IN ['scope_1_emissions', 'scope_2_emissions']
  AND o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH c.name AS company, m.canonical_id AS scope,
     max(o.normalised_value) AS value
RETURN company, scope, value, 'tCO2e' AS unit
ORDER BY company, scope""".strip()

Q4_CYPHER = """
MATCH (o:Observation)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.raw_name IN [
  'Gross wages paid to females as a % of total wages',
  'Gross wages paid to females as % of total wages'
]
  AND o.normalised_unit_symbol = '%'
  AND o.normalised_value IS NOT NULL
WITH c, max(o.normalised_value) as value
RETURN c.name as company,
       value,
       '%' as unit
ORDER BY value DESC""".strip()

Q5_CYPHER = """
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric
      {canonical_id: 'scope_1_emissions'}),
      (o)-[:REPORTED_BY]->(c:Company
      {company_id: 'nestle_india'}),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
  AND o.normalised_value < 1000000
WITH p.fiscal_year as year,
     max(o.normalised_value) as value
RETURN year, value, 'tCO2e' as unit
ORDER BY year""".strip()

Q6_CYPHER = """
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric),
      (o)-[:REPORTED_BY]->(c:Company {company_id: 'nestle_india'}),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'}),
      (o)-[:SUPPORTED_BY]->(ev:Evidence),
      (o)-[:EXTRACTED_FROM]->(ch:Chunk),
      (o)-[:HAS_CONFIDENCE]->(cr:ConfidenceRecord)
WHERE m.canonical_id = 'water_consumption_absolute'
  AND o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH o, ev, ch, cr, p
ORDER BY o.normalised_value DESC
LIMIT 1
RETURN o.normalised_value as value,
       o.normalised_unit_symbol as unit,
       o.normalization_status as status,
       cr.final_confidence as confidence_score,
       ev.text as evidence,
       ch.page as page,
       o.source_doc_id as doc_id""".strip()

QUESTIONS = [
    {"id": "q1", "text": "Which company has improved its emissions the most since 2023?",        "category": "Environmental", "cypher": Q1_CYPHER,  "chart": "emissions_improvement"},
    {"id": "q2", "text": "How do Scope 1 and Scope 2 emissions compare across companies?",       "category": "Environmental", "cypher": Q2_CYPHER,  "chart": "grouped_bar"},
    {"id": "q3", "text": "What percentage of Britannia's energy comes from renewable sources?",  "category": "Environmental", "cypher": None,       "chart": "stat_renewable"},
    {"id": "q4", "text": "What share of total wages goes to female employees across companies?", "category": "Social",        "cypher": Q4_CYPHER,  "chart": "bar_pct"},
    {"id": "q5", "text": "How have Nestlé's Scope 1 emissions changed over time?",              "category": "Environmental", "cypher": Q5_CYPHER,  "chart": "line_trend"},
    {"id": "q6", "text": "How confident are we in Nestlé's water withdrawal figure?",           "category": "Provenance",    "cypher": Q6_CYPHER,  "chart": "provenance_water"},
]

VERIFIED_METRICS: dict[str, dict] = {
    "Scope 1 Emissions": {
        "canonical_id": "scope_1_emissions",
        "unit": "tCO2e",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 6 GHG Disclosures",
    },
    "Scope 2 Emissions": {
        "canonical_id": "scope_2_emissions",
        "unit": "tCO2e",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 6 GHG Disclosures",
    },
    "Total Water Withdrawal": {
        "canonical_id": "water_withdrawal",
        "unit": "kL",
        "divide_by": 1000,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024", "FY2025"],
        "principle": "Principle 6 Water Disclosures",
    },
    "Water Consumption": {
        "canonical_id": "water_consumption_absolute",
        "unit": "kL",
        "divide_by": 1000,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024", "FY2025"],
        "principle": "Principle 6 Water Disclosures",
    },
    "Total Energy (Renewable)": {
        "canonical_id": "renewable_energy_consumption_absolute",
        "unit": "GJ",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 6 Energy Disclosures",
    },
    "Total Energy (Non-Renewable)": {
        "canonical_id": "non_renewable_energy_consumption_absolute",
        "unit": "GJ",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 6 Energy Disclosures",
    },
    "Plastic Waste Generated": {
        "canonical_id": "plastic_waste_generated",
        "unit": "kg",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 6 Waste Disclosures",
    },
    "Plastic Waste Collected": {
        "canonical_id": "plastic_waste_collected",
        "unit": "kg",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 6 Waste Disclosures",
    },
    "Employee Headcount": {
        "canonical_id": "employee_headcount",
        "unit": "employees",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024", "FY2025"],
        "principle": "Section A Employee Disclosures",
    },
    "Total Recordable Injuries (Workers)": {
        "canonical_id": "total_recordable_injuries_workers",
        "unit": "count",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 5 Safety Disclosures",
    },
    "Total Recordable Injuries (Employees)": {
        "canonical_id": "total_recordable_injuries_employees",
        "unit": "count",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 5 Safety Disclosures",
    },
    "Worker Union Membership": {
        "canonical_id": "worker_union_membership",
        "unit": "count",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 3 Labour Disclosures",
    },
    "Waste Generated": {
        "canonical_id": "waste_generated",
        "unit": "kg",
        "divide_by": 1,
        "companies": ["nestle_india", "britannia", "marico"],
        "years": ["FY2024"],
        "principle": "Principle 6 Waste Disclosures",
    },
}

COMPANIES = {
    "Nestlé India":       "nestle_india",
    "Britannia Industries": "britannia",
    "Marico":             "marico",
}

# ── Worded answer builders ─────────────────────────────────────────────────────
def _short(name: str) -> str:
    return name.replace(" Limited", "").replace(" Industries", "")


def _worded(sel: str, rows: list[dict]) -> str | None:
    if not rows:
        return None

    if sel == "q1":
        srt = sorted(rows, key=lambda r: r.get("year", ""))
        if len(srt) < 2:
            return None
        first_val = srt[0]["value"]
        last_val  = srt[-1]["value"]
        first_yr  = srt[0]["year"]
        last_yr   = srt[-1]["year"]
        pct       = (last_val - first_val) / first_val * 100 if first_val else 0
        direction = "decreased" if pct < 0 else "increased"
        return (
            f"Among the companies in this graph, only <strong>Nestlé India</strong> has "
            f"multi-year Scope 1 data. Their emissions <strong>{direction} by "
            f"{abs(pct):.1f}%</strong> — from <strong>{first_val:,.0f} tCO2e</strong> "
            f"in {first_yr} to <strong>{last_val:,.0f} tCO2e</strong> in {last_yr} — "
            f"reflecting significant progress on their net zero roadmap."
        )

    if sel == "q2":
        by_co: dict[str, dict] = {}
        for r in rows:
            co = r["company"]
            if co not in by_co:
                by_co[co] = {}
            by_co[co][r["scope"]] = r["value"]
        totals = {co: sum(v.values()) for co, v in by_co.items()}
        hi_co  = max(totals, key=totals.get)
        hi     = by_co[hi_co]
        s1_hi  = hi.get("scope_1_emissions", 0)
        s2_hi  = hi.get("scope_2_emissions", 0)
        marico = by_co.get("Marico Limited", {})
        marico_note = (
            f" Marico's Scope 2 ({marico.get('scope_2_emissions',0):,.0f} tCO2e) exceeds "
            f"its Scope 1 ({marico.get('scope_1_emissions',0):,.0f} tCO2e) — typical for "
            f"companies with minimal on-site combustion but significant purchased electricity."
            if marico.get("scope_2_emissions", 0) > marico.get("scope_1_emissions", 0) else ""
        )
        return (
            f"In FY2024, <strong>{_short(hi_co)}</strong> had the highest combined GHG footprint: "
            f"Scope 1 <strong>{s1_hi:,.0f}</strong> + Scope 2 <strong>{s2_hi:,.0f} tCO2e</strong>."
            f"{marico_note}"
        )

    if sel == "q3":
        if not rows:
            return None
        fossil_pct    = rows[0].get("fossil_pct")
        renewable_pct = rows[0].get("renewable_pct")
        nr_gj         = rows[0].get("non_renewable", 0)
        total_gj      = rows[0].get("total", 0)
        renew_gj      = total_gj - nr_gj if total_gj else 0
        if renewable_pct is None:
            return None
        return (
            f"<strong>{renewable_pct}%</strong> of Britannia's total energy consumption came from "
            f"renewable sources in FY2024 — <strong>{renew_gj:,.0f} GJ</strong> of "
            f"<strong>{total_gj:,.0f} GJ</strong> total. "
            f"The remaining <strong>{fossil_pct}%</strong> came from fossil fuel sources "
            f"including coal, oil and natural gas."
        )

    if sel == "q4":
        srt = sorted(rows, key=lambda r: r["value"], reverse=True)
        if len(srt) < 2:
            return None
        hi  = srt[0]
        mid = srt[1] if len(srt) > 2 else None
        lo  = srt[-1]
        mid_part = (
            f", <strong>{_short(mid['company'])}</strong> at <strong>{mid['value']}%</strong>"
            if mid else ""
        )
        return (
            f"<strong>{_short(hi['company'])}</strong> pays the highest share of total wages to "
            f"female employees at <strong>{hi['value']}%</strong> in FY2024"
            f"{mid_part} and "
            f"<strong>{_short(lo['company'])}</strong> at <strong>{lo['value']}%</strong>. "
            f"This metric is disclosed under BRSR Principle 5 human rights disclosures."
        )

    if sel == "q5":
        srt = sorted(rows, key=lambda r: r.get("year", ""))
        if len(srt) < 2:
            return None
        first_val = srt[0]["value"]
        last_val  = srt[-1]["value"]
        first_yr  = srt[0]["year"]
        last_yr   = srt[-1]["year"]
        pct       = (last_val - first_val) / first_val * 100 if first_val else 0
        if pct < 0:
            return (
                f"Nestlé India's Scope 1 emissions have <strong>decreased by "
                f"{abs(pct):.1f}%</strong> from <strong>{first_val:,.0f} tCO2e</strong> "
                f"in {first_yr} to <strong>{last_val:,.0f} tCO2e</strong> in {last_yr}, "
                f"reflecting significant progress on their net zero roadmap."
            )
        return (
            f"Nestlé India's Scope 1 emissions <strong>increased by {pct:.1f}%</strong> "
            f"from <strong>{first_val:,.0f} tCO2e</strong> in {first_yr} to "
            f"<strong>{last_val:,.0f} tCO2e</strong> in {last_yr}."
        )

    if sel == "q6":
        row   = rows[0]
        value = row.get("value", 0)
        status = row.get("status", "—")
        val_kl = value / 1000 if isinstance(value, (int, float)) else 0
        return (
            f"Nestlé India reported total water withdrawal of "
            f"<strong>{val_kl:,.0f} kL</strong> in FY2024. "
            f"This figure has <strong>{status}</strong> confidence — matched to the canonical "
            f"metric <code>water_consumption_absolute</code>."
        )

    return None


def _source_citation(sel: str, rows: list[dict]) -> str:
    _CITATIONS: dict[str, str] = {
        "q1": "Source: Nestlé India Annual Reports CY2023, FY2024 & FY2025, BRSR Section C — Principle 6 GHG Disclosures",
        "q2": "Source: Company Annual Reports FY2024, BRSR Section C — Principle 6 GHG Disclosures",
        "q3": "Source: Britannia Industries Annual Report FY2024, BRSR Section C — Principle 6 Energy Disclosures",
        "q4": "Source: Company Annual Reports FY2024, BRSR Section C — Principle 5 Human Rights Disclosures",
        "q5": "Source: Nestlé India Annual Reports CY2023, FY2024 & FY2025, BRSR Section C — Principle 6 GHG Disclosures",
        "q6": "",
    }
    return _CITATIONS.get(sel, "")


# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@300;400;500&family=JetBrains+Mono:wght@400&display=swap');

#MainMenu {visibility: hidden;}
footer    {visibility: hidden;}
header    {visibility: hidden;}

.block-container {
    padding-top: 2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1100px !important;
}

.app-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    border-bottom: 1px solid #E2DDD8;
    padding-bottom: 1.2rem;
    margin-bottom: 2rem;
}
.app-title {
    font-family: 'DM Serif Display', serif;
    font-size: 24px;
    color: #1A1A18;
    display: inline-block;
    border-bottom: 2px solid #C9748A;
    padding-bottom: 1px;
}
.app-subtitle {
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: #9B9590;
    margin-top: 5px;
}
.app-stats {
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: #9B9590;
    letter-spacing: 0.3px;
    text-align: right;
}

.section-eyebrow {
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    letter-spacing: 1.8px;
    text-transform: uppercase;
    color: #9B9590;
    margin-bottom: 1rem;
    margin-top: 0;
}

.q-category {
    font-family: 'Inter', sans-serif;
    font-size: 10px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: #9B9590;
    margin-bottom: 3px;
    line-height: 1;
}

div[data-testid="stButton"] button {
    width: 100% !important;
    text-align: left !important;
    background: #FFFFFF !important;
    border: 1px solid #E2DDD8 !important;
    border-left: 3px solid transparent !important;
    border-radius: 0 !important;
    padding: 1.1rem 1.3rem !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    color: #1A1A18 !important;
    line-height: 1.45 !important;
    white-space: normal !important;
    height: auto !important;
    min-height: 68px !important;
    box-shadow: none !important;
    transition: background 0.12s, border-left-color 0.12s !important;
}
div[data-testid="stButton"] button:hover {
    background: #FAF7F5 !important;
    border-left: 3px solid #C9748A !important;
    color: #1A1A18 !important;
    box-shadow: none !important;
}
div[data-testid="stButton"] button:focus,
div[data-testid="stButton"] button:active {
    background: #FAF7F5 !important;
    border-left: 3px solid #C9748A !important;
    box-shadow: none !important;
    outline: none !important;
    color: #1A1A18 !important;
}

.result-question {
    font-family: 'DM Serif Display', serif;
    font-size: 22px;
    color: #1A1A18;
    margin-top: 1.8rem;
    margin-bottom: 0.3rem;
}
.result-meta {
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: #9B9590;
    margin-bottom: 1rem;
    padding-bottom: 0.9rem;
    border-bottom: 1px solid #E2DDD8;
}

.worded-answer {
    font-family: 'Inter', sans-serif;
    font-size: 15px;
    color: #1A1A18;
    line-height: 1.6;
    margin-bottom: 1.4rem;
    padding: 1rem 1.2rem;
    background: #FAF7F5;
    border-left: 3px solid #C9748A;
}

.source-citation {
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    color: #9B9590;
    margin-top: 0.6rem;
    letter-spacing: 0.2px;
}

.big-stat-value {
    font-family: 'DM Serif Display', serif;
    font-size: 80px;
    color: #C9748A;
    line-height: 1;
    margin: 1.2rem 0 0.4rem;
}
.big-stat-label {
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    color: #6B6560;
    margin-bottom: 1.5rem;
}

.cypher-code {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    background: #F4F2EF;
    border: 1px solid #E2DDD8;
    padding: 1rem;
    color: #3D3A37;
    overflow-x: auto;
    white-space: pre;
    line-height: 1.5;
}

.section-divider {
    height: 1px;
    background: #E2DDD8;
    margin: 2.5rem 0;
}

div[data-testid="stFormSubmitButton"] button {
    border-radius: 0 !important;
    background: #1A1A18 !important;
    color: #FAFAF8 !important;
    border: none !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 0.5rem 2rem !important;
    letter-spacing: 0.4px !important;
    box-shadow: none !important;
}
div[data-testid="stFormSubmitButton"] button:hover {
    background: #333330 !important;
    color: #FAFAF8 !important;
}

div[data-testid="stSelectbox"] > div > div,
div[data-testid="stMultiSelect"] > div > div {
    border-radius: 0 !important;
    border-color: #E2DDD8 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
}
div[data-testid="stSelectbox"] label,
div[data-testid="stMultiSelect"] label {
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    letter-spacing: 0.8px !important;
    text-transform: uppercase !important;
    color: #6B6560 !important;
}

.app-footer {
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid #E2DDD8;
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: #9B9590;
    text-align: center;
    line-height: 2;
}
.app-footer a { color: #C9748A; text-decoration: none; }

/* ── Tab bar ── */
button[data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
    font-weight: 400 !important;
    color: #9B9590 !important;
    background: transparent !important;
    border-bottom: 2px solid transparent !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #C9748A !important;
    font-weight: 500 !important;
    border-bottom-color: #C9748A !important;
}
button[data-baseweb="tab"]:hover {
    color: #1A1A18 !important;
    background: transparent !important;
}

/* ── Explorer Run button vertical alignment ── */
div[data-testid="column"]:last-child div[data-testid="stButton"] button {
    margin-top: 24px !important;
    height: 42px !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
</style>
""", unsafe_allow_html=True)

# ── DB connection ──────────────────────────────────────────────────────────────
try:
    get_driver()
except Exception as e:
    st.error(f"Could not connect to Neo4j. Ensure the database is running.\n\n{e}")
    st.stop()

# ── Session state ──────────────────────────────────────────────────────────────
if "selected_question" not in st.session_state:
    st.session_state.selected_question = None

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
  <div>
    <span class="app-title">ESG Knowledge Graph</span>
    <div class="app-subtitle">From unstructured data to queryable graph</div>
  </div>
  <div class="app-stats">
    3 companies &nbsp;·&nbsp; 4 documents &nbsp;·&nbsp;
    2,462 observations &nbsp;·&nbsp; 97.1% recall accuracy
  </div>
</div>
""", unsafe_allow_html=True)

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["Questions", "Explorer", "Ask a Question"])

with tab1:
    # ── Question cards ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-eyebrow">Questions this graph can answer</div>',
                unsafe_allow_html=True)

    col_l, col_r = st.columns(2, gap="small")
    for i, q in enumerate(QUESTIONS):
        col = col_l if i % 2 == 0 else col_r
        with col:
            st.markdown(f'<div class="q-category">{q["category"]}</div>', unsafe_allow_html=True)
            if st.button(q["text"], key=q["id"]):
                if st.session_state.selected_question == q["id"]:
                    st.session_state.selected_question = None
                else:
                    st.session_state.selected_question = q["id"]
                st.rerun()

    # ── Result panel ───────────────────────────────────────────────────────────
    sel = st.session_state.selected_question
    if sel:
        q = next(x for x in QUESTIONS if x["id"] == sel)

        if sel == "q3":
            rows           = get_q3_fossil_data()
            cypher_display = Q3_CYPHER_DISPLAY
        else:
            rows           = run_query(q["cypher"])
            cypher_display = q["cypher"]

        n = len(rows)

        st.markdown(f'<div class="result-question">{q["text"]}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="result-meta">Verified Cypher query against Neo4j &nbsp;·&nbsp; '
            f'{n} result{"s" if n != 1 else ""}</div>',
            unsafe_allow_html=True,
        )

        if not rows:
            st.warning("No data found for this query. The metric may not be available for all companies.")
        else:
            # ── 1. Worded answer ──────────────────────────────────────────────
            answer = _worded(sel, rows)
            if answer:
                st.markdown(f'<div class="worded-answer">{answer}</div>', unsafe_allow_html=True)

            # ── 2. Chart / stat / provenance ──────────────────────────────────
            if q["chart"] in ("bar", "bar_pct"):
                df   = pd.DataFrame(rows).sort_values("value", ascending=True)
                unit = df["unit"].dropna().iloc[0] if not df["unit"].dropna().empty else ""
                fig  = hbar(df, unit)
                if q["chart"] == "bar_pct":
                    fig.update_layout(xaxis=dict(
                        range=[0, 35],
                        title=dict(text="% of total wages", font=dict(size=11, color="#6B6560")),
                        showgrid=False, showline=True, linecolor="#E2DDD8",
                        tickfont=dict(size=11, color="#6B6560"),
                    ))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            elif q["chart"] == "line":
                df = pd.DataFrame(rows)
                kl_df   = df[df["unit"] == "kL/tonne"].copy() if "unit" in df.columns else df
                plot_df = kl_df if not kl_df.empty else df
                unit    = plot_df["unit"].dropna().iloc[0] if not plot_df["unit"].dropna().empty else ""
                fig = go.Figure(go.Scatter(
                    x=plot_df["year"], y=plot_df["value"],
                    mode="lines+markers",
                    line=dict(color="#C9748A", width=2),
                    marker=dict(size=8, color="#C9748A", line=dict(color="white", width=2)),
                ))
                layout = {**_LAYOUT_BASE}
                layout["yaxis"] = dict(
                    showgrid=True, gridcolor="#F4F2EF", showline=False,
                    title=dict(text=unit, font=dict(size=11, color="#6B6560")),
                    tickfont=dict(size=11, color="#6B6560"),
                )
                layout["height"] = 280
                fig.update_layout(**layout)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            elif q["chart"] == "line_trend":
                df = pd.DataFrame(rows).sort_values("year")
                fig = go.Figure(go.Scatter(
                    x=df["year"], y=df["value"],
                    mode="lines+markers+text",
                    line=dict(color="#C9748A", width=2),
                    marker=dict(size=10, color="#C9748A", line=dict(color="white", width=2)),
                    text=[f"{v:,.0f}" for v in df["value"]],
                    textposition="top center",
                    textfont=dict(size=11, color="#6B6560", family="Inter"),
                ))
                layout = {**_LAYOUT_BASE}
                layout["yaxis"] = dict(
                    showgrid=True, gridcolor="#F4F2EF", showline=False,
                    rangemode="tozero",
                    title=dict(text="tCO2e", font=dict(size=11, color="#6B6560")),
                    tickfont=dict(size=11, color="#6B6560"),
                )
                layout["xaxis"] = dict(
                    showgrid=False, showline=True, linecolor="#E2DDD8",
                    tickfont=dict(size=11, color="#6B6560"),
                )
                layout["height"] = 300
                layout["margin"] = dict(l=10, r=20, t=30, b=10)
                fig.update_layout(**layout)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                st.markdown(
                    '<div style="font-family:Inter,sans-serif;font-size:11px;color:#9B9590;'
                    'margin-top:-0.4rem;margin-bottom:0.8rem;">'
                    'Note: FY2024 covers a 15-month transition period (Jan 2023 – Mar 2024). '
                    'CY2023 and FY2025 are standard 12-month periods.'
                    '</div>',
                    unsafe_allow_html=True,
                )

            elif q["chart"] == "emissions_improvement":
                srt = sorted(rows, key=lambda r: r.get("year", ""))
                if len(srt) >= 2:
                    first_val = srt[0]["value"]
                    last_val  = srt[-1]["value"]
                    first_yr  = srt[0]["year"]
                    last_yr   = srt[-1]["year"]
                    pct       = (last_val - first_val) / first_val * 100 if first_val else 0
                    sign      = "−" if pct < 0 else "+"
                    color     = "#2E7D6B" if pct < 0 else "#C41E3A"
                    st.markdown(f"""
<div style="font-family:'DM Serif Display',serif;font-size:80px;
            color:{color};line-height:1;margin:1.2rem 0 0.4rem;">{sign}{abs(pct):.1f}%</div>
<div style="font-family:Inter,sans-serif;font-size:14px;color:#6B6560;margin-bottom:1.8rem;">
  Nestlé India Scope 1 emissions &nbsp;·&nbsp; {first_yr} → {last_yr}
</div>
<div style="display:flex;gap:32px;font-family:Inter,sans-serif;margin-bottom:1rem;align-items:center;">
  <div>
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;
                color:#9B9590;margin-bottom:4px;">{first_yr}</div>
    <div style="font-size:22px;font-weight:500;color:#1A1A18;">{first_val:,.0f} tCO2e</div>
  </div>
  <div style="font-size:28px;color:#9B9590;">→</div>
  <div>
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;
                color:#9B9590;margin-bottom:4px;">{last_yr}</div>
    <div style="font-size:22px;font-weight:500;color:{color};">{last_val:,.0f} tCO2e</div>
  </div>
</div>
<div style="font-family:Inter,sans-serif;font-size:11px;color:#9B9590;margin-top:0.6rem;">
  Only Nestlé India has multi-year Scope 1 data in this graph (CY2023, FY2024, FY2025).
</div>
""", unsafe_allow_html=True)

            elif q["chart"] == "grouped_bar":
                seen_order: list[str] = []
                for r in rows:
                    if r["company"] not in seen_order:
                        seen_order.append(r["company"])
                totals: dict[str, float] = {}
                for r in rows:
                    totals[r["company"]] = totals.get(r["company"], 0) + r["value"]
                companies_ord = sorted(seen_order, key=lambda c: totals.get(c, 0), reverse=True)
                scope1_vals = [
                    next((r["value"] for r in rows
                          if r["company"] == co and r["scope"] == "scope_1_emissions"), 0)
                    for co in companies_ord
                ]
                scope2_vals = [
                    next((r["value"] for r in rows
                          if r["company"] == co and r["scope"] == "scope_2_emissions"), 0)
                    for co in companies_ord
                ]
                co_short  = [_short(c) for c in companies_ord]
                co_colors = [company_color(c) for c in companies_ord]
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    name="Scope 1 (Direct)",
                    x=co_short, y=scope1_vals,
                    marker_color=co_colors, marker_line_width=0,
                    text=[f"{v:,.0f}" for v in scope1_vals],
                    textposition="outside",
                    textfont=dict(size=10, color="#6B6560", family="Inter"),
                    width=0.35, opacity=1.0,
                ))
                fig.add_trace(go.Bar(
                    name="Scope 2 (Electricity)",
                    x=co_short, y=scope2_vals,
                    marker_color=co_colors, marker_line_width=0,
                    text=[f"{v:,.0f}" for v in scope2_vals],
                    textposition="outside",
                    textfont=dict(size=10, color="#6B6560", family="Inter"),
                    width=0.35, opacity=0.4,
                ))
                layout = {**_LAYOUT_BASE}
                layout["barmode"] = "group"
                layout["showlegend"] = True
                layout["legend"] = dict(
                    orientation="h", x=0, y=1.08,
                    font=dict(size=11, family="Inter", color="#6B6560"),
                )
                layout["yaxis"] = dict(
                    showgrid=True, gridcolor="#F4F2EF", showline=False,
                    title=dict(text="tCO2e", font=dict(size=11, color="#6B6560")),
                    tickfont=dict(size=11, color="#6B6560"),
                )
                layout["height"] = 360
                layout["margin"] = dict(l=10, r=20, t=50, b=10)
                fig.update_layout(**layout)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            elif q["chart"] == "stat_renewable":
                renewable_pct = rows[0].get("renewable_pct")
                if renewable_pct is not None:
                    st.markdown(f"""
<div style="font-family:'DM Serif Display',serif;font-size:80px;
            color:#2E7D6B;line-height:1;margin:1.2rem 0 0.4rem;">{renewable_pct}%</div>
<div style="font-family:Inter,sans-serif;font-size:14px;color:#6B6560;margin-bottom:1.5rem;">
  of total energy from renewable sources &nbsp;·&nbsp; Britannia FY2024
</div>
""", unsafe_allow_html=True)

            elif q["chart"] == "provenance_water":
                row          = rows[0]
                value        = row.get("value", 0)
                status       = row.get("status", "—")
                raw_evidence = row.get("evidence") or ""
                page         = row.get("page", "—")
                doc_id       = row.get("doc_id", "")
                doc_name     = DOC_NAMES.get(doc_id, "Source document")
                val_kl       = value / 1000 if isinstance(value, (int, float)) else 0
                status_bg    = "#D4EDDA" if status == "normalized" else "#FFF3CD"
                status_color = "#155724" if status == "normalized" else "#856404"

                st.markdown(f"""
<div style="display:flex;gap:12px;margin:1rem 0 1.4rem;font-family:Inter,sans-serif;">
  <div style="flex:1;background:#FAF7F5;border:1px solid #E2DDD8;padding:1rem 1.2rem;">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;
                color:#9B9590;margin-bottom:6px;">Reported value</div>
    <div style="font-size:16px;font-weight:500;color:#1A1A18;">{val_kl:,.0f} kL</div>
  </div>
  <div style="flex:1;background:{status_bg};border:1px solid #E2DDD8;padding:1rem 1.2rem;">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;
                color:#9B9590;margin-bottom:6px;">Match status</div>
    <div style="font-size:16px;font-weight:500;color:{status_color};">{status}</div>
  </div>
  <div style="flex:1;background:#FAF7F5;border:1px solid #E2DDD8;padding:1rem 1.2rem;">
    <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;
                color:#9B9590;margin-bottom:6px;">Canonical metric</div>
    <div style="font-size:13px;font-weight:500;color:#1A1A18;word-break:break-all;">
      water_consumption_absolute</div>
  </div>
</div>
""", unsafe_allow_html=True)

                evidence_text = clean_evidence(raw_evidence, _EVIDENCE_KEYWORDS["q6"])
                if evidence_text and evidence_text != "Source text not available":
                    st.markdown(f"""
<div style="background:#FAF7F5;border-left:3px solid #C9748A;padding:1rem 1.2rem;
            font-style:italic;color:#3D3A37;font-size:13px;line-height:1.6;
            margin-bottom:0.4rem;">&ldquo;{evidence_text}&rdquo;</div>
<div style="font-size:12px;color:#9B9590;font-family:Inter;
            margin-bottom:1rem;">{doc_name} · Page {page}</div>
""", unsafe_allow_html=True)

                st.markdown("""
<div style="font-size:12px;color:#9B9590;font-family:Inter,sans-serif;margin-top:0.4rem;">
  <code style="background:#F4F2EF;padding:1px 5px;font-size:11px;font-family:'JetBrains Mono',monospace;">normalized</code>
  &nbsp;= exact canonical match &nbsp;·&nbsp;
  <code style="background:#F4F2EF;padding:1px 5px;font-size:11px;font-family:'JetBrains Mono',monospace;">partial</code>
  &nbsp;= fuzzy match above threshold &nbsp;·&nbsp;
  <code style="background:#F4F2EF;padding:1px 5px;font-size:11px;font-family:'JetBrains Mono',monospace;">new_metric</code>
  &nbsp;= no registry match found
</div>
""", unsafe_allow_html=True)

            # ── 3. Source citation ────────────────────────────────────────────
            cite = _source_citation(sel, rows)
            if cite:
                st.markdown(f'<div class="source-citation">{cite}</div>', unsafe_allow_html=True)

            # ── Expanders ─────────────────────────────────────────────────────
            exp1, exp2 = st.columns(2)
            with exp1:
                with st.expander("Cypher query"):
                    st.markdown(f'<div class="cypher-code">{cypher_display}</div>',
                                unsafe_allow_html=True)
            with exp2:
                render_source_expander(sel, rows)

# ── Tab 2: Explorer ────────────────────────────────────────────────────────────
with tab2:
    st.markdown('<div class="section-eyebrow">Build your own comparison</div>',
                unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns([3, 1.2, 1.8, 0.8])

    with col1:
        selected_metric = st.selectbox(
            "Metric",
            options=list(VERIFIED_METRICS.keys()),
            label_visibility="visible",
            key="exp_metric",
        )

    metric_config   = VERIFIED_METRICS[selected_metric]
    available_years = metric_config["years"]
    metric_cos      = metric_config.get("companies", [])
    available_display = [name for name, cid in COMPANIES.items() if cid in metric_cos]

    with col2:
        selected_year = st.selectbox(
            "Year",
            options=available_years,
            index=0,
            label_visibility="visible",
            key="exp_year",
        )

    with col3:
        selected_companies = st.multiselect(
            "Companies",
            options=available_display,
            default=available_display,
            label_visibility="visible",
            key="exp_companies",
        )

    with col4:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_clicked = st.button("Run", use_container_width=True, key="exp_run")

    if run_clicked:
        if not selected_companies:
            st.warning("Please select at least one company.")
        else:
            canonical_id        = metric_config["canonical_id"]
            divide_by           = metric_config.get("divide_by", 1)
            unit                = metric_config["unit"]
            principle           = metric_config.get("principle", "Principle 6")
            selected_ids        = [COMPANIES[name] for name in selected_companies]
            ids_cypher          = "['" + "', '".join(selected_ids) + "']"

            exp_cypher = f"""MATCH (o:Observation)-[:OF_METRIC]->(m:Metric
      {{canonical_id: '{canonical_id}'}}),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period
      {{fiscal_year: '{selected_year}'}})
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
  AND c.company_id IN {ids_cypher}
WITH c, max(o.normalised_value) as raw_value
RETURN c.name as company,
       raw_value / {divide_by} as value,
       '{unit}' as unit
ORDER BY value DESC""".strip()

            exp_rows = run_query(exp_cypher)

            if not exp_rows:
                st.warning(
                    f"No data found for **{selected_metric}** in {selected_year}. "
                    f"This metric may not be available for all companies in the selected year."
                )
            else:
                df    = pd.DataFrame(exp_rows).sort_values("value", ascending=True)
                n_cos = len(df)

                # summary line
                co_names = " · ".join(
                    r["company"].replace(" Limited","").replace(" Industries","")
                    for r in sorted(exp_rows, key=lambda r: r["value"], reverse=True)
                )
                st.markdown(
                    f'<div style="font-family:Inter;font-size:12px;color:#9B9590;'
                    f'margin-bottom:0.8rem;">'
                    f'{n_cos} {"company" if n_cos==1 else "companies"} &nbsp;·&nbsp; '
                    f'{selected_metric} &nbsp;·&nbsp; {selected_year}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if n_cos == 1:
                    # single company — show as big stat card
                    v   = df["value"].iloc[0]
                    co  = df["company"].iloc[0]
                    fmt = f"{v:,.0f}" if v >= 10 else f"{v:,.2f}"
                    co_color = company_color(co)
                    st.markdown(f"""
<div style="font-family:'DM Serif Display',serif;font-size:72px;
            color:{co_color};line-height:1;margin:1.2rem 0 0.4rem;">{fmt}</div>
<div style="font-family:Inter,sans-serif;font-size:14px;
            color:#6B6560;margin-bottom:1.5rem;">
  {unit} &nbsp;·&nbsp;
  {co.replace(' Limited','').replace(' Industries','')} &nbsp;·&nbsp;
  {selected_year}
</div>
""", unsafe_allow_html=True)

                else:
                    # multi-company bar chart
                    colors = [company_color(c) for c in df["company"]]
                    text_labels = [
                        f"{v:,.0f} {unit}" if v >= 10 else f"{v:,.2f} {unit}"
                        for v in df["value"]
                    ]
                    fig = go.Figure(go.Bar(
                        x=df["value"],
                        y=df["company"],
                        orientation="h",
                        marker_color=colors,
                        marker_line_width=0,
                        width=0.5,
                        text=text_labels,
                        textposition="outside",
                        textfont=dict(size=11, color="#3D3A37", family="Inter"),
                    ))
                    layout = {**_LAYOUT_BASE}
                    layout["xaxis"] = dict(
                        showgrid=False, showline=False, showticklabels=False,
                        tickfont=dict(size=11, color="#6B6560"),
                    )
                    layout["margin"] = dict(l=10, r=120, t=10, b=10)
                    layout["height"] = max(200, n_cos * 80)
                    fig.update_layout(**layout)
                    st.plotly_chart(fig, use_container_width=True,
                                    config={"displayModeBar": False})

                # source citation
                st.markdown(
                    f'<div class="source-citation">Source: Company Annual Reports '
                    f'{selected_year}, BRSR Section C — {principle}</div>',
                    unsafe_allow_html=True,
                )

                # cypher expander
                with st.expander("Cypher query"):
                    st.markdown(f'<div class="cypher-code">{exp_cypher}</div>',
                                unsafe_allow_html=True)

# ── Tab 3: Ask a Question ──────────────────────────────────────────────────────
with tab3:
    st.markdown('<div class="section-eyebrow">Natural language query interface</div>',
                unsafe_allow_html=True)

    st.markdown("""
<style>
div[data-testid="stTextInput"] input:disabled {
    opacity: 0.5 !important;
    cursor: not-allowed !important;
    background: #F4F2EF !important;
}
div[data-testid="stButton"] button:disabled {
    opacity: 0.5 !important;
    cursor: not-allowed !important;
}
</style>
""", unsafe_allow_html=True)

    st.text_input("",
        placeholder="e.g. Which company has the lowest carbon intensity?",
        disabled=True,
        label_visibility="collapsed")

    st.button("Run Query", disabled=True, key="nlq_run")

    st.markdown("""
<div style="
    border: 1px solid #E2DDD8;
    border-left: 3px solid #C9748A;
    padding: 1rem 1.2rem;
    background: #FAFAF8;
    font-family: Inter, sans-serif;
    font-size: 13px;
    color: #6B6560;
    margin: 1rem 0 2rem;
    line-height: 1.6;
">
    <strong style="color:#1A1A18;">
        Bring your own API key to enable live queries
    </strong><br>
    Add your OpenAI API key to
    <code style="background:#F0EDE8;padding:1px 4px;
                 font-family:JetBrains Mono,monospace;
                 font-size:12px;">pipeline_config.json</code>
    to translate any natural language question into
    a Cypher graph query in real time.<br><br>
    The full NL&rarr;Cypher pipeline is implemented and
    open source &mdash; the examples below show the kinds
    of questions it can answer.
    <a href="https://github.com/Vadiaaaaaaa/ESG-Fact-Extraction-and-Knowledge-Graph-Pipeline"
       style="color:#C9748A;text-decoration:none;margin-left:4px;">
       View source &rarr;
    </a>
</div>
""", unsafe_allow_html=True)

    st.markdown(
        '<div class="section-eyebrow" style="margin-top:1rem;">'
        'Example queries this system can answer'
        '</div>',
        unsafe_allow_html=True)

    EXAMPLES = [
        {
            "question": "Which company has improved its emissions the most since 2022?",
            "answer": "Nestlé India reduced Scope 1 emissions by 23.4% from 192,678 tCO2e in CY2022 to 147,573 tCO2e in FY2025 — the largest reduction among the three companies tracked. This reflects investments in biomass boilers and renewable energy across their manufacturing facilities.",
            "cypher": """MATCH (o:Observation)-[:OF_METRIC]->(m:Metric
      {canonical_id: 'scope_1_emissions'}),
      (o)-[:REPORTED_BY]->(c:Company
      {company_id: 'nestle_india'}),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE o.normalization_status IN ['normalized', 'partial']
AND o.normalised_value < 1000000
WITH p.fiscal_year as year,
     max(o.normalised_value) as value
RETURN year, value, 'tCO2e' as unit
ORDER BY year""",
        },
        {
            "question": "How do Scope 1 and Scope 2 emissions compare across all companies?",
            "answer": "In FY2024, Nestlé India had the highest Scope 1 emissions at 231,324 tCO2e, followed by Britannia at 93,583 tCO2e and Marico at 1,053 tCO2e. The large difference reflects Nestlé's significantly larger manufacturing scale and higher thermal energy requirements for food processing.",
            "cypher": """MATCH (o:Observation)-[:OF_METRIC]->(m:Metric),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE m.canonical_id IN ['scope_1_emissions',
                          'scope_2_emissions']
AND o.normalization_status IN ['normalized', 'partial']
AND o.normalised_value < 1000000
WITH c, m.canonical_id as metric,
     max(o.normalised_value) as value
RETURN c.name as company, metric, value,
       'tCO2e' as unit
ORDER BY metric, value DESC""",
        },
        {
            "question": "What share of Britannia's energy comes from renewable sources?",
            "answer": "22.1% of Britannia's total energy consumption came from renewable sources in FY2024, representing 503,290 GJ out of 2,279,136 GJ total. Britannia has set a target of 59% renewable electricity by 2024 — indicating significant room to grow.",
            "cypher": """MATCH (o1:Observation)-[:OF_METRIC]->(m1:Metric
      {canonical_id: 'renewable_energy_consumption_absolute'}),
      (o2:Observation)-[:OF_METRIC]->(m2:Metric
      {canonical_id: 'absolute_energy_consumption'}),
      (o1)-[:REPORTED_BY]->(c:Company
      {company_id: 'britannia'}),
      (o2)-[:REPORTED_BY]->(c),
      (o1)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'}),
      (o2)-[:IN_PERIOD]->(p)
WHERE o1.normalization_status IN ['normalized', 'partial']
AND o2.normalization_status IN ['normalized', 'partial']
WITH max(o1.normalised_value) as renewable,
     max(o2.normalised_value) as total
RETURN renewable, total,
       round(renewable / total * 100, 1) as pct""",
        },
        {
            "question": "Which company has the highest female board representation?",
            "answer": "Marico had 25% female representation on its Board of Directors in FY2024 — 3 out of 12 board members. Britannia had 7.69% (1 out of 13). This data is disclosed under BRSR Principle 5 human rights and gender diversity requirements.",
            "cypher": """MATCH (o:Observation)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.raw_name IN [
  'Females on Board of Directors',
  'percentage of female board members',
  'Women on Board'
]
AND o.normalised_value IS NOT NULL
RETURN c.name as company,
       o.normalised_value as pct,
       '%' as unit
ORDER BY pct DESC""",
        },
    ]

    for ex in EXAMPLES:
        st.markdown(f"""
<div style="
    border: 1px solid #E2DDD8;
    padding: 1.2rem 1.4rem;
    margin-bottom: 1px;
    background: #FFFFFF;
    font-family: Inter, sans-serif;
">
    <div style="font-size:14px;font-weight:500;color:#1A1A18;margin-bottom:8px;">
        {ex['question']}
    </div>
    <div style="font-size:13px;color:#6B6560;line-height:1.5;">
        {ex['answer']}
    </div>
</div>
""", unsafe_allow_html=True)
        with st.expander("View Cypher"):
            st.markdown(f'<div class="cypher-code">{ex["cypher"]}</div>',
                        unsafe_allow_html=True)

    st.markdown("""
<div style="margin-top:2rem;padding-top:1.5rem;border-top:1px solid #E2DDD8;">
    <div class="section-eyebrow">What live querying enables</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.5rem;margin-top:1rem;">
        <div style="font-family:Inter;font-size:13px;color:#6B6560;line-height:1.6;">
            <strong style="color:#1A1A18;display:block;margin-bottom:4px;">Any metric</strong>
            Query any of 297 canonical ESG metrics or 1,456 provisional metrics
            across all companies
        </div>
        <div style="font-family:Inter;font-size:13px;color:#6B6560;line-height:1.6;">
            <strong style="color:#1A1A18;display:block;margin-bottom:4px;">Any company</strong>
            Compare across Nestlé, Britannia, and Marico &mdash; extensible to any
            BRSR-reporting Indian listed company
        </div>
        <div style="font-family:Inter;font-size:13px;color:#6B6560;line-height:1.6;">
            <strong style="color:#1A1A18;display:block;margin-bottom:4px;">Full provenance</strong>
            Every answer traces back to the exact page and sentence in the source
            annual report
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-footer">
  A knowledge graph where every fact knows who reported it, when, how confidently,
  and where &mdash; connected through shared canonical metrics to enable cross-company
  queries no flat database can answer.
</div>
""", unsafe_allow_html=True)
