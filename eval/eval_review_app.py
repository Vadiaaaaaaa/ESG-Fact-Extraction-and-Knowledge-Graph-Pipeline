"""
Manual eval review interface.

Loads eval results, shows each failure with full context from Neo4j,
lets you categorise it as: period_error | unit_error | value_error |
wrong_fact_matched | missing | canonical_only | correct.

Saves labels to eval_review_labels.json so you can resume.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import streamlit as st
from neo4j import GraphDatabase, READ_ACCESS

sys.path.insert(0, str(Path(__file__).parent))
from eval_gold_set import GOLD_FACTS

NEO4J_URI  = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "Watermelon@123"
LABELS_FILE = Path(__file__).parent / "eval_review_labels.json"

CATEGORIES = {
    "period_error":        "✅ Right fact, right value — WRONG YEAR attributed",
    "unit_error":          "✅ Right fact, right value — WRONG UNIT stored",
    "value_error":         "❌ Wrong number entirely (different fact or calculation error)",
    "wrong_fact_matched":  "❌ Eval matched a DIFFERENT fact with similar value",
    "missing":             "🔴 Pipeline never extracted this fact",
    "canonical_only":      "⚠️ Fact found, value/unit/period OK — only canonical_id missing",
    "correct":             "✅ Actually correct — gold set or eval logic was wrong",
}

CATEGORY_COLORS = {
    "period_error":       "#fff3cd",
    "unit_error":         "#d1ecf1",
    "value_error":        "#f8d7da",
    "wrong_fact_matched": "#f8d7da",
    "missing":            "#f5c6cb",
    "canonical_only":     "#d4edda",
    "correct":            "#d4edda",
    "unlabelled":         "#f8f9fa",
}


@st.cache_resource
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))


def load_labels() -> dict:
    if LABELS_FILE.exists():
        return json.loads(LABELS_FILE.read_text())
    return {}


def save_labels(labels: dict) -> None:
    LABELS_FILE.write_text(json.dumps(labels, indent=2))


def get_gold(fact_id: str) -> dict | None:
    for f in GOLD_FACTS:
        if f["fact_id"] == fact_id:
            return f
    return None


def fetch_graph_row(driver, obs_id: str) -> dict | None:
    with driver.session(database="neo4j", default_access_mode=READ_ACCESS) as s:
        rows = list(s.run("""
            MATCH (o:Observation {obs_id: $obs_id})-[:REPORTED_BY]->(c:Company)
            OPTIONAL MATCH (o)-[:IN_PERIOD]->(p:Period)
            OPTIONAL MATCH (o)-[:OF_METRIC]->(m:Metric)
            OPTIONAL MATCH (o)-[:SUPPORTED_BY]->(e:Evidence)
            RETURN o.obs_id AS obs_id,
                   o.raw_name AS raw_name,
                   o.raw_value AS raw_value,
                   o.raw_unit_string AS raw_unit_string,
                   o.normalised_value AS normalised_value,
                   o.normalised_unit_symbol AS unit,
                   o.normalization_status AS status,
                   o.canonical_id AS canonical_id,
                   o.source_doc_id AS source_doc_id,
                   o.period_label AS period_label,
                   p.fiscal_year AS fiscal_year,
                   m.display_name AS metric_name,
                   m.canonical_id AS metric_canonical_id,
                   e.text AS evidence_text
        """, obs_id=obs_id))
        return dict(rows[0]) if rows else None


def fetch_candidates(driver, expected_value: float, company_id: str = "nestle_india") -> list[dict]:
    """Fetch top 5 closest-value observations for manual inspection."""
    if expected_value == 0:
        lo, hi = -1.0, 1.0
    else:
        lo = expected_value * 0.96
        hi = expected_value * 1.04
    with driver.session(database="neo4j", default_access_mode=READ_ACCESS) as s:
        rows = list(s.run("""
            MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id: $cid}),
                  (o)-[:IN_PERIOD]->(p:Period)
            WHERE o.normalised_value >= $lo AND o.normalised_value <= $hi
            OPTIONAL MATCH (o)-[:OF_METRIC]->(m:Metric)
            OPTIONAL MATCH (o)-[:SUPPORTED_BY]->(e:Evidence)
            RETURN o.obs_id AS obs_id,
                   o.raw_name AS raw_name,
                   o.raw_value AS raw_value,
                   o.raw_unit_string AS raw_unit_string,
                   o.normalised_value AS value,
                   o.normalised_unit_symbol AS unit,
                   o.normalization_status AS status,
                   o.canonical_id AS canonical_id,
                   o.source_doc_id AS source_doc_id,
                   p.fiscal_year AS fiscal_year,
                   m.canonical_id AS m_canonical_id,
                   e.text AS evidence_text
            ORDER BY
                CASE WHEN o.source_doc_id CONTAINS 'fy2024' THEN 0 ELSE 1 END,
                abs(o.normalised_value - $expected) ASC
            LIMIT 5
        """, cid=company_id, lo=lo, hi=hi, expected=float(expected_value)))
        return [dict(r) for r in rows]


# ─── Build failure list from last eval output ──────────────────────────────────

FAILURES: list[dict] = []

# MISSED facts
MISSED_IDS = [
    "nestle_fy2024_g006", "nestle_fy2024_g014", "nestle_fy2024_g021",
    "nestle_fy2024_g022", "nestle_fy2024_g023", "nestle_fy2024_g024",
    "nestle_fy2024_g030", "nestle_fy2024_g032", "nestle_fy2024_g035",
]

# WRONG/PARTIAL facts — (fact_id, matched_obs_id_or_None, issues_list)
WRONG: list[tuple[str, str | None, list[str]]] = [
    ("nestle_fy2024_g001",  None, ["period=CY2021"]),
    ("nestle_fy2024_g003",  None, ["unit=count", "period=CY2022"]),
    ("nestle_fy2024_g004",  None, ["value=5.2 (expected ~5.12)"]),
    ("nestle_fy2024_g007",  None, ["period=CY2021"]),
    ("nestle_fy2024_g008",  None, ["unit=count", "period=CY2021"]),
    ("nestle_fy2024_g009",  None, ["period=CY2022"]),
    ("nestle_fy2024_g010",  None, ["canon=''"]),
    ("nestle_fy2024_g015",  None, ["unit=count"]),
    ("nestle_fy2024_g016",  None, ["period=FY2022"]),
    ("nestle_fy2024_g017",  None, ["value=66.0 (expected ~65)"]),
    ("nestle_fy2024_g018",  None, ["value=73.0 (expected ~73.9)", "period=CY2022"]),
    ("nestle_fy2024_g019",  None, ["value=92.0 (expected ~91)", "period=FY2022"]),
    ("nestle_fy2024_g020",  None, ["unit=kg/tonne", "period=FY2022"]),
    ("nestle_fy2024_g026",  None, ["value=4243 (expected ~4200)", "period=CY2022", "canon=''"]),
    ("nestle_fy2024_g028",  None, ["unit=%"]),
    ("nestle_fy2024_g029",  None, ["unit=count", "period=CY2022"]),
    ("nestle_fy2024_g031",  None, ["unit=INR", "period=CY2021"]),
    ("nestle_fy2024_g033",  None, ["canon=water_consumption_absolute"]),
    ("nestle_fy2024_g040",  None, ["unit=count"]),
    ("nestle_fy2024_g043",  None, ["canon=''"]),
    ("nestle_fy2024_g044",  None, ["unit=count"]),
    ("nestle_fy2024_g045",  None, ["unit=%"]),
    ("nestle_fy2024_g050",  None, ["canon=''"]),
    ("nestle_fy2024_g052",  None, ["canon=''"]),
    ("nestle_fy2024_g053",  None, ["canon=''"]),
    ("nestle_fy2024_g067",  None, ["value=92.0 (expected ~91)", "period=FY2022"]),
    ("nestle_fy2024_g068",  None, ["value=231324 (expected ~228900)", "unit=tCO2e"]),
]

for fid in MISSED_IDS:
    FAILURES.append({"fact_id": fid, "kind": "missing", "issues": ["NOT FOUND in graph"]})

for fid, obs_id, issues in WRONG:
    FAILURES.append({"fact_id": fid, "kind": "wrong", "obs_id": obs_id, "issues": issues})


# ─── Streamlit app ─────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Eval Review",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown("""
    <style>
    .gold-box { background:#e8f4f8; border-left:4px solid #0077b6; padding:0.8rem 1rem;
                border-radius:0 6px 6px 0; margin-bottom:0.5rem; font-family:monospace; }
    .graph-box { background:#fff8e1; border-left:4px solid #f4a100; padding:0.8rem 1rem;
                 border-radius:0 6px 6px 0; margin-bottom:0.5rem; font-family:monospace; }
    .issue-tag { background:#dc3545; color:white; padding:2px 8px; border-radius:10px;
                 font-size:0.8rem; margin-right:4px; }
    </style>
    """, unsafe_allow_html=True)

    driver = get_driver()
    labels = load_labels()

    # ── Sidebar: progress + summary ──────────────────────────────────────────
    with st.sidebar:
        st.title("Eval Review")
        st.divider()

        labelled = sum(1 for f in FAILURES if f["fact_id"] in labels)
        st.metric("Progress", f"{labelled} / {len(FAILURES)}")

        if labelled > 0:
            counts: dict[str, int] = {}
            for fid, cat in labels.items():
                counts[cat] = counts.get(cat, 0) + 1

            st.divider()
            st.subheader("Bucket counts")
            for cat, desc in CATEGORIES.items():
                n = counts.get(cat, 0)
                if n > 0:
                    emoji = desc.split()[0]
                    st.write(f"{emoji} **{cat}**: {n}")

        st.divider()
        if st.button("Export summary to JSON"):
            save_labels(labels)
            st.success(f"Saved to {LABELS_FILE}")

        # Filter
        st.divider()
        show_only = st.radio(
            "Show",
            ["All failures", "Unlabelled only", "Labelled only"],
            index=0,
        )

    # ── Main content ──────────────────────────────────────────────────────────
    st.title("Eval Failure Review")
    st.caption(
        "For each failure: read the gold expectation, see what the graph matched, "
        "then pick a category. Labels auto-save."
    )

    failures_to_show = FAILURES
    if show_only == "Unlabelled only":
        failures_to_show = [f for f in FAILURES if f["fact_id"] not in labels]
    elif show_only == "Labelled only":
        failures_to_show = [f for f in FAILURES if f["fact_id"] in labels]

    if not failures_to_show:
        st.success("Nothing to show for this filter.")
        return

    for i, failure in enumerate(failures_to_show):
        fid     = failure["fact_id"]
        kind    = failure["kind"]
        issues  = failure["issues"]
        gold    = get_gold(fid)
        current = labels.get(fid, "unlabelled")
        bg      = CATEGORY_COLORS.get(current, "#f8f9fa")

        with st.container():
            st.markdown(f"---")
            col_num, col_title = st.columns([0.5, 11])
            col_num.markdown(f"**{i+1}**")
            col_title.markdown(
                f"### `{fid}` &nbsp;&nbsp; "
                f"<span style='background:#6c757d;color:white;padding:2px 8px;"
                f"border-radius:8px;font-size:0.8rem'>{gold['difficulty']}</span> "
                f"&nbsp; Page {gold['source_page']}",
                unsafe_allow_html=True,
            )

            # Issue tags
            issue_html = " ".join(f"<span class='issue-tag'>{iss}</span>" for iss in issues)
            st.markdown(issue_html, unsafe_allow_html=True)

            col_left, col_right = st.columns(2)

            # ── Gold fact ──
            with col_left:
                st.markdown("**GOLD (ground truth)**")
                st.markdown(f"""<div class='gold-box'>
