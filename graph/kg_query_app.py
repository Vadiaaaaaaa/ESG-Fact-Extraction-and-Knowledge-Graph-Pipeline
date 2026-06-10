from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_ROOT / 'pipeline'), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

"""
ESG Knowledge Graph - Natural Language Query Interface.

Streamlit app that converts plain-English ESG questions into read-only Cypher,
runs them against Neo4j, and formats the graph results as a concise answer.
"""


import html
import json
import os
import re
import time
from typing import Any

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS
from openai import OpenAI

load_dotenv()


# Config
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "Watermelon@123")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

CYPHER_MODEL = os.getenv("CYPHER_MODEL", "gpt-4.1-mini")
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "gpt-4.1-mini")

READ_ONLY_CYPHER_PATTERN = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|CALL\s+dbms|CALL\s+apoc|LOAD\s+CSV)\b",
    re.IGNORECASE,
)


GRAPH_SCHEMA = """
You are an expert Neo4j Cypher query writer for an ESG (Environmental, Social,
Governance) knowledge graph containing sustainability data from corporate
annual reports.

NODE TYPES AND KEY PROPERTIES:

Company         {company_id, name, sector, country}
                Currently loaded: nestle_india (Nestle India Limited, FMCG)

Document        {doc_id, fiscal_year, report_type, has_brsr,
                 has_third_party_assurance, assurance_provider}

Section         {section_id, title}

Chunk           {chunk_id, page, text, char_count}
                Chunks are text extracts from the PDF, roughly 600 tokens each.

Observation     {obs_id, raw_name, raw_value, raw_unit_string,
                 normalised_value, normalised_unit_symbol,
                 normalisation_confidence, period_label, period_start,
                 period_end, period_type, fact_type, normalization_status,
                 page, chunk_id, canonical_id}
                normalization_status: normalized | partial | new_metric
                fact_type: measurement | target | baseline | ratio | boolean | count
                normalisation_confidence: exact | inferred | failed | needs_context

Metric          {canonical_id, display_name, category, unit_family,
                 metric_subject, metric_role, comparable}
                Labels: :Metric:Canonical or :Metric:Provisional
                Categories: water, energy, emissions, waste, packaging,
                            workforce, safety, governance, community

MetricCategory  {category_id, name, level}
                Hierarchy: Environmental > Water > Water Consumption etc.

Period          {fiscal_year, year_start, year_end, calendar}
                Available examples: FY2018 through FY2030, CY2022, FY2023_15M

Unit            {symbol, label, unit_family}
                Examples: L, kL, ML, kg, tonne, GJ, MWh, tCO2e, %, count

Evidence        {evidence_id, text}
                The exact sentence from the PDF that the fact came from.

ConfidenceRecord {normalization_status, normalisation_confidence,
                  final_confidence, tiebreaker_used}

Change          {from_period, to_period, absolute_change,
                 percentage_change, direction}

RELATIONSHIPS (use these exact relationship names and directions):
(Company)-[:FILED]->(Document)
(Section)-[:IN_DOCUMENT]->(Document)
(Chunk)-[:IN_SECTION]->(Section)
(Chunk)-[:NEXT]->(Chunk)
(Observation)-[:REPORTED_BY]->(Company)
(Observation)-[:OF_METRIC]->(Metric)
(Observation)-[:IN_PERIOD]->(Period)
(Observation)-[:EXTRACTED_FROM]->(Chunk)
(Observation)-[:SUPPORTED_BY]->(Evidence)
(Evidence)-[:FOUND_IN]->(Chunk)
(Observation)-[:HAS_CONFIDENCE]->(ConfidenceRecord)
(Observation)-[:MEASURED_IN]->(Unit)
(Metric)-[:BELONGS_TO]->(MetricCategory)
(MetricCategory)-[:SUBCATEGORY_OF]->(MetricCategory)
(Period)-[:NEXT_YEAR]->(Period)
(Unit)-[:CONVERTS_TO]->(Unit)

CRITICAL — CROSS-COMPANY QUERY PATTERN:

For ANY question comparing across companies or asking about
metrics that might be provisional (employees, complaints,
training, NOx, SOx, battery waste, specific waste types),
ALWAYS use this pattern:

MATCH (o:Observation)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE (
    EXISTS {
        MATCH (o)-[:OF_METRIC]->(m:Metric:Canonical)
        WHERE toLower(m.display_name) CONTAINS toLower('keyword')
    }
    OR EXISTS {
        MATCH (o)-[:OF_METRIC]->(m:Metric:Provisional)
        WHERE toLower(m.raw_name) CONTAINS toLower('keyword')
    }
    OR toLower(o.raw_name) CONTAINS toLower('keyword')
)
AND o.normalization_status IN ['normalized','partial','new_metric']
OPTIONAL MATCH (o)-[:OF_METRIC]->(m:Metric)
OPTIONAL MATCH (o)-[:IN_PERIOD]->(p2:Period)
RETURN c.company_id, c.name, o.raw_name,
       o.normalised_value, o.normalised_unit_symbol,
       o.normalization_status, p.fiscal_year
ORDER BY c.company_id, o.normalised_value DESC
LIMIT 30

RULES:
1. For headcount/employees: keyword='employee' OR 'headcount'
   Add these filters to exclude financial share counts:
     AND o.normalised_value > 500
     AND o.normalised_value < 500000
     AND o.normalised_unit_symbol = 'count'
     AND NOT toLower(o.raw_name) CONTAINS 'stock'
     AND NOT toLower(o.raw_name) CONTAINS 'share'
     AND NOT toLower(o.raw_name) CONTAINS 'option'
     AND NOT toLower(o.raw_name) CONTAINS 'ordinary shares'
     AND NOT toLower(o.raw_name) CONTAINS 'potential'

2. For complaints: keyword='complaint' OR 'grievance'
   Split filed vs pending by adding:
   AND toLower(o.raw_name) CONTAINS 'filed' (or 'pending')

3. For emissions cross-company: use canonical pattern first
   since scope_1_emissions, scope_2_emissions are canonical.
   Fall back to raw_name search if canonical returns nothing.

CRITICAL — ALWAYS include both normalized and partial:
   NEVER filter on normalization_status = 'normalized' alone.
   ALWAYS use: o.normalization_status IN ['normalized', 'partial']
   Many important facts (Scope 1/2 for Britannia, Marico,
   water, energy) are stored as 'partial' not 'normalized'.
   Filtering on 'normalized' alone will silently drop them.

WATER UNITS — prefer kL over L:
   When displaying water metrics, prefer observations where
   normalised_unit_symbol = 'kL'. If only 'L' values exist,
   convert: display value / 1000 as kL. Never show raw litres
   in a cross-company water comparison — always normalise to kL.
   In Cypher, filter with: o.normalised_unit_symbol = 'kL'
   If that returns nothing, fall back to 'L' and divide by 1000
   in the RETURN clause: o.normalised_value / 1000 AS value_kL

4. DEDUPLICATION — one value per company per year:
   BRSR tables contain current-year AND comparative prior-year
   values in the same page, so a single canonical metric may
   have multiple Observation nodes per company. When comparing
   across companies for a specific year, always deduplicate
   with this pattern after the WHERE clause:

   WITH c, o ORDER BY o.normalised_value DESC
   WITH c, collect(o)[0] as o
   RETURN c.company_id, o.normalised_value, o.normalised_unit_symbol

   The collect(o)[0] picks the highest value per company,
   which is correct for absolute metrics (scope emissions,
   energy, water) reported in the current year row.
   Always apply this when the question asks for one number
   per company (e.g. "compare scope 1 emissions across
   companies").

5. Always filter by fiscal year when comparing across companies:
   AND p.fiscal_year = 'FY2024'  (or the year asked about)
   AND o.normalization_status IN ['normalized', 'partial']

4. Always include new_metric in status filter for cross-company —
   many important facts are provisional across companies.

5. For water/energy/waste cross-company: use canonical pattern
   since these are well-covered by the registry.
   Only add raw_name search if canonical returns < 2 companies.

6. RENEWABLE ENERGY DATA — what's actually in the graph:

   Companies report renewable energy differently:
   - ITC: percentage share (raw_name CONTAINS 'share of renewable energy', unit='%')
   - Tata Consumer: percentage (raw_name = 'renewable energy share', value=97%, unit='%')
   - Nestle: absolute GJ (canonical_id = 'renewable_energy_consumption_absolute')
   - GCPL: not loaded yet

   For "renewable energy share/percentage" questions use:
   MATCH (o:Observation)-[:REPORTED_BY]->(c:Company),
         (o)-[:IN_PERIOD]->(p:Period)
   WHERE (
       toLower(o.raw_name) CONTAINS 'renewable'
       OR o.canonical_id = 'renewable_energy_consumption_absolute'
   )
   AND o.normalization_status IN ['normalized','partial','new_metric']
   AND NOT toLower(o.raw_name) CONTAINS 'non-renewable'
   AND NOT toLower(o.raw_name) CONTAINS 'non renewable'
   AND NOT toLower(o.raw_name) CONTAINS 'irec'
   AND NOT toLower(o.raw_name) CONTAINS 'ghg'
   AND NOT toLower(o.raw_name) CONTAINS 'demerger'
   AND NOT (o.normalised_value > 500 AND o.normalised_unit_symbol = 'GJ')
   AND NOT toLower(o.raw_name) CONTAINS 'grid electricity'
   OPTIONAL MATCH (o)-[:OF_METRIC]->(m:Metric)
   RETURN c.company_id, c.name, o.raw_name, o.normalised_value,
          o.normalised_unit_symbol, p.fiscal_year
   ORDER BY c.company_id
   LIMIT 20

   For ITC specifically: prefer raw_name = 'share of renewable energy'
   over any raw_name CONTAINS 'grid electricity' — the electricity-specific
   100% value is a sub-metric, not the total renewable share (which is ~50-52%).

   For "how much renewable energy" absolute questions use:
   canonical_id = 'renewable_energy_consumption_absolute'
   AND o.normalised_value < 10000000
   AND o.normalised_unit_symbol = 'GJ'
   (values above 1 billion are bad CY2021 TJ conversion remnants)

IMPORTANT FOR CROSS-COMPANY COMPARISONS:
When comparing a metric across companies, return ONE primary value
per company — not all rows. Use this pattern:

MATCH (o:Observation)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE [conditions]
WITH c, p, o
ORDER BY c.company_id, o.normalised_value DESC
WITH c, collect({value: o.normalised_value, unit: o.normalised_unit_symbol,
                 period: p.fiscal_year, raw_name: o.raw_name})[0] as best
RETURN c.company_id, c.name, best.raw_name, best.value,
       best.unit, best.period
ORDER BY best.value DESC

This ensures one row per company in cross-company comparisons.
Never return more than 5 rows per company in a comparison query.

EXAMPLE QUESTIONS AND KEYWORDS:
"compare employees"          -> keyword: 'employee', 'headcount'
"complaints across companies"-> keyword: 'complaint'
"training coverage"          -> keyword: 'training', 'skill'
"NOx emissions comparison"   -> keyword: 'nox', 'nitrogen'
"waste by type"              -> keyword: 'battery waste', 'plastic waste'
"water stress areas"         -> keyword: 'water stress', 'high stress'
"renewable energy share"     -> keyword: 'renewable'

CYPHER WRITING RULES:
1. Return exactly one read-only Cypher query and no prose.
2. Always use LIMIT 50 unless the user explicitly asks for all.
3. For company queries: company_id = 'nestle_india'.
4. For metric name matching: use toLower(m.display_name) CONTAINS toLower('keyword').
5. For period matching: match on p.fiscal_year = 'FY2024' etc.
6. IMPORTANT: The graph has three normalization statuses — 'normalized' (23 obs),
   'partial' (49 obs), and 'new_metric' (134 obs). Most BRSR facts are 'new_metric'.
   For general listing/search queries include ALL statuses (omit status filter, or
   use o.normalization_status IN ['normalized','partial','new_metric']).
   Only restrict to ['normalized','partial'] when the user explicitly asks for
   "verified" or "normalized" data, or when doing strict numeric comparisons.
7. For source text queries: follow (o)-[:SUPPORTED_BY]->(e:Evidence)-[:FOUND_IN]->(ch:Chunk).
8. Use OPTIONAL MATCH for relationships that might not exist on every node.
9. Return human-readable fields: display names, values with units, period labels.
10. If a question genuinely cannot be answered from this graph, return exactly: IMPOSSIBLE
11. Put WHERE filters for the primary MATCH immediately after that MATCH and
    before OPTIONAL MATCH clauses. Do not put a primary row filter after an
    OPTIONAL MATCH.
12. When combining OR metric-name filters with AND status filters, wrap the OR
    group in parentheses.
13. NEVER use (Document)-[:HAS_SECTION] or (Section)-[:HAS_CHUNK] — those do not
    exist. Use (Chunk)-[:IN_SECTION]->(Section) and (Section)-[:IN_DOCUMENT]->(Document).

COMMON QUERY HINTS FROM THE LOADED GRAPH:
- "waste facts" should match either toLower(m.display_name) CONTAINS 'waste'
  OR toLower(o.raw_name) CONTAINS 'waste'; include new_metric rows.
- "water intensity" should match Water Consumption Intensity and raw names
  containing 'water intensity' or 'water usage reduction per ton'.
- "employees" or "headcount" should match raw names such as 'Employees Total',
  'Employees - Male', and 'Employees - Female'; include new_metric rows.
- "targets" should first check o.fact_type = 'target', but also match raw names
  containing 'target', because target-like BRSR rows may be marked measurement.

EXAMPLE QUESTION -> CYPHER PAIRS:

Q: "What was Nestle's total water consumption in FY2024?"
A: MATCH (m:Metric)<-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}), (o)-[:IN_PERIOD]->(p:Period {fiscal_year:'FY2024'}) WHERE toLower(coalesce(m.display_name,'')) CONTAINS 'water consumption' OR toLower(o.raw_name) CONTAINS 'water consumption' RETURN coalesce(m.display_name, o.raw_name) AS metric, o.raw_name AS raw_name, o.normalised_value AS value, o.normalised_unit_symbol AS unit, p.fiscal_year AS fiscal_year, o.normalization_status AS status ORDER BY o.normalised_value DESC LIMIT 20

Q: "Show me Scope 1 emissions"
A: MATCH (m:Metric)<-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) WHERE toLower(coalesce(m.display_name,'')) CONTAINS 'scope 1' OR toLower(o.raw_name) CONTAINS 'scope 1' OPTIONAL MATCH (o)-[:IN_PERIOD]->(p:Period) RETURN coalesce(m.display_name, o.raw_name) AS metric, o.raw_name AS raw_name, o.normalised_value AS value, o.normalised_unit_symbol AS unit, p.fiscal_year AS fiscal_year, o.normalization_status AS status ORDER BY p.fiscal_year DESC LIMIT 20

Q: "Show me the source text for the Scope 1 emissions fact"
A: MATCH (m:Metric)<-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}), (o)-[:SUPPORTED_BY]->(e:Evidence)-[:FOUND_IN]->(ch:Chunk) WHERE toLower(coalesce(m.display_name,'')) CONTAINS 'scope 1' OR toLower(o.raw_name) CONTAINS 'scope 1' RETURN o.raw_name AS fact, o.normalised_value AS value, o.normalised_unit_symbol AS unit, e.text AS source_text, ch.page AS page_number LIMIT 10

Q: "What sustainability targets has Nestle set?"
A: MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) WHERE o.fact_type = 'target' OR toLower(o.raw_name) CONTAINS 'target' OPTIONAL MATCH (o)-[:OF_METRIC]->(m:Metric) OPTIONAL MATCH (o)-[:IN_PERIOD]->(p:Period) RETURN coalesce(m.display_name, o.raw_name) AS metric, o.raw_name AS raw_name, o.raw_value AS raw_value, o.raw_unit_string AS raw_unit, coalesce(p.fiscal_year, o.period_label) AS period ORDER BY metric LIMIT 30

Q: "Show me all water metrics"
A: MATCH (m:Metric)<-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) WHERE toLower(coalesce(m.display_name,'')) CONTAINS 'water' OR toLower(o.raw_name) CONTAINS 'water' OPTIONAL MATCH (o)-[:IN_PERIOD]->(p:Period) RETURN coalesce(m.display_name, o.raw_name) AS metric, o.raw_name AS raw_name, o.normalised_value AS value, o.normalised_unit_symbol AS unit, p.fiscal_year AS fiscal_year, o.normalization_status AS status ORDER BY metric, p.fiscal_year LIMIT 50

Q: "Show me all waste facts"
A: MATCH (m:Metric)<-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) WHERE toLower(coalesce(m.display_name,'')) CONTAINS 'waste' OR toLower(o.raw_name) CONTAINS 'waste' OPTIONAL MATCH (o)-[:IN_PERIOD]->(p:Period) RETURN coalesce(m.display_name, o.raw_name) AS metric, o.raw_name AS raw_name, o.normalised_value AS value, o.normalised_unit_symbol AS unit, p.fiscal_year AS fiscal_year, o.normalization_status AS status ORDER BY p.fiscal_year DESC, metric LIMIT 50

Q: "What is Nestle's water intensity?"
A: MATCH (m:Metric)<-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) WHERE toLower(coalesce(m.display_name,'')) CONTAINS 'water intensity' OR toLower(coalesce(m.display_name,'')) CONTAINS 'water consumption intensity' OR toLower(o.raw_name) CONTAINS 'water intensity' OPTIONAL MATCH (o)-[:IN_PERIOD]->(p:Period) RETURN coalesce(m.display_name, o.raw_name) AS metric, o.raw_name AS raw_name, o.normalised_value AS value, o.normalised_unit_symbol AS unit, p.fiscal_year AS fiscal_year, o.normalization_status AS status ORDER BY p.fiscal_year DESC LIMIT 20

Q: "How many employees does Nestle have?"
A: MATCH (m:Metric)<-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}) WHERE toLower(coalesce(m.display_name,'')) CONTAINS 'employee' OR toLower(coalesce(m.display_name,'')) CONTAINS 'headcount' OR toLower(o.raw_name) CONTAINS 'employee' OR toLower(o.raw_name) CONTAINS 'headcount' OPTIONAL MATCH (o)-[:IN_PERIOD]->(p:Period) RETURN o.raw_name AS fact, o.normalised_value AS value, o.normalised_unit_symbol AS unit, coalesce(p.fiscal_year, o.period_label) AS period, o.normalization_status AS status ORDER BY period DESC, fact LIMIT 30

Q: "Which facts came from page 209?"
A: MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}), (o)-[:EXTRACTED_FROM]->(ch:Chunk) WHERE ch.page = 209 OPTIONAL MATCH (o)-[:OF_METRIC]->(m:Metric) OPTIONAL MATCH (o)-[:IN_PERIOD]->(p:Period) OPTIONAL MATCH (o)-[:SUPPORTED_BY]->(e:Evidence) RETURN coalesce(m.display_name, o.raw_name) AS metric, o.raw_name AS fact, o.normalised_value AS value, o.normalised_unit_symbol AS unit, p.fiscal_year AS fiscal_year, ch.page AS page_number, e.text AS source_text, o.normalization_status AS status LIMIT 50

Q: "Show me year on year emissions comparison"
A: MATCH (m:Metric)<-[:OF_METRIC]-(o:Observation)-[:REPORTED_BY]->(c:Company {company_id:'nestle_india'}), (o)-[:IN_PERIOD]->(p:Period) WHERE (toLower(coalesce(m.display_name,'')) CONTAINS 'scope 1' OR toLower(coalesce(m.display_name,'')) CONTAINS 'scope 2' OR toLower(o.raw_name) CONTAINS 'scope 1' OR toLower(o.raw_name) CONTAINS 'scope 2') RETURN coalesce(m.display_name, o.raw_name) AS metric, o.raw_name AS raw_name, o.normalised_value AS value, o.normalised_unit_symbol AS unit, p.fiscal_year AS fiscal_year, o.normalization_status AS status ORDER BY metric, p.fiscal_year LIMIT 50
"""


