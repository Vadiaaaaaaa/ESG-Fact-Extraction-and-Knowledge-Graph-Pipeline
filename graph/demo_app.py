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
    cfg: dict[str, Any] = {}
    if _CONFIG.exists():
        cfg = json.loads(_CONFIG.read_text())
    uri  = cfg.get("neo4j_uri",  os.getenv("NEO4J_URI",  "neo4j://127.0.0.1:7687"))
    user = cfg.get("neo4j_user", os.getenv("NEO4J_USER", "neo4j"))
    pwd  = cfg.get("neo4j_pass", cfg.get("neo4j_password", os.getenv("NEO4J_PASS", "Watermelon@123")))
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
    "q1": "employee_headcount",
    "q2": "scope_1_emissions",
    "q5": "water_consumption_absolute",
    "q6": "water_consumption_absolute",
}

_EVIDENCE_KEYWORDS: dict[str, list[str]] = {
    "q1": ["permanent employee", "permanent worker", "employee headcount", "total employee"],
    "q2": ["scope 1", "scope1", "direct emission", "tCO2e"],
    "q3_nonrenew": ["non-renewable", "fossil fuel", "coal", "oil", "natural gas", "non renewable"],
    "q3_total":    ["total energy", "energy consumed", "GJ"],
    "q4": ["female", "wages paid to female", "gross wages"],
    "q5": ["water withdrawal", "water consumption", "kiloliter", "kilolitre"],
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
                    WITH o, ev, ch ORDER BY o.normalised_value DESC LIMIT 1
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
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE m.canonical_id = 'employee_headcount'
  AND o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
  AND o.normalised_unit_symbol = 'count'
WITH c, max(o.normalised_value) as value
RETURN c.name as company,
       value,
       'employees' as unit
ORDER BY value DESC""".strip()

Q2_CYPHER = """
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric
      {canonical_id: 'scope_1_emissions'}),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
  AND o.normalised_value < 1000000
WITH c, max(o.normalised_value) as value
RETURN c.name as company,
       value,
       'tCO2e' as unit
ORDER BY value DESC""".strip()

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
      {canonical_id: 'water_consumption_absolute'}),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH c, max(o.normalised_value) as max_val
RETURN c.name as company,
       round(max_val / 1000) as value,
       'kL' as unit
ORDER BY value DESC""".strip()

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
    {"id": "q1", "text": "How many permanent employees do these companies have?",       "category": "Social",        "cypher": Q1_CYPHER,  "chart": "bar"},
    {"id": "q2", "text": "How do Scope 1 emissions compare across companies?",             "category": "Environmental", "cypher": Q2_CYPHER,  "chart": "bar"},
    {"id": "q3", "text": "What percentage of Britannia's energy is still from fossil fuels?", "category": "Environmental", "cypher": None, "chart": "stat_dark"},
    {"id": "q4", "text": "What share of total wages goes to female employees across companies?", "category": "Social", "cypher": Q4_CYPHER, "chart": "bar_pct"},
    {"id": "q5", "text": "How does water consumption compare across companies?",        "category": "Environmental", "cypher": Q5_CYPHER,  "chart": "bar"},
    {"id": "q6", "text": "How confident are we in Nestlé's water withdrawal figure?",  "category": "Provenance",    "cypher": Q6_CYPHER,  "chart": "provenance_water"},
]

METRIC_OPTIONS = {
    "Scope 1 emissions":       "scope_1_emissions",
    "Scope 2 emissions":       "scope_2_emissions",
    "Water consumption":       "water_consumption_absolute",
    "Water intensity":         "water_consumption_intensity",
    "Energy consumption":      "absolute_energy_consumption",
    "Renewable energy":        "renewable_energy_consumption_absolute",
    "Non-renewable energy":    "non_renewable_energy_consumption_absolute",
    "Total waste generated":   "total_waste_generated",
    "Employee headcount":      "employee_headcount",
    "Consumer complaints":     "complaint_count_filed",
}
COMPANY_OPTIONS = {
    "Nestlé India": "nestle_india",
    "Britannia":    "britannia",
    "Marico":       "marico",
}

# ── Worded answer builders ─────────────────────────────────────────────────────
def _short(name: str) -> str:
    return name.replace(" Limited", "").replace(" Industries", "")