<b>raw_text:</b> {gold['raw_text']}<br>
<b>expected_value:</b> {gold['expected_value']:,}<br>
<b>expected_unit:</b> {gold['expected_unit']}<br>
<b>expected_period:</b> {gold['expected_period']}<br>
<b>expected_canonical:</b> {gold.get('expected_canonical') or '—'}<br>
<b>notes:</b> {gold['notes']}
</div>""", unsafe_allow_html=True)

            # ── Graph match ──
            with col_right:
                st.markdown("**GRAPH (what was found / matched)**")
                if kind == "missing":
                    st.error("Not found in graph at all.")
                    # Show closest candidates anyway
                    candidates = fetch_candidates(driver, gold["expected_value"])
                    if candidates:
                        st.markdown("*Closest values in graph (±4%):*")
                        for c in candidates[:3]:
                            st.markdown(f"""<div class='graph-box'>
<b>raw_name:</b> {c['raw_name']}<br>
<b>value:</b> {c['value']:,} {c['unit']}<br>
<b>period:</b> {c['fiscal_year']} | doc: {c['source_doc_id']}<br>
<b>canonical:</b> {c.get('canonical_id') or c.get('m_canonical_id') or '—'}<br>
<b>evidence:</b> {(c.get('evidence_text') or '')[:200]}
</div>""", unsafe_allow_html=True)
                else:
                    candidates = fetch_candidates(driver, gold["expected_value"])
                    if candidates:
                        top = candidates[0]
                        st.markdown(f"""<div class='graph-box'>