ANSWER_PROMPT_TEMPLATE = """
You are an ESG data analyst presenting sustainability data clearly and concisely.

The user asked: "{question}"

The Neo4j graph query returned these results:
{results}

Instructions:
- Answer in 2-4 clear sentences.
- Always include actual numbers with units when they are present.
- Mention the time period, such as fiscal year, when relevant.
- If multiple values exist, summarise the key ones.
- If results are empty, say the data is not currently in the graph.
- If results are not empty, do not say the graph has no matching data.
- If results are partial matches (normalization_status=partial), note they are
  medium-confidence matches.
- Do not mention Neo4j, Cypher, or technical implementation details.
- Keep it factual and professional.
"""


SUGGESTED_QUESTIONS = [
    # Single company
    "What was Nestle's water consumption trend from 2021 to 2024?",
    "Show me Nestle's Scope 1 and Scope 2 emissions",
    "What sustainability targets has ITC set?",
    "Show me the source text for Nestle's water withdrawal fact",
    "What waste metrics does Tata Consumer report?",

    # Cross-company
    "Compare total water consumption across all companies",
    "Compare waste generated across all four companies",
    "Which company has the lowest water intensity?",
    "Compare Scope 1 emissions across all companies",
    "How many employees does each company have?",
    "Compare renewable energy share across companies",
    "Which company generates the most waste?",
]


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def validate_read_only_cypher(cypher: str) -> None:
    query = cypher.strip()
    if not query:
        raise ValueError("The model returned an empty query.")
    if query.upper() == "IMPOSSIBLE":
        return
    if ";" in query.rstrip(";"):
        raise ValueError("Multiple Cypher statements are not allowed.")
    if READ_ONLY_CYPHER_PATTERN.search(query):
        raise ValueError("Only read-only Cypher queries are allowed.")
    if not query.upper().startswith(("MATCH", "OPTIONAL MATCH", "WITH")):
        raise ValueError("Only read-style Cypher queries are allowed.")