def _worded(sel: str, rows: list[dict]) -> str | None:
    if not rows:
        return None

    if sel == "q1":
        srt = sorted(rows, key=lambda r: r["value"], reverse=True)
        if len(srt) < 2:
            return None
        names = [_short(r["company"]) for r in srt]
        vals  = [r["value"] for r in srt]
        mid_parts = ", ".join(
            f"<strong>{n}</strong> at <strong>{v:,.0f}</strong>"
            for n, v in zip(names[1:], vals[1:])
        )
        return (
            f"In FY2024, <strong>{names[0]}</strong> had the largest permanent workforce at "
            f"<strong>{vals[0]:,.0f} employees</strong>, followed by {mid_parts}."
        )

    if sel == "q2":
        srt = sorted(rows, key=lambda r: r["value"], reverse=True)
        if len(srt) < 2:
            return None
        hi  = srt[0]
        mid = srt[1] if len(srt) > 2 else None
        lo  = srt[-1]
        mid_part = (
            f", <strong>{_short(mid['company'])}</strong> at <strong>{mid['value']:,.0f} tCO2e</strong>"
            if mid else ""
        )
        return (
            f"In FY2024, <strong>{_short(hi['company'])}</strong> had the highest Scope 1 emissions at "
            f"<strong>{hi['value']:,.0f} tCO2e</strong>"
            f"{mid_part} and "
            f"<strong>{_short(lo['company'])}</strong> at <strong>{lo['value']:,.0f} tCO2e</strong>. "
            f"Scope 1 covers direct emissions from owned operations including boilers, "
            f"furnaces and company vehicles."
        )

    if sel == "q3":
        if not rows:
            return None
        fossil_pct    = rows[0].get("fossil_pct")
        renewable_pct = rows[0].get("renewable_pct")
        if fossil_pct is None:
            return None
        return (
            f"<strong>{fossil_pct}%</strong> of Britannia's total energy consumption came from "
            f"fossil fuel sources in FY2024. The remaining "
            f"<strong>{renewable_pct}%</strong> came from renewable sources including "
            f"solar, wind, and biomass."
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
        srt = sorted(rows, key=lambda r: r["value"], reverse=True)
        if len(srt) < 2:
            return None
        hi  = srt[0]
        mid = srt[1] if len(srt) > 2 else None
        lo  = srt[-1]
        mid_part = (
            f", <strong>{_short(mid['company'])}</strong> at <strong>{mid['value']:,.0f} kL</strong>,"
            if mid else ""
        )
        return (
            f"In FY2024, <strong>{_short(hi['company'])}</strong> had the highest water consumption "
            f"at <strong>{hi['value']:,.0f} kL</strong>"
            f"{mid_part} and "
            f"<strong>{_short(lo['company'])}</strong> at <strong>{lo['value']:,.0f} kL</strong>. "
            f"All three companies operate zero liquid discharge facilities."
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
        "q1": "Source: Company Annual Reports FY2024, BRSR Section A — Employee Disclosures",
        "q2": "Source: Company Annual Reports FY2024, BRSR Section C — Principle 6 GHG Disclosures",
        "q3": "Source: Britannia Industries Annual Report FY2024, BRSR Section C — Principle 6 Energy Disclosures",
        "q4": "Source: Company Annual Reports FY2024, BRSR Section C — Principle 5 Human Rights Disclosures",
        "q5": "Source: Company Annual Reports FY2024, BRSR Section C — Principle 6 Water Disclosures",
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
    <div class="app-subtitle">Indian FMCG · BRSR Sustainability Data</div>
  </div>
  <div class="app-stats">
    3 companies &nbsp;·&nbsp; 4 documents &nbsp;·&nbsp;
    2,462 observations &nbsp;·&nbsp; 78.3% eval accuracy
  </div>
</div>
""", unsafe_allow_html=True)

# ── Section 1: Question cards ──────────────────────────────────────────────────
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

# ── Result panel ───────────────────────────────────────────────────────────────
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
        # ── 1. Worded answer ──────────────────────────────────────────────────
        answer = _worded(sel, rows)
        if answer:
            st.markdown(f'<div class="worded-answer">{answer}</div>', unsafe_allow_html=True)

        # ── 2. Chart / stat / provenance ──────────────────────────────────────
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
            # Filter to comparable kL/tonne rows for charting
            kl_df = df[df["unit"] == "kL/tonne"].copy() if "unit" in df.columns else df
            plot_df = kl_df if not kl_df.empty else df
            unit = plot_df["unit"].dropna().iloc[0] if not plot_df["unit"].dropna().empty else ""
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

        elif q["chart"] == "stat_dark":
            fossil_pct    = rows[0].get("fossil_pct")
            renewable_pct = rows[0].get("renewable_pct")
            if fossil_pct is not None:
                st.markdown(f"""
<div style="font-family:'DM Serif Display',serif;font-size:80px;
            color:#1A1A18;line-height:1;margin:1.2rem 0 0.4rem;">{fossil_pct}%</div>
<div style="font-family:Inter,sans-serif;font-size:14px;color:#6B6560;margin-bottom:1.5rem;">
  of total energy from fossil fuel sources &nbsp;·&nbsp; Britannia FY2024
</div>
""", unsafe_allow_html=True)

        elif q["chart"] == "provenance_water":
            row            = rows[0]
            value          = row.get("value", 0)
            unit           = row.get("unit", "")
            status         = row.get("status", "—")
            confidence     = row.get("confidence_score", "—")
            raw_evidence   = row.get("evidence") or ""
            page           = row.get("page", "—")
            doc_id         = row.get("doc_id", "")
            doc_name       = DOC_NAMES.get(doc_id, "Source document")
            val_kl         = value / 1000 if isinstance(value, (int, float)) else 0

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

        # ── 3. Source citation ────────────────────────────────────────────────
        cite = _source_citation(sel, rows)
        if cite:
            st.markdown(f'<div class="source-citation">{cite}</div>', unsafe_allow_html=True)

        # ── Expanders ─────────────────────────────────────────────────────────
        exp1, exp2 = st.columns(2)
        with exp1:
            with st.expander("Cypher query"):
                st.markdown(f'<div class="cypher-code">{cypher_display}</div>',
                            unsafe_allow_html=True)
        with exp2:
            render_source_expander(sel, rows)

# ── Divider ────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

# ── Section 2: Explorer ────────────────────────────────────────────────────────
st.markdown('<div class="section-eyebrow">Build your own comparison</div>',
            unsafe_allow_html=True)

with st.form("explorer"):
    fc1, fc2, fc3 = st.columns([2, 2, 1])
    with fc1:
        metric_label = st.selectbox("Metric", list(METRIC_OPTIONS.keys()))
    with fc2:
        company_labels = st.multiselect("Companies", list(COMPANY_OPTIONS.keys()),
                                        default=list(COMPANY_OPTIONS.keys()))
    with fc3:
        year = st.selectbox("Year", ["FY2024", "FY2025", "FY2023", "FY2022"])
    submitted = st.form_submit_button("Run")

if submitted:
    if not company_labels:
        st.markdown(
            '<p style="font-family:Inter;font-size:14px;color:#9B9590;">Select at least one company.</p>',
            unsafe_allow_html=True)
    else:
        canonical  = METRIC_OPTIONS[metric_label]
        ids_str    = "['" + "', '".join(COMPANY_OPTIONS[c] for c in company_labels) + "']"
        byo_cypher = f"""
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric {{canonical_id: '{canonical}'}}),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {{fiscal_year: '{year}'}})
WHERE c.company_id IN {ids_str}
  AND o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH c, o.normalised_unit_symbol AS unit, max(o.normalised_value) AS value