<b>raw_name:</b> {top['raw_name']}<br>
<b>raw_value:</b> {top.get('raw_value','')} | <b>raw_unit:</b> {top.get('raw_unit_string','')}<br>
<b>normalised:</b> {top['value']:,} {top['unit']}<br>
<b>period:</b> {top['fiscal_year']} | doc: {top['source_doc_id']}<br>
<b>canonical:</b> {top.get('canonical_id') or top.get('m_canonical_id') or '—'}<br>
<b>evidence:</b> {(top.get('evidence_text') or '')[:300]}
</div>""", unsafe_allow_html=True)
                        if len(candidates) > 1:
                            with st.expander("Other candidates"):
                                for c in candidates[1:]:
                                    st.write(f"`{c['raw_name']}` | {c['value']:,} {c['unit']} | {c['fiscal_year']} | {c['source_doc_id']}")

            # ── Category selector ──
            options = list(CATEGORIES.keys())
            current_idx = options.index(current) if current in options else len(options)
            if current == "unlabelled":
                display_options = ["— pick one —"] + options
                sel_idx = 0
            else:
                display_options = options
                sel_idx = options.index(current)

            col_sel, col_note = st.columns([3, 5])
            with col_sel:
                chosen = st.selectbox(
                    "Category",
                    display_options,
                    index=sel_idx,
                    key=f"sel_{fid}",
                    format_func=lambda x: f"{x}  —  {CATEGORIES.get(x, '')}" if x in CATEGORIES else x,
                )
                if chosen != "— pick one —" and chosen != labels.get(fid):
                    labels[fid] = chosen
                    save_labels(labels)
                    st.rerun()

            with col_note:
                note = st.text_input(
                    "Optional note",
                    value=labels.get(f"{fid}_note", ""),
                    key=f"note_{fid}",
                    placeholder="e.g. 'matched CY2022 row instead of FY2024'",
                )
                if note != labels.get(f"{fid}_note", ""):
                    labels[f"{fid}_note"] = note
                    save_labels(labels)

            # Current label badge
            if current != "unlabelled":
                color_map = {
                    "period_error": "orange", "unit_error": "blue",
                    "value_error": "red", "wrong_fact_matched": "red",
                    "missing": "red", "canonical_only": "green", "correct": "green",
                }
                badge_color = color_map.get(current, "grey")
                st.markdown(
                    f"<span style='background:{badge_color};color:white;padding:3px 12px;"
                    f"border-radius:10px;font-size:0.9rem'>✓ {current}</span>",
                    unsafe_allow_html=True,
                )


if __name__ == "__main__":
    main()
