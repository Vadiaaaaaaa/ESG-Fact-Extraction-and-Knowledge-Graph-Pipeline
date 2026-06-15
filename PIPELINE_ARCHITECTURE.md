# ESG Fact Extraction Pipeline — Architecture

**Project:** Consumer company ESG & operational KPI extraction from annual reports  
**Stack:** Python · OpenAI GPT-4.1-mini · Neo4j 5.x · Streamlit · Plotly  
**Companies in KG:** Nestlé India, Britannia Industries, Marico Limited

---

## Table of Contents

1. [Overview](#1-overview)
2. [Repository Layout](#2-repository-layout)
3. [Pipeline Stages](#3-pipeline-stages)
   - [Stage 0 — PDF Ingestion & Chunking](#stage-0--pdf-ingestion--chunking)
   - [Stage 1 — Pass 1: Fact Extraction (LLM)](#stage-1--pass-1-fact-extraction-llm)
   - [Stage 2 — Pass 2: Normalization & Registry Matching](#stage-2--pass-2-normalization--registry-matching)
   - [Stage 3 — Knowledge Graph Loading](#stage-3--knowledge-graph-loading)
4. [Data Models](#4-data-models)
5. [Registry System](#5-registry-system)
6. [Unit Normalisation](#6-unit-normalisation)
7. [Financial Classifier](#7-financial-classifier)
8. [Knowledge Graph Schema](#8-knowledge-graph-schema)
9. [Demo & Query Applications](#9-demo--query-applications)
10. [Evaluation & Quality Gates](#10-evaluation--quality-gates)
11. [Known Issues & Current Status](#11-known-issues--current-status)
12. [Cost & Token Profile](#12-cost--token-profile)

---

## 1. Overview

The pipeline converts raw PDF annual reports into a structured Neo4j knowledge graph of ESG and operational metrics. It does this in two LLM passes separated by a deterministic normalisation layer.

```
PDF Annual Report
 │
 ▼
[Stage 0] pipeline/fast_pdf_text_ingest.py
 │  Page selection → text extraction → chunking → prev/next linking
 │
 ▼  {prefix}_fast_chunks.json
[Stage 1] pipeline/extractor.py  (LLM: gpt-4.1-mini)
 │  Per-chunk fact extraction → validation → dedup → rescue pass
 │
 ▼  {prefix}_pass1.json
[Stage 2] pipeline/normalizer.py  (fuzzy match + optional LLM tiebreaker)
 │  Registry matching → unit normalisation → financial filtering → enrichment
 │
 ▼  {prefix}_pass2.json
[Stage 3] pipeline/run_pipeline.py → Neo4j
 │  MERGE nodes/relationships (idempotent)
 │  Cross-document deduplication
 │  MetricCategory hierarchy seeding
 │
 ▼  Neo4j KG (2,431 Observations across 4 documents)
 │
 ├──▶ graph/demo_app.py          port 8502  — 6 ESG questions, Explorer, provenance
 └──▶ graph/kg_query_app.py      port 8501  — NL→Cypher query interface
```

### Documents processed

| Document | Pages Selected | Chunks | KG Observations |
|---|---|---|---|
| Nestlé India FY2024 | 52 / 287 | 149 | 536 |
| Nestlé India FY2025 | 210 / 259 | 276 | 775 |
| Britannia FY2024 | 52 / 132 | 115 | 433 |
| Marico FY2024 | 98 / 259 | 201 | 687 |
| **Total** | | **741** | **2,431** |

---

## 2. Repository Layout

```
test/
│
├── pipeline/                        PIPELINE ENTRY POINTS
│   ├── run_pipeline.py              Unified orchestrator (CLI entry point, Stages 0–3)
│   ├── fast_pdf_text_ingest.py      Stage 0 — PDF → chunks
│   ├── section_finder.py            Page selection logic
│   ├── extractor.py                 Stage 1 — chunks → Pass 1 facts
│   ├── normalizer.py                Stage 2 — Pass 1 → Pass 2 facts
│   ├── models.py                    Chunk, ExtractedFact, NormalizedFact dataclasses
│   ├── unit_normaliser.py           Unit conversion + confidence
│   ├── normalizer_guardrails.py     Dimension/unit validators
│   └── pass1_*.py                   Prompt templates and schemas
│
├── registry/                        CANONICAL METRIC REGISTRY
│   ├── consumer_master_registry_v1.json   240 base canonical metric definitions
│   ├── registry_additions_approved.json   9+ BRSR-specific additions
│   ├── registry_aliases.json              289 raw_name → canonical_id aliases
│   ├── registry_semantic_overrides.json   Semantic typing corrections
│   └── metric_registry_seed.py            REGISTRY builder + alias index
│
├── audit/                           QUALITY CHECKS
│   ├── audit_selected_pages.py      Stage 2: Coverage audit
│   ├── new_metric_distance_audit.py Stage 5: Proximity audit
│   └── review_memory.json           Manual override decisions
│
├── graph/                           APPLICATIONS
│   ├── demo_app.py                  Portfolio demo (3 tabs, 6 questions, Explorer)
│   ├── kg_query_app.py              NL→Cypher query interface
│   ├── kg_loader_nestle.py          Legacy Nestlé FY2024 loader (superseded by run_pipeline.py)
│   ├── kg_loader_nestle_2021.py     Historical loaders
│   ├── kg_loader_nestle_2022.py
│   └── pipeline_ui.py               Pipeline run UI
│
├── eval/                            EVALUATION
│   ├── eval_pipeline.py             Precision/recall vs gold set
│   ├── eval_gold_set.py             69 gold fact annotations (Nestlé FY2024)
│   └── eval_review_app.py           Interactive label review app
│
├── tools/
│   └── registry_gap_analysis.py     Suggest new canonical metrics from new_metric clusters
│
├── gold_set.py                      Fuzzy scoring, match signals
├── pipeline_config.json             Runtime config (credentials, paths)
└── workspace_test_outputs/          All pipeline artifacts
```

---

## 3. Pipeline Stages

### Stage 0 — PDF Ingestion & Chunking

**File:** `pipeline/fast_pdf_text_ingest.py`  
**Input:** Annual report PDF  
**Output:** `{prefix}_fast_chunks.json`, `{prefix}_selected_pages.json`

#### What it does

1. **Page selection** — scans all PDF pages and scores each for ESG/BRSR content using keyword weights from `section_finder.py`. Pages below the threshold are excluded.

2. **TOC detection** — pages with ≥5 standalone 2–3 digit numbers are identified as table-of-contents pages and skipped when searching for the BRSR section heading. Prevents the range heuristic from selecting the wrong block of pages.

3. **Section detection** — groups selected pages into logical sections (Board's Report, BRSR, Cash Flow, Notes, etc.).

4. **Text extraction** — uses PyMuPDF (`fitz`) to extract raw text from selected pages.

5. **Chunking** — splits section text into ~600-token passages with 5-word overlap. Chunks store `prev_chunk_id` / `next_chunk_id` for provenance.

6. **Historical reprint detection** — prior-year comparative rows are flagged `is_historical_reprint=True` and excluded from extraction.

#### Chunk structure

```json
{
  "doc_id": "nestle_india",
  "section_id": "nestle_india_page_209",
  "chunk_id": "nestle_india_p209_1",
  "prev_chunk_id": "nestle_india_p203_2",
  "next_chunk_id": "nestle_india_p210_1",
  "page_start": 209,
  "page_end": 209,
  "chunk_type": "text",
  "content": "...",
  "char_count": 819,
  "token_estimate": 205,
  "is_historical_reprint": false,
  "temporal_context": {
    "filing_year": 2024,
    "fiscal_year_end": "March",
    "primary_period": "FY2024",
    "prior_period": "FY2023"
  }
}
```

#### Coverage audit

`audit/audit_selected_pages.py` re-scans the PDF after page selection and flags high-signal pages that were not selected. Acts as a recall check on the page selector.

---

### Stage 1 — Pass 1: Fact Extraction (LLM)

**File:** `pipeline/extractor.py`  
**Model:** `gpt-4.1-mini`  
**Input:** `{prefix}_fast_chunks.json`  
**Output:** `{prefix}_pass1.json`, `{prefix}_pass1_partial.jsonl`, `{prefix}_pass1_telemetry.json`

#### What it does

Each chunk is sent to GPT-4.1-mini with a high-recall extraction prompt. The model outputs a JSON array of all quantitative ESG facts found in the chunk.

- `max_tokens=16000` to handle dense BRSR tables without truncation (raised from 3,000)
- Truncation recovery: if JSON is cut off, scans backwards for last complete fact object
- Incremental JSONL (`{prefix}_pass1_partial.jsonl`): one line per completed chunk — enables crash recovery without re-extracting
- Rescue pass: facts with missing context are re-sent with neighboring chunks prepended

#### Extraction rules (key prompt additions)

- **Absolute value rule** — when a sentence has both an absolute figure and a multiplier, extract the absolute as primary
- **Sustainability targets** — extract future commitments as `fact_type=target` with `period_end` as the target year
- **Anti-noise** — exclude tenure years, award counts, page/section references

#### Pass 1 output per fact

```json
{
  "fact_id": "nestle_india_p209_1_fact_1",
  "chunk_id": "nestle_india_p209_1",
  "raw_name": "total volume of water withdrawal",
  "metric_core": "water_withdrawal",
  "raw_value": "3,232,635",
  "raw_unit": "kiloliters",
  "raw_period": "FY2024",
  "fact_class": "scalar_kpi",
  "source_sentence": "Total volume of water withdrawal [in kiloliters] 3,232,635",
  "period_confidence": "high",
  "decision": "keep"
}
```

**Typical costs** (gpt-4.1-mini at $0.40/$1.60 per M tokens):

| Document | Prompt tokens | Completion tokens | Cost |
|---|---|---|---|
| Nestlé FY2024 | ~400K | ~150K | ~$0.40 |
| Nestlé FY2025 | ~700K | ~280K | ~$0.73 |
| Britannia FY2024 | ~440K | ~165K | ~$0.44 |
| Marico FY2024 | ~520K | ~195K | ~$0.52 |

---

### Stage 2 — Pass 2: Normalization & Registry Matching

**File:** `pipeline/normalizer.py`  
**Model:** `gpt-4.1-mini` (tiebreaker calls only)  
**Input:** `{prefix}_pass1.json`  
**Output:** `{prefix}_pass2.json`

#### Processing flow (per fact)

```
Pass 1 fact
     │
     ▼
[Financial classifier]
     │  Is this a P&L/financial metric? → out_of_scope_financial (skip)
     │  Runs BEFORE alias lookup — blocks financial aliases bypassing filter
     │
     ▼
[Alias lookup]  registry_aliases.json (289 entries)
     │  Exact raw_name match → canonical_id, decision=normalized
     │
     ▼ (if no alias match)
[Fuzzy registry match]  gold_set.py
     │  Cosine similarity: raw_name vs 249 canonical display names
     │  score > SCORE_FLOOR + SCORE_MARGIN → normalized
     │  score in margin band → provisional (tiebreaker)
     │  score < SCORE_FLOOR → new_metric
     │
     ▼ (if provisional)
[Semantic tiebreaker]  LLM call
     │  Sends fact + top-2 candidates + definitions
     │  Returns accept/reject with reasoning
     │
     ▼
[Unit normalisation]  unit_normaliser.py
     │  raw_unit → canonical symbol + conversion factor
     │  Confidence: exact / inferred / needs_context / failed
     │
     ▼
Pass 2 enriched fact
```

#### Normalization decisions

| Decision | Meaning |
|---|---|
| `normalized` | High-confidence canonical match |
| `partial` | Plausible match, lower confidence |
| `new_metric` | No registry match — stored as Provisional node |
| `out_of_scope_financial` | P&L metric — excluded from ESG KG |
| `quarantine` | Implausible value (e.g. Scope 3 < 1% of Scope 1) |
| `drop` | Pass 1 already dropped, carried through |

#### Typical normalization breakdown (Nestlé FY2024)

| Status | Count | % |
|---|---|---|
| new_metric | 782 | 72% |
| normalized | 97 | 9% |
| partial | 73 | 7% |
| drop / quarantine | 147 | 14% |

---

### Stage 3 — Knowledge Graph Loading

**File:** `pipeline/run_pipeline.py` → `load_observations_to_graph()`  
**Database:** Neo4j 5.x, `neo4j://127.0.0.1:7687`

#### What it does

Creates all nodes and relationships using MERGE (idempotent). Runs three operations before loading facts:

**1. Cross-document deduplication**  
BRSR tables always include current + prior year comparative figures. Without dedup, loading FY2025 would create duplicate FY2024 Observations. The dedup logic queries Neo4j for matching (canonical_id, value ±1%, period) and keeps the Observation from the document whose year is closest to the reported period.

```python
facts = deduplicate_cross_document(session, facts, company_id, doc_id)
```

**2. MetricCategory hierarchy seeding**  
41 category nodes, 38 SUBCATEGORY_OF edges — seeded once per load:

```
Environmental → Water, Energy, Emissions, Waste, Packaging
Social        → Workforce, Community
Governance    → Compliance
```

**3. Observation load**  
```cypher
MERGE (o:Observation {obs_id: $id}) SET o += $props
MERGE (o)-[:REPORTED_BY]->(c:Company)
MERGE (o)-[:IN_PERIOD]->(p:Period)
MERGE (o)-[:OF_METRIC]->(m:Metric)
MERGE (o)-[:EXTRACTED_FROM]->(ch:Chunk)
MERGE (o)-[:SUPPORTED_BY]->(ev:Evidence)
MERGE (o)-[:HAS_CONFIDENCE]->(cr:ConfidenceRecord)
```

Only `normalized`, `partial`, and `new_metric` facts are loaded. `out_of_scope_financial`, `drop`, and `quarantine` are excluded.

#### The 4 production commands

```powershell
python pipeline/run_pipeline.py --pdf "...\Annual-Report-2023-24-nestle-india.pdf" `
  --company nestle_india --company-name "Nestlé India Limited" --year 2024 --calendar-type indian_fiscal

python pipeline/run_pipeline.py --pdf "...\Annual-Report-2024-25-nestle-india.pdf" `
  --company nestle_india --company-name "Nestlé India Limited" --year 2025 --calendar-type indian_fiscal

python pipeline/run_pipeline.py --pdf "...\BRITANNIA_Annual_Report_2023_24.pdf" `
  --company britannia --company-name "Britannia Industries Limited" --year 2024 --calendar-type indian_fiscal

python pipeline/run_pipeline.py --pdf "...\Marico_Annual_Report_FY24.pdf" `
  --company marico --company-name "Marico Limited" --year 2024 --calendar-type indian_fiscal
```

---

## 4. Data Models

### Chunk

Defined in `pipeline/models.py`.

| Field | Type | Description |
|---|---|---|
| `doc_id` | str | Company identifier |
| `section_id` | str | Section grouping |
| `chunk_id` | str | Unique, e.g. `nestle_india_p209_1` |
| `prev_chunk_id` | str\|None | Previous chunk in document order |
| `next_chunk_id` | str\|None | Next chunk in document order |
| `page_start` / `page_end` | int | PDF page range |
| `chunk_type` | str | `text` or `table` |
| `content` | str | Raw extracted text |
| `char_count` / `token_estimate` | int | Size metrics |
| `is_historical_reprint` | bool | Skip flag for reprinted prior-year data |
| `temporal_context` | TemporalContext | Filing year, fiscal year end, periods |

### Pass 1 Fact

Schema version: `edc_v1`. Key fields:

| Field | Description |
|---|---|
| `fact_id` | Unique, derived from chunk_id + sequence |
| `chunk_id`, `section_id`, `doc_id` | Provenance chain |
| `prev_chunk_id`, `next_chunk_id` | Chunk navigation |
| `raw_name` | Raw metric name as extracted |
| `raw_value` | Raw numeric value as string |
| `raw_unit` | Raw unit string |
| `raw_period` | Resolved period label (FY2024, CY2022, etc.) |
| `fact_class` | scalar_kpi / ratio / percentage / count / target |
| `source_sentence` | Exact PDF sentence |
| `decision` | keep / drop / rescue |

### Pass 2 Fact (Enriched)

All Pass 1 fields plus:

| Field | Description |
|---|---|
| `canonical_id` | Matched registry ID, null for new_metric |
| `canonical_name` | Human-readable registry name |
| `normalization_status` | normalized / partial / new_metric / out_of_scope_financial / drop / quarantine |
| `normalised_value` | Float, unit-converted value |
| `normalised_unit_symbol` | Canonical unit (kL, tCO2e, %, count, etc.) |
| `normalisation_confidence` | exact / inferred / needs_context / failed |
| `mapping_confidence` | high / medium / low / no_match |
| `tiebreaker_used` | bool — whether LLM tiebreaker was called |
| `final_confidence` | Float 0–1 |
| `source_doc_id` | Source document identifier |
| `page` | PDF page number |

---

## 5. Registry System

Three files are merged at runtime by `registry/metric_registry_seed.py`:

| File | Entries | Description |
|---|---|---|
| `consumer_master_registry_v1.json` | 240 | Core canonical metrics |
| `registry_additions_approved.json` | 9+ | BRSR-specific additions |
| `registry_semantic_overrides.json` | — | Typing corrections |
| `registry_aliases.json` | 289 | raw_name → canonical_id fast lookup |

Each canonical metric entry:

```json
{
  "canonical_id": "scope_1_emissions",
  "display_name": "Scope 1 GHG Emissions (Absolute)",
  "category": "environmental",
  "unit_family": "mass_equivalent",
  "metric_subject": "company",
  "metric_role": "total",
  "comparable": true,
  "aliases": ["scope 1 emissions", "direct ghg emissions", "scope-1"],
  "external_refs": [{"standard": "BRSR", "id": "Principle 6 Essential"}],
  "canonical_definition": "Total direct GHG emissions from company operations.",
  "review_status": "approved"
}
```

#### Registry matching algorithm (`gold_set.py`)

Score = weighted combination of:
- `alias_score` — BM25/cosine match between raw_name and registry aliases
- `metric_core_score` — snake_case metric_core similarity
- `definition_score` — semantic similarity against canonical_definition

```
score > SCORE_FLOOR + SCORE_MARGIN  → normalized
score > SCORE_FLOOR                 → provisional (tiebreaker)
score < SCORE_FLOOR                 → new_metric
```

`SCORE_FLOOR = 0.65`, `SCORE_MARGIN = 0.20`

#### Semantic alias gate

Before accepting a fuzzy match, `semantic_alias_gate` checks that the metric subject (water, emissions, energy, etc.) is compatible between the input fact and the candidate canonical. Blocks subject mismatches even when surface similarity is high.

#### BRSR-specific additions in registry_additions_approved.json

- `ltifr_workers` — Lost Time Injury Frequency Rate (Workers)
- `total_recordable_injuries_workers` / `_employees`
- `worker_union_membership`
- `energy_intensity_physical_output`
- `non_renewable_fuel_consumption` / `renewable_fuel_consumption`
- `water_discharge_third_party_treated`
- `high_consequence_injuries_employees`

---

## 6. Unit Normalisation

**File:** `pipeline/unit_normaliser.py`

Called inside `_enrich_normalized_fact` for every fact that passes the financial filter.

#### Confidence levels

| Level | Meaning |
|---|---|
| `exact` | Unit found directly in UNIT_MAP |
| `inferred` | Unit inferred from context |
| `needs_context` | Unit ambiguous — `normalised_value` set to null |
| `failed` | Unit not recognised — `normalised_value` set to null |

#### Key invariant

If `normalised_value is None` and confidence would be `exact` or `inferred`, confidence is downgraded to `needs_context`. A confident label with a null value is an error.

#### Critical unit fix: MTCO2E

Indian BRSR reports use "MT CO2e" to mean *metric tonnes*, not *megatonnes*. Earlier code applied a ×1,000,000 factor. Fixed to factor=1 for all `mt co2e`, `mtco2e`, `mt co2 equivalent` variants. 6 Marico observations were patched directly in Neo4j.

#### Unit conversions in the demo app

The Explorer tab in `graph/demo_app.py` applies `divide_by` per metric for display (e.g. water: ÷1000 to convert L → kL). This is display-only — the KG stores the raw normalised value.

---

## 7. Financial Classifier

**Function:** `_is_financial_fact()` in `pipeline/normalizer.py`

Runs as a **pre-filter in `run_pass2`** before facts reach the alias/fuzzy loop. This is a critical placement — previously alias lookup ran first, letting `sales → total_revenue` and `operating cash flow → operating_cash_flow` through as `normalized`.

#### Detection layers (in order)

1. `graph_fact_type == "financial_metric"` from Pass 1 LLM output
2. `metric` field matches `_FINANCIAL_METRIC_NAMES` set
3. `metric` field matches `_FINANCIAL_KEYWORD_RE` regex
4. `metric` field matches `_GROWTH_RATE_RE` (YoY, CAGR, year-on-year)
5. Registry match's `raw_name`/`metric_core` matches `_FINANCIAL_KEYWORD_RE`

#### Key patterns blocked

EBITDA, EBIT, revenue, turnover, profit (all variants), EPS, earnings per share, cash equivalents, operating/investing/financing cash flow, CAPEX, ROCE, margins (operating/net/gross), CAGR, retained earnings, shareholders fund, tax expense, working capital ratios.

---

## 8. Knowledge Graph Schema

### Node types and counts (current, all 4 documents)

| Label | Count | Key Properties |
|---|---|---|
| Observation | 2,431 | obs_id, raw_name, normalised_value, normalised_unit_symbol, normalization_status, canonical_id, source_doc_id, page |
| Metric:Canonical | 249 | canonical_id, display_name, category, unit_family, metric_subject, metric_role |
| Metric:Provisional | 1,456 | canonical_id (provisional), raw_name, owner_company |
| Chunk | 741 | chunk_id, page, text, char_count |
| Section | 470 | section_id, title |
| Evidence | 2,431 | evidence_id, text (exact PDF sentence) |
| ConfidenceRecord | 2,431 | normalization_status, normalisation_confidence, final_confidence |
| Company | 3 | company_id, name, sector, country |
| Document | 4 | doc_id, fiscal_year, report_type |
| Period | 3 | fiscal_year (CY2023, FY2024, FY2025) |
| MetricCategory | 41 | category_id, name, level (0=top, 1=mid, 2=leaf) |

### Relationships

| Relationship | Direction | Count | Meaning |
|---|---|---|---|
| REPORTED_BY | Observation → Company | 2,431 | Which company |
| IN_PERIOD | Observation → Period | 2,431 | Which fiscal year |
| OF_METRIC | Observation → Metric | 2,401 | Canonical or Provisional |
| EXTRACTED_FROM | Observation → Chunk | 2,431 | Source chunk |
| SUPPORTED_BY | Observation → Evidence | 2,431 | Exact source sentence |
| HAS_CONFIDENCE | Observation → ConfidenceRecord | 2,431 | Normalization metadata |
| IN_SECTION | Chunk → Section | 741 | Document structure |
| IN_DOCUMENT | Section → Document | 470 | Document structure |
| FILED | Company → Document | 4 | Company–document link |
| BELONGS_TO | Metric → MetricCategory | 1,705 | Category taxonomy |
| SUBCATEGORY_OF | MetricCategory → MetricCategory | 38 | Category hierarchy |
| NEXT_YEAR | Period → Period | 2 | CY2023→FY2024→FY2025 |

### Observation normalization_status breakdown

| Status | Count | KG linked to canonical? |
|---|---|---|
| new_metric | 1,872 | No (Provisional node) |
| partial | 310 | Yes |
| normalized | 249 | Yes |

### Important property notes

- `c.name` — use this for company display names (`c.display_name` is NULL on all nodes)
- `ev.text` — use this for evidence text (`ev.evidence_text` property does not exist)
- Periods: `CY2023` (Nestlé 12-month), `FY2024` (Nestlé 15-month Jan 2023–Mar 2024), `FY2025` (Nestlé 12-month)

### Standard cross-company query pattern

```cypher
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric {canonical_id: 'scope_1_emissions'}),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH c, max(o.normalised_value) AS value   -- dedup comparative/sub-segment rows
RETURN c.name AS company, value
ORDER BY value DESC
```

### Category hierarchy (3 levels)

```
Environmental → Water → Water Consumption/Withdrawal/Discharge/Recharge
             → Energy → Renewable/Non-Renewable/Intensity
             → Emissions → Scope 1/2/3/GHG Intensity
             → Waste → Generation/Recovery/Disposal/Plastic
             → Packaging → Plastic/Recyclable/EPR
Social        → Workforce → Headcount/Safety/Training/Diversity
             → Community → CSR/Complaints
Governance    → Compliance → BRSR/EPR
```

---

## 9. Demo & Query Applications

### graph/demo_app.py — Portfolio demo (port 8502)

Three-tab Streamlit app for non-technical audiences.

**Tab 1 — Questions**: 6 pre-answered ESG questions with live Neo4j queries, dynamic worded summaries, and source text expanders (PDF sentence + page number).

| # | Question | Category | Chart |
|---|---|---|---|
| Q1 | Permanent employee headcount across companies | Social | Horizontal bar |
| Q2 | Scope 1 emissions comparison FY2024 | Environmental | Horizontal bar |
| Q3 | Fossil fuel % of Britannia's energy | Environmental | Stat card |
| Q4 | Female wage share across companies | Social | % bar |
| Q5 | Nestlé Scope 1 emissions trend CY2023–FY2025 | Environmental | Line chart |
| Q6 | Confidence provenance for Nestlé water withdrawal | Provenance | Confidence card |

**Tab 2 — Explorer**: 13 verified metrics, dynamic year/company filters, horizontal bar with unit labels. Falls back to stat card for single-company results.

**Tab 3 — Ask a Question**: Disabled NL interface placeholder with 4 example cards and capability grid.

Key implementation: `max(o.normalised_value)` dedup pattern, `ev.text` for evidence, `c.name` for company names, `clean_evidence()` for ≤200-char PDF snippets.

### graph/kg_query_app.py — NL query interface (port 8501)

Template-based Cypher generation for common query patterns (cross-company comparison, time series). Falls back to LLM generation for unrecognised patterns.

---

## 10. Evaluation & Quality Gates

### eval/eval_pipeline.py

Measures pipeline quality against 69 hand-annotated Nestlé FY2024 gold facts. Checks value (±1% tolerance), unit (with aliases), period, and canonical_id.

**Current scores:**

| Metric | Score |
|---|---|
| Graph coverage (fact found in KG) | **97.1%** (67/69) |
| Value correct | 95.7% (66/69) |
| Unit correct | 85.5% (59/69) |
| Period correct | 97.1% (67/69) |
| **Fully correct** (all four dimensions) | **78.3%** (54/69) |

2 facts not in graph: g006, g014 (not present in ingested chunks).  
13 found but partial: canonical mismatches (g026, g033, g052), unit symbol issues (g003, g007, g010, g015, g028, g035, g044, g045), value rounding (g004).

```powershell
python eval/eval_pipeline.py
```

### Unit normalisation verification

`verify_unit_normalisation.py` checks: no fact has `normalisation_confidence IN (exact, inferred)` with `normalised_value = null`.

Current status: **all 4 documents PASS** (0 errors).

### tools/registry_gap_analysis.py

Queries Neo4j for all `new_metric` Observations, clusters by cosine similarity (threshold 0.85), and scores each cluster against the existing registry. Outputs:
- `registry_gap_report.csv` — cluster representative, companies, frequency, suggested canonical, action
- `registry_gap_aliases.json` — ready-to-merge alias suggestions (score > 0.75)

---

## 11. Known Issues & Current Status

### Fixed

- **`c.display_name` NULL** — all Company nodes have NULL `display_name`. All queries use `c.name`.
- **`ev.evidence_text` missing** — property is `ev.text`. All queries updated.
- **MTCO2E unit** — Indian BRSR "MT CO2e" = metric tonnes, not megatonnes. Factor corrected to 1.0. 6 Marico observations patched in Neo4j.
- **Financial classifier alias bypass** — `_is_financial_fact()` now runs as a pre-filter before alias lookup.
- **Cross-document dedup** — `deduplicate_cross_document()` prevents FY2025 report's comparative FY2024 rows from creating duplicate Observations.
- **CypherSyntaxError in q4 source expander** — `WITH` clause dropped `c` from scope; fixed to `WITH o, ev, ch, c ORDER BY ...`.
- **TOC page detection** — BRSR heading in a TOC page triggered wrong page range. Fixed by detecting pages with ≥5 standalone 2–3 digit numbers.

### Outstanding

- **g006, g014** — 2 gold facts not found in graph (not present in ingested chunks; would require expanding page selection or manual chunk addition).
- **Unit symbol mismatches (13 facts)** — mostly `count` vs `""` and `%` handling edge cases in the eval matcher. Low impact on actual KG values.
- **canonical_id gaps** — `water_withdrawal` vs `water_consumption_absolute` disambiguation (g033); `employee_headcount` coverage for non-BRSR headcount rows (g026).
- **gpt-4.1-mini API timeouts** — can occur on dense 50K+ character table chunks. Workaround: increase `API_TIMEOUT_SECONDS` from 300 to 600 in `extractor.py`.

---

## 12. Cost & Token Profile

### Actual costs (all 4 documents, gpt-4.1-mini at $0.40/$1.60 per M tokens)

| Document | Pass 1 cost | Pass 2 tiebreaker | Total |
|---|---|---|---|
| Nestlé FY2024 (149 chunks) | ~$0.40 | ~$0.02 | **~$0.42** |
| Nestlé FY2025 (276 chunks) | ~$0.73 | ~$0.03 | **~$0.76** |
| Britannia FY2024 (115 chunks) | ~$0.44 | ~$0.02 | **~$0.46** |
| Marico FY2024 (201 chunks) | ~$0.52 | ~$0.02 | **~$0.54** |
| **Total (4 documents)** | | | **~$2.18** |

### API calls

- Pass 1: ~1 call per chunk
- Pass 2: tiebreaker only (~5–10% of facts)
- **~741 Pass 1 calls total** across all 4 documents

### Scale projections

| Scope | Documents | Est. cost |
|---|---|---|
| Current (4 docs) | 4 | ~$2.18 |
| +2 companies FY2024 | 6 | ~$3.40 |
| 10 companies × 3 years | 30 | ~$16–18 |