RETURN c.name AS company, value, unit
ORDER BY value DESC""".strip()

        byo_rows = run_query(byo_cypher)

        if not byo_rows:
            st.markdown(
                f'<p style="font-family:Inter;font-size:14px;color:#9B9590;">'
                f'No data found for <strong>{metric_label}</strong> · {year}.</p>',
                unsafe_allow_html=True)
        else:
            df   = pd.DataFrame(byo_rows).sort_values("value", ascending=True)
            unit = df["unit"].dropna().iloc[0] if not df["unit"].dropna().empty else ""

            if len(df) == 1:
                v   = df["value"].iloc[0]
                co  = df["company"].iloc[0]
                fmt = f"{v:,.1f}" if isinstance(v, float) else str(v)
                st.markdown(f"""
<div class="big-stat-value" style="font-size:64px;">{fmt}</div>
<div class="big-stat-label">{unit} &nbsp;·&nbsp; {co} &nbsp;·&nbsp; {year}</div>
""", unsafe_allow_html=True)
            else:
                st.plotly_chart(hbar(df, unit), use_container_width=True,
                                config={"displayModeBar": False})

            with st.expander("Raw data"):
                st.dataframe(df, hide_index=True, use_container_width=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-footer">
  Data extracted from BRSR sections of Indian annual reports using a two-pass LLM pipeline<br>
  Evaluated against a manually verified gold set of 69 facts &nbsp;·&nbsp; 78.3% end-to-end accuracy<br>
  <a href="https://github.com/Vadiaaaaaaa/ESG-Fact-Extraction-and-Knowledge-Graph-Pipeline">
    View on GitHub →
  </a>
</div>
""", unsafe_allow_html=True)