def chat_completion_text(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, str]],
    max_completion_tokens: int,
    temperature: float = 0,
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_completion_tokens,
    )
    content = response.choices[0].message.content
    if not content:
        finish_reason = response.choices[0].finish_reason
        usage = getattr(response, "usage", None)
        raise ValueError(f"The model returned an empty response. finish_reason={finish_reason}, usage={usage}")
    return content.strip()


@st.cache_resource
def get_neo4j_driver():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        driver.verify_connectivity()
        return driver, None
    except Exception as exc:
        return None, str(exc)


def run_cypher(driver, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    validate_read_only_cypher(query)
    with driver.session(database="neo4j", default_access_mode=READ_ACCESS) as session:
        result = session.run(query.rstrip(";"), params or {})
        return [dict(record) for record in result]


def get_openai_client() -> OpenAI:
    if not OPENAI_KEY:
        raise ValueError("OPENAI_API_KEY is missing.")
    return OpenAI(
        api_key=OPENAI_KEY,
        http_client=httpx.Client(proxy=None, trust_env=False),
    )


@st.cache_data(ttl=300)
def get_graph_stats(_driver) -> dict[str, Any]:
    try:
        stats: dict[str, Any] = {}
        queries = {
            "total_observations": "MATCH (o:Observation) RETURN count(o) AS n",
            "normalized": "MATCH (o:Observation {normalization_status:'normalized'}) RETURN count(o) AS n",
            "partial": "MATCH (o:Observation {normalization_status:'partial'}) RETURN count(o) AS n",
            "new_metric": "MATCH (o:Observation {normalization_status:'new_metric'}) RETURN count(o) AS n",
            "companies": "MATCH (c:Company) RETURN count(c) AS n",
            "canonical_metrics": "MATCH (m:Metric:Canonical) RETURN count(m) AS n",
            "provisional_metrics": "MATCH (m:Metric:Provisional) RETURN count(m) AS n",
            "chunks": "MATCH (ch:Chunk) RETURN count(ch) AS n",
        }
        for key, query in queries.items():
            result = run_cypher(_driver, query)
            stats[key] = result[0]["n"] if result else 0

        companies = run_cypher(
            _driver,
            "MATCH (c:Company) RETURN c.name AS name, c.company_id AS id ORDER BY c.name LIMIT 50",
        )
        stats["company_list"] = [(row["name"], row["id"]) for row in companies]

        periods = run_cypher(
            _driver,
            "MATCH (o:Observation)-[:IN_PERIOD]->(p:Period) "
            "RETURN DISTINCT p.fiscal_year AS fy ORDER BY p.fiscal_year LIMIT 100",
        )
        stats["periods"] = [row["fy"] for row in periods if row.get("fy")]

        return stats
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Query template system
# ---------------------------------------------------------------------------

_CANONICAL_LOOKUP: dict[str, str] = {
    "scope 1": "scope_1_emissions",
    "scope1": "scope_1_emissions",
    "scope 2": "scope_2_emissions",
    "scope2": "scope_2_emissions",
    "water withdrawal": "water_consumption_absolute",
    "water intensity": "water_consumption_intensity",
    "energy intensity": "energy_intensity_physical_output",
    "total energy": "absolute_energy_consumption",
    "renewable energy": "renewable_energy_consumption_absolute",
    "waste": "waste_generated",
    "plastic waste": "plastic_waste_generated",
}

_COMPANY_LOOKUP: dict[str, str] = {
    "nestle": "nestle_india",
    "nestlé": "nestle_india",
    "nestle india": "nestle_india",
    "britannia": "britannia",
    "marico": "marico",
}

_CROSS_COMPANY_TEMPLATE = """MATCH (o:Observation)-[:OF_METRIC]->(m:Metric),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE m.canonical_id = '{canonical_id}'
  AND p.fiscal_year = '{year}'
  AND o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH c, p, o
ORDER BY o.normalised_value DESC
WITH c, collect(o)[0] as best
RETURN c.company_id AS company,
       best.normalised_value AS value,
       best.normalised_unit_symbol AS unit
ORDER BY company"""

_TIME_SERIES_TEMPLATE = """MATCH (o:Observation)-[:OF_METRIC]->(m:Metric),
      (o)-[:REPORTED_BY]->(c:Company {{company_id: '{company_id}'}}),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE m.canonical_id = '{canonical_id}'
  AND o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH p.fiscal_year AS year, o.normalised_unit_symbol AS unit,
     max(o.normalised_value) AS value
RETURN year, value, unit
ORDER BY year"""


def _extract_template_params(client: OpenAI, question: str, template_type: str) -> dict[str, str] | None:
    q_lower = question.lower()
    result: dict[str, str] = {}

    # Extract canonical_id
    canonical_id = None
    for term, cid in _CANONICAL_LOOKUP.items():
        if term in q_lower:
            canonical_id = cid
            break
    if canonical_id is None:
        return None
    result["canonical_id"] = canonical_id

    # Extract year (default FY2024)
    year_match = re.search(r"fy\s*(\d{4})", q_lower)
    result["year"] = f"FY{year_match.group(1)}" if year_match else "FY2024"

    if template_type == "time_series":
        company_id = None
        for term, cid in _COMPANY_LOOKUP.items():
            if term in q_lower:
                company_id = cid
                break
        if company_id is None:
            return None
        result["company_id"] = company_id

    return result


def match_query_template(client: OpenAI, question: str) -> tuple[str, str] | None:
    """Returns (cypher, template_name) or None if no template matched."""
    q_lower = question.lower()

    esg_terms = {"emission", "scope 1", "scope 2", "scope1", "scope2",
                 "energy", "water", "waste", "plastic"}
    is_cross_company = (
        "compare" in q_lower
        and "compan" in q_lower
        and any(t in q_lower for t in esg_terms)
    )
    is_time_series = any(t in q_lower for t in (
        "trend", "over time", "year over year", "fy2024 to fy2025",
        "fy2023 to fy2024", "historical",
    ))

    if is_cross_company:
        params = _extract_template_params(client, question, "cross_company")
        if params:
            return _CROSS_COMPANY_TEMPLATE.format(**params), f"Template: cross-company ({params['canonical_id']}, {params['year']})"

    if is_time_series:
        params = _extract_template_params(client, question, "time_series")
        if params:
            return _TIME_SERIES_TEMPLATE.format(**params), f"Template: time-series ({params['canonical_id']}, {params['company_id']})"

    return None


def generate_cypher(client: OpenAI, question: str) -> str:
    cypher = chat_completion_text(
        client,
        model=CYPHER_MODEL,
        messages=[
            {"role": "system", "content": GRAPH_SCHEMA},
            {"role": "user", "content": f"Convert this question to a Cypher query:\n\n{question}"},
        ],
        max_completion_tokens=2000,
        temperature=0,
    )
    cypher = strip_code_fence(cypher)
    validate_read_only_cypher(cypher)
    return cypher


def fix_cypher(client: OpenAI, question: str, bad_cypher: str, error: str) -> str:
    fix_prompt = f"""The following Cypher query failed with this error:

Error: {error}

Failed query:
{bad_cypher}

Original question: {question}

Please write a corrected read-only Cypher query. Return only the query, nothing else."""

    cypher = chat_completion_text(
        client,
        model=CYPHER_MODEL,
        messages=[
            {"role": "system", "content": GRAPH_SCHEMA},
            {"role": "user", "content": fix_prompt},
        ],
        max_completion_tokens=2000,
        temperature=0,
    )
    cypher = strip_code_fence(cypher)
    validate_read_only_cypher(cypher)
    return cypher


def generate_answer(client: OpenAI, question: str, results: list[dict[str, Any]]) -> str:
    results_str = json.dumps(results[:20], indent=2, default=str)
    return chat_completion_text(
        client,
        model=ANSWER_MODEL,
        messages=[
            {
                "role": "user",
                "content": ANSWER_PROMPT_TEMPLATE.format(question=question, results=results_str),
            }
        ],
        max_completion_tokens=1500,
        temperature=0.3,
    )


def run_query(client: OpenAI, driver, question: str) -> dict[str, Any]:
    output: dict[str, Any] = {
        "answer": "",
        "cypher": "",
        "results": [],
        "error": None,
        "retried": False,
        "template": "LLM generated",
    }

    try:
        template_result = match_query_template(client, question)
        if template_result:
            cypher, template_name = template_result
            output["template"] = template_name
        else:
            cypher = generate_cypher(client, question)
            output["template"] = "LLM generated"
        output["cypher"] = cypher
    except Exception as exc:
        import traceback
        output["error"] = f"Failed to generate Cypher: {type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        return output

    if cypher.strip().upper() == "IMPOSSIBLE":
        output["answer"] = "This question cannot be answered from the current graph data."
        return output

    try:
        output["results"] = run_cypher(driver, cypher)
    except Exception as exc:
        output["retried"] = True
        try:
            fixed_cypher = fix_cypher(client, question, cypher, str(exc))
            output["cypher"] = fixed_cypher
            output["results"] = run_cypher(driver, fixed_cypher)
        except Exception as retry_exc:
            output["error"] = f"Query failed after retry: {retry_exc}"
            output["answer"] = "I could not retrieve that data because the query failed. Try rephrasing your question."
            return output

    try:
        output["results"] = _convert_water_units(output["results"])
        output["answer"] = generate_answer(client, question, output["results"])
    except Exception as exc:
        output["error"] = f"Failed to format answer: {exc}"
        output["answer"] = f"Found {len(output['results'])} results, but could not format them."

    return output


def _convert_water_units(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert L → kL for any water results returned in litres."""
    converted = []
    for row in results:
        row = dict(row)
        unit_key = next((k for k in row if "unit" in k.lower()), None)
        val_key = next((k for k in row if "value" in k.lower() or k == "value"), None)
        if unit_key and val_key and row.get(unit_key) == "L" and row.get(val_key) is not None:
            try:
                row[val_key] = float(row[val_key]) / 1000
                row[unit_key] = "kL"
            except (TypeError, ValueError):
                pass
        converted.append(row)
    return converted


def dataframe_for_display(results: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(results)
    for column in df.columns:
        if pd.api.types.is_float_dtype(df[column]):
            df[column] = df[column].apply(
                lambda value: f"{value:,.0f}" if pd.notna(value) and abs(value) >= 1000 else value
            )
    return df


def render_sidebar() -> Any:
    with st.sidebar:
        st.title("ESG Graph")
        st.divider()

        driver, conn_error = get_neo4j_driver()
        if conn_error:
            st.error(f"Neo4j disconnected: {conn_error}")
            st.stop()
        st.success("Neo4j connected")

        if not OPENAI_KEY:
            st.error("OpenAI API key missing. Check your .env file.")
            st.stop()
        st.success("OpenAI ready")

        st.divider()

        stats = get_graph_stats(driver)
        if "error" in stats:
            st.warning(f"Stats unavailable: {stats['error']}")
        else:
            st.subheader("Graph Stats")
            col1, col2 = st.columns(2)
            col1.metric("Observations", stats.get("total_observations", 0))
            col2.metric("Metrics", stats.get("canonical_metrics", 0))
            col1.metric("Normalized", stats.get("normalized", 0))
            col2.metric("Partial", stats.get("partial", 0))
            col1.metric("Provisional", stats.get("provisional_metrics", 0))
            col2.metric("Chunks", stats.get("chunks", 0))

            st.divider()
            st.subheader("Loaded Data")
            for name, _company_id in stats.get("company_list", []):
                st.write(f"**{name}**")

            periods = stats.get("periods", [])
            if periods:
                st.write(f"**Periods:** {', '.join(periods)}")

            st.divider()
            st.subheader("Models")
            st.write(f"Query: `{CYPHER_MODEL}`")
            st.write(f"Answer: `{ANSWER_MODEL}`")

    return driver


def render_suggested_questions() -> None:
    with st.expander("Suggested questions", expanded=True):
        cols = st.columns(2)
        for index, suggested_question in enumerate(SUGGESTED_QUESTIONS):
            if cols[index % 2].button(
                suggested_question,
                key=f"suggested_{index}",
                use_container_width=True,
            ):
                st.session_state["question_input"] = suggested_question
                st.session_state["run_query"] = True


def render_output(output: dict[str, Any], elapsed: float) -> None:
    if output["answer"]:
        escaped_answer = html.escape(output["answer"]).replace("\n", "<br>")
        st.markdown(f'<div class="answer-box">{escaped_answer}</div>', unsafe_allow_html=True)

        meta_parts = [f"{elapsed:.1f}s"]
        if output.get("retried"):
            meta_parts.append("query auto-corrected")
        if output.get("error"):
            meta_parts.append(output["error"])
        st.caption(" | ".join(meta_parts))

    if output.get("error") and not output["answer"]:
        st.error(output["error"])

    if output["cypher"]:
        with st.expander("View Cypher query", expanded=False):
            st.code(output["cypher"], language="cypher")

    with st.expander("🔍 Debug info", expanded=False):
        st.markdown(f"**Query source:** `{output.get('template', 'LLM generated')}`")
        st.markdown(f"**Cypher executed:**")
        st.code(output["cypher"] or "(none)", language="cypher")
        results = output.get("results", [])
        st.markdown(f"**Raw results:** {len(results)} row(s)")
        if results:
            st.dataframe(pd.DataFrame(results[:5]), use_container_width=True)
        else:
            st.caption("No rows returned.")

    if output["results"]:
        with st.expander(f"View raw data ({len(output['results'])} rows)", expanded=False):
            st.dataframe(dataframe_for_display(output["results"]), use_container_width=True)

        evidence_keys = [
            key
            for key in output["results"][0].keys()
            if any(token in key.lower() for token in ("evidence", "source", "text", "page"))
        ]
        if evidence_keys:
            with st.expander("View source text from PDF", expanded=False):
                for index, row in enumerate(output["results"][:5]):
                    page = row.get("page_number") or row.get("page") or ""
                    for key in evidence_keys:
                        value = row.get(key)
                        if value and isinstance(value, str) and len(value) > 20:
                            label = f"Source {index + 1}" + (f" (page {page})" if page else "")
                            st.markdown(f"**{label}**")
                            st.markdown(f"> {value}")


def main() -> None:
    st.set_page_config(
        page_title="ESG Knowledge Graph",
        page_icon=":material/account_tree:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
        <style>
        /* ── Answer box ── */
        .answer-box {
            background-color: #f1f8f4;
            border-left: 4px solid #2f7d4f;
            padding: 1rem 1.4rem;
            border-radius: 0 8px 8px 0;
            margin: 1rem 0 0.5rem 0;
            font-size: 1.07rem;
            line-height: 1.7;
            color: #1a1a1a;
        }
        /* ── Main title ── */
        h1 { color: #1a3d2b !important; }
        /* ── Suggested question buttons ── */
        div[data-testid="stHorizontalBlock"] button {
            text-align: left !important;
            white-space: normal !important;
            height: auto !important;
        }
        /* ── Sidebar metrics ── */
        [data-testid="stMetricValue"] { font-size: 1.3rem !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    driver = render_sidebar()

    st.title("🌱 ESG Knowledge Graph")
    st.markdown(
        "Ask plain-English questions about sustainability data extracted from "
        "Nestlé India's annual report. Queries are converted to Cypher and run "
        "live against Neo4j."
    )

    render_suggested_questions()
    st.divider()

    with st.form("query_form", clear_on_submit=False):
        question = st.text_input(
            "Ask a question",
            placeholder="e.g. What was Nestle's water consumption in FY2024?",
            key="question_input",
            label_visibility="collapsed",
        )
        col_ask, col_clear = st.columns([1, 5])
        run_button = col_ask.form_submit_button("Ask", type="primary", use_container_width=True)
        clear_button = col_clear.form_submit_button("Clear")

    if clear_button:
        st.session_state["question_input"] = ""
        st.session_state.pop("last_output", None)
        st.session_state.pop("last_question", None)
        st.session_state.pop("elapsed", None)
        st.rerun()

    should_run = run_button or st.session_state.pop("run_query", False)
    if should_run and question.strip():
        client = get_openai_client()
        with st.spinner("Thinking..."):
            start = time.time()
            output = run_query(client, driver, question)
            elapsed = time.time() - start

        st.session_state["last_output"] = output
        st.session_state["last_question"] = question
        st.session_state["elapsed"] = elapsed

    if "last_output" in st.session_state:
        render_output(st.session_state["last_output"], st.session_state.get("elapsed", 0.0))


if __name__ == "__main__":
    main()
