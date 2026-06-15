# ESG Knowledge Graph: Complete Project Documentation

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Pipeline Stages](#pipeline-stages)
4. [Knowledge Graph Schema](#knowledge-graph-schema)
5. [Registry System](#registry-system)
6. [Documents Processed](#documents-processed)
7. [Key Design Decisions](#key-design-decisions)
8. [How to Run](#how-to-run)
9. [Output Files](#output-files)
10. [Tools and Utilities](#tools-and-utilities)
11. [Demo Application](#demo-application)
12. [Configuration](#configuration)

---

## Project Overview

An end-to-end pipeline that extracts Environmental, Social, and Governance (ESG) metrics from Indian consumer company annual reports and loads them into a Neo4j knowledge graph for cross-company, cross-year analysis and querying.

**Core capability**: Takes PDF annual reports, runs a two-pass LLM extraction pipeline (OpenAI GPT-4.1-mini), normalizes raw metrics against a canonical registry, and loads structured observations into Neo4j — enabling queries like:
- "Compare Scope 1 emissions across all companies FY2024"
- "Show water intensity trend for Nestlé over time"
- "What LTIFR did Britannia report in FY2024?"

**Target domain**: Indian FMCG companies (Nestlé, Britannia, Marico, Tata Consumer, GCPL, ITC) filing BRSR (Business Responsibility and Sustainability Report) disclosures.

---

## Architecture

```
PDF Annual Report
        │
        ▼
Stage 1: Page Selection & Chunking
        │  section_finder.py → fast_pdf_text_ingest.py
        │  Selects ESG-relevant pages, chunks into ~600-token passages
        │
        ▼  {prefix}_fast_chunks.json
Stage 2: Coverage Audit
        │  audit_selected_pages.py
        │  Flags high-signal pages missed by selector
        │
        ▼  {prefix}_section_coverage_audit.csv
Stage 3: Pass 1 Extraction  (LLM)
        │  extractor.py
        │  GPT-4.1-mini extracts raw facts from each chunk
        │  Incremental JSONL written after each chunk (crash recovery)
        │
        ▼  {prefix}_pass1.json
Stage 4: Pass 2 Normalization
        │  normalizer.py
        │  Maps raw metric names → canonical registry IDs
        │  Unit normalization, semantic gating, tiebreaker LLM
        │
        ▼  {prefix}_pass2.json
Stage 5: Distance Audit
        │  new_metric_distance_audit.py
        │  Identifies new_metric facts close to existing canonicals
        │
        ▼  {prefix}_new_metric_distance_audit.csv
Stage 6: KG Load
        │  run_pipeline.py → Neo4j
        │  MERGE nodes/relationships (idempotent)
        │  Cross-document deduplication
        │  MetricCategory hierarchy seeding
        │
        ▼
      Neo4j Knowledge Graph
        │
        ├──▶ Demo App (graph/demo_app.py)         port 8502
        │       6 pre-answered ESG questions, Graph Explorer,
        │       brand-styled Plotly charts, provenance traces
        │
        └──▶ Query App (graph/kg_query_app.py)    port 8501
                NL → Cypher (template + LLM) → graph results
```

### Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| PDF processing | PyMuPDF (fitz) |
| LLM inference | OpenAI API (gpt-4.1-mini) |
| Database | Neo4j 5.x |
| Frontend | Streamlit |
| Utilities | pandas, httpx, python-dotenv, python-docx |

### Directory Structure

```
test/
├── pipeline/
│   ├── run_pipeline.py          # Unified orchestrator (CLI entry point)
│   ├── fast_pdf_text_ingest.py  # Stage 1: PDF → chunks
│   ├── section_finder.py        # Page selection logic
│   ├── extractor.py             # Stage 3: LLM extraction
│   ├── normalizer.py            # Stage 4: Registry matching
│   ├── models.py                # Chunk, ExtractedFact, NormalizedFact dataclasses
│   ├── unit_normaliser.py       # Unit conversion + confidence
│   ├── normalizer_guardrails.py # Dimension/unit validators
│   └── pass1_*.py               # Prompt templates and schemas
│
├── registry/
│   ├── consumer_master_registry_v1.json  # Base canonicals
│   ├── registry_additions_approved.json  # Approved extensions
│   ├── registry_aliases.json             # raw_name → canonical_id mappings
│   ├── registry_semantic_overrides.json  # Manual tiebreaker overrides
│   └── metric_registry_seed.py           # REGISTRY builder + alias index
│
├── audit/
│   ├── audit_selected_pages.py           # Stage 2: Coverage audit
│   ├── new_metric_distance_audit.py      # Stage 5: Proximity audit
│   └── review_memory.json               # Manual override decisions
│
├── graph/
│   ├── demo_app.py              # Portfolio demo (3 tabs, 6 questions, Explorer)
│   ├── kg_query_app.py          # NL→Cypher query interface
│   ├── kg_loader_nestle.py      # Nestlé FY2024 graph loader
│   ├── kg_loader_nestle_2021.py # Nestlé historical loaders
│   ├── kg_loader_nestle_2022.py
│   └── pipeline_ui.py           # Pipeline run UI
│
├── eval/
│   ├── eval_pipeline.py         # Precision/recall vs gold set
│   ├── eval_gold_set.py         # 69 gold fact annotations (Nestlé FY2024)
│   └── eval_review_app.py       # Interactive label review app
│
├── tools/
│   └── registry_gap_analysis.py # Suggest new canonical metrics
│
├── gold_set.py                  # Fuzzy scoring, match signals
├── pipeline_config.json         # Runtime config (credentials, paths)
└── workspace_test_outputs/      # All pipeline outputs
```

---

## Pipeline Stages

### Stage 1: Page Selection & Chunking

**Files**: `section_finder.py`, `fast_pdf_text_ingest.py`  
**Output**: `{prefix}_fast_chunks.json`, `{prefix}_selected_pages.json`

The section finder selects only ESG-relevant pages from the annual report (typically 50–210 pages from a 250–400 page PDF):

1. **TOC detection**: Pages with ≥5 standalone 2–3 digit numbers are identified as table-of-contents pages and skipped when looking for BRSR section headings (prevents false triggers on TOC entries).

2. **BRSR range heuristic**: Finds the BRSR section heading and selects a window of pages around it.

3. **Keyword scoring**: Scores all pages against ESG keywords (energy, water, emissions, waste, BRSR, etc.) and selects pages above a threshold.

4. **Coverage audit augmentation**: Adds isolated pages with high-signal ESG patterns not captured by the range heuristic.

After selection, text is chunked into ~600-token passages with metadata: `chunk_id`, `page`, `section_title`, `prev_chunk_id`, `next_chunk_id`.

**Typical results**:
- Nestlé FY2024: 52/287 pages selected, 149 chunks
- Nestlé FY2025: 210/259 pages, 276 chunks
- Britannia FY2024: 52/132 pages, 115 chunks
- Marico FY2024: 98/259 pages, 201 chunks

---

### Stage 3: Pass 1 Extraction (LLM)

**File**: `extractor.py`  
**Output**: `{prefix}_pass1.json`, `{prefix}_pass1_telemetry.json`

Each chunk is sent to GPT-4.1-mini with a high-recall extraction prompt. The model outputs a JSON array of facts:

```json
{
  "facts": [
    {
      "raw_name": "Total energy consumed",
      "metric_core": "energy_consumption",
      "fact_class": "scalar_kpi",
      "raw_value": "2279136",
      "raw_unit": "GJ",
      "raw_period": "FY2024",
      "source_sentence": "Total energy consumed in FY2024 was 2,279,136 GJ.",
      "period_confidence": "high"
    }
  ]
}
```

**Key features**:
- `max_tokens=16000` to handle dense BRSR tables without truncation
- Truncation recovery: if JSON is cut off, scans backwards for last complete fact object
- Two-stage mode: Pass 1A (recall) + Pass 1B (keep/drop decision)
- Incremental JSONL (`{prefix}_pass1_partial.jsonl`): one line per chunk, written as each API call completes — enables crash recovery without re-extracting completed chunks
- Post-processing: neighbor rescue pass, anchor consolidation, deduplication
- Cost tracking: writes `{prefix}_cost_summary.json` with token counts and USD cost

**Typical costs** (gpt-4.1-mini at $0.40/$1.60 per M tokens):
- Britannia FY2024: $0.70 (702K prompt + 262K completion)
- Marico FY2024: $0.83 (836K prompt + 309K completion)

---

### Stage 4: Pass 2 Normalization

**File**: `normalizer.py`  
**Output**: `{prefix}_pass2.json`

Maps each raw metric name to a canonical registry entry via a cascade:

```
1. ALIAS LOOKUP (O(1))
   Check registry_aliases.json — 289 hand-curated mappings
   e.g. "total fuel consumption from non-renewable sources (e)" → non_renewable_energy_consumption_absolute

2. FUZZY MATCH (token-based cosine)
   Score raw name vs all 249 canonical display names
   Uses compute_match_score() from gold_set.py

3. SEMANTIC GATE
   Validate subject/role/unit-family compatibility
   e.g. reject water canonical for an emissions metric

4. TIEBREAKER
   If top-2 scores within margin: check semantic_registry overrides
   Optional: LLM semantic disambiguation

5. OUTCOME
   normalized  — high-confidence canonical match
   partial     — plausible match, lower confidence
   new_metric  — no suitable canonical (stored as Provisional)
   quarantine  — implausible value (e.g., Scope 3 < 1% of Scope 1)
   drop        — out of scope
```

**Unit normalization** (`unit_normaliser.py`):
- Converts raw units to canonical symbols
- Key fix: `MTCO2E` / `MT CO2e` → `tCO2e` with factor 1.0 (Indian BRSR uses MT = metric tonne, not megatonne)
- Confidence: `exact`, `inferred`, `null`

**Typical normalization breakdown** (Nestlé FY2024 after registry additions):
- normalized: 97 (9%)
- partial: 73 (7%)
- new_metric: 782 (72%)
- drop/quarantine: 147 (14%)

---

### Stage 6: KG Load

**File**: `run_pipeline.py` → `load_observations_to_graph()`

Creates all nodes and relationships in Neo4j using MERGE (idempotent):

```python
# Cross-document deduplication (added to prevent duplicate comparative rows)
# For each fact: check if same canonical + value + period already exists in graph
# If yes: keep the observation whose source_doc_id year matches the period year
# (prefer FY2024 doc for FY2024 facts over FY2025 doc's comparative table)
facts = deduplicate_cross_document(session, facts, company_id, doc_id)

# MetricCategory hierarchy seeding (41 nodes, 38 SUBCATEGORY_OF edges)
# Environmental → Water, Energy, Emissions, Waste, Packaging
# Social → Workforce, Community
# Governance → Compliance
seed_metric_categories(session)

# Load observations
for fact in facts:
    MERGE (o:Observation {obs_id: $id}) SET o += $props
    MERGE (o)-[:REPORTED_BY]->(c:Company)
    MERGE (o)-[:IN_PERIOD]->(p:Period)
    MERGE (o)-[:OF_METRIC]->(m:Metric)
    MERGE (o)-[:EXTRACTED_FROM]->(ch:Chunk)
    MERGE (o)-[:SUPPORTED_BY]->(ev:Evidence)
    MERGE (o)-[:HAS_CONFIDENCE]->(cr:ConfidenceRecord)
```

**Deduplication logic** (`deduplicate_cross_document`):
- Runs a Cypher query before each fact load to check for duplicates within 1% value tolerance
- Compares `|doc_year - period_year|` for incoming vs existing
- Keeps the observation from the document closest in year to the period being reported
- Result: FY2025 report's comparative FY2024 rows are dropped when FY2024 report is already loaded

---

## Knowledge Graph Schema

### Node Types

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
| Period | 2 | fiscal_year, year_start, year_end, calendar |
| MetricCategory | 41 | category_id, name, level (0=top, 1=mid, 2=leaf) |

### Relationships

| Relationship | Direction | Count | Meaning |
|---|---|---|---|
| REPORTED_BY | Observation → Company | 2,431 | Which company reported this |
| IN_PERIOD | Observation → Period | 2,431 | Which fiscal year |
| OF_METRIC | Observation → Metric | 2,401 | Which canonical/provisional metric |
| EXTRACTED_FROM | Observation → Chunk | 2,431 | Source text chunk |
| SUPPORTED_BY | Observation → Evidence | 2,431 | Exact source sentence |
| HAS_CONFIDENCE | Observation → ConfidenceRecord | 2,431 | Normalization metadata |
| IN_SECTION | Chunk → Section | 741 | Document structure |
| IN_DOCUMENT | Section → Document | 470 | Document structure |
| FILED | Company → Document | 4 | Company–document link |
| BELONGS_TO | Metric → MetricCategory | 1,705 | Category taxonomy |
| SUBCATEGORY_OF | MetricCategory → MetricCategory | 38 | Category hierarchy |
| NEXT_YEAR | Period → Period | 1 | FY2024 → FY2025 |

### Observation normalization_status breakdown

| Status | Count | KG linked to canonical? |
|---|---|---|
| new_metric | 1,872 | No (Provisional node) |
| partial | 310 | Yes |
| normalized | 249 | Yes |

### Standard cross-company query pattern

```cypher
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric {canonical_id: 'scope_1_emissions'}),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH c, o ORDER BY o.normalised_value DESC
WITH c, collect(o)[0] AS best  -- one per company, highest value
RETURN c.company_id AS company,
       best.normalised_value AS value,
       best.normalised_unit_symbol AS unit
ORDER BY company
```

---

## Registry System

### Files

**`consumer_master_registry_v1.json`** — 240 base canonical metric definitions across:
- financial_backbone (revenue, profit, margins)
- environmental (emissions, energy, water, waste)
- social (headcount, safety, training)
- operational_seed (distribution, market share)

**`registry_additions_approved.json`** — 9+ BRSR-specific additions including:
- `ltifr_workers` — Lost Time Injury Frequency Rate (Workers)
- `total_recordable_injuries_workers` / `_employees`
- `worker_union_membership`
- `energy_intensity_physical_output`
- `non_renewable_fuel_consumption` / `renewable_fuel_consumption`
- `water_discharge_third_party_treated`
- `employee_training_health_safety_male`
- `high_consequence_injuries_employees`

**`registry_aliases.json`** — 289 flat aliases:
```json
{
  "total fuel consumption from non-renewable sources (e)": "non_renewable_energy_consumption_absolute",
  "lost time injury frequency rate (ltifr) workers": "ltifr_workers",
  "total employees": "employee_headcount"
}
```

**`metric_registry_seed.py`** — Builds the merged `REGISTRY` list at runtime by reading all three files.

### Canonical entry format

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

---

## Documents Processed

| Document | Pages Selected | Chunks | Pass 1 Facts | Normalized+Partial | KG Observations |
|---|---|---|---|---|---|
| Nestlé India FY2024 | 52 / 287 | 149 | 950 keep | 170 | 536 |
| Nestlé India FY2025 | 210 / 259 | 276 | 1,517 keep | 147 | 775 |
| Britannia FY2024 | 52 / 132 | 115 | 1,149 keep | 105 | 433 |
| Marico FY2024 | 98 / 259 | 201 | 1,517 keep | 168 | 687 |
| **Total** | | **741** | | | **2,431** |

**Eval scores** (Nestlé FY2024 gold set, 69 facts):

| Metric | Score |
|---|---|
| Graph coverage (fact found in KG) | **97.1%** (67/69) |
| Value correct (±1% tolerance) | 95.7% (66/69) |
| Unit correct | 85.5% (59/69) |
| Period correct | 97.1% (67/69) |
| Fully correct (value + unit + period + canonical) | **78.3%** (54/69) |

2 facts not found: g006, g014 (not present in the ingested chunks). 13 facts found but with partial issues (unit symbol mismatches, canonical_id gaps).

---

## Key Design Decisions

### 1. Two-pass LLM architecture
Pass 1 focuses on high-recall extraction. Pass 2 handles normalization deterministically (registry + fuzzy match), calling LLM only for tiebreakers. This means Pass 2 can be rerun cheaply when the registry changes without re-paying for Pass 1 extraction.

### 2. max_tokens=16000
Dense BRSR tables produce 50K+ character JSON responses. Raising the token limit from 3,000 → 16,000 eliminated truncation on energy/water/emissions pages.

### 3. Incremental crash recovery
`{prefix}_pass1_partial.jsonl` — one JSON line per completed chunk containing `{chunk_id, facts: [...]}`. On restart, the extractor reads this file, skips completed chunk IDs, and resumes from the next. Uses `ExtractedFact.from_dict()` for exact round-trip reconstruction.

### 4. Cross-document deduplication
BRSR tables always report current year + prior year comparative. Without dedup, loading FY2025 would create duplicate FY2024 observations. The dedup logic queries Neo4j for matching (canonical_id, value ±1%, period) and keeps the observation from the document whose year is closest to the reported period year.

### 5. TOC page detection
BRSR section heading in a TOC page would trigger the heuristic to select TOC page + 68 wrong pages. Fixed by detecting pages with ≥5 standalone 2–3 digit numbers (page number tokens) and skipping them when searching for the BRSR range start.

### 6. MTCO2E unit fix
Indian BRSR reports use "MT CO2e" to mean *metric tonnes*, not *megatonnes*. The unit normaliser was applying a ×1,000,000 factor. Fixed to factor=1 for all `mt co2e`, `mtco2e`, `mt co2 equivalent` variants. 6 Marico observations patched directly in Neo4j.

### 7. Streamlit query templates
Pre-written Cypher templates for the most common query patterns (cross-company comparison, time series) bypass LLM generation entirely for reliable demo queries. Template matching checks question keywords; falls back to LLM for everything else.

---

## How to Run

### Full pipeline for one document

```powershell
python pipeline/run_pipeline.py `
  --pdf "C:\path\to\Annual_Report.pdf" `
  --company nestle_india `
  --company-name "Nestlé India Limited" `
  --year 2024 `
  --calendar-type indian_fiscal
```

### Skip to KG load only (pass1 + pass2 already done)

```powershell
python pipeline/run_pipeline.py `
  --pdf "..." --company nestle_india --company-name "..." --year 2024
# Stages 1-4 are skipped automatically if output files exist
```

### Force rerun of Pass 2 only

```powershell
# Delete pass2 file, then run without --force
Remove-Item workspace_test_outputs\nestle_india_fy2024_pass2.json
python pipeline/run_pipeline.py --pdf "..." --company nestle_india --company-name "..." --year 2024 --no-kg
```

### Run Demo App (portfolio)

```powershell
python -m streamlit run graph/demo_app.py --server.port 8502
```

### Run Query App (NL→Cypher)

```powershell
python -m streamlit run graph/kg_query_app.py --server.port 8501
```

### Run eval

```powershell
python eval/eval_pipeline.py
```

### Run registry gap analysis

```powershell
python tools/registry_gap_analysis.py
```

### Export pass1 facts to Word

```python
# See export_readable_facts.py or run inline:
python -c "
import json
from docx import Document
# ... (see project for full script)
"
```

### The 4 production commands

```powershell
# Document 1 — Nestlé FY2024
python pipeline/run_pipeline.py --pdf "...\Annual-Report-2023-24-nestle-india.pdf" --company nestle_india --company-name "Nestlé India Limited" --year 2024 --calendar-type indian_fiscal

# Document 2 — Nestlé FY2025
python pipeline/run_pipeline.py --pdf "...\Annual-Report-2024-25-nestle-india.pdf" --company nestle_india --company-name "Nestlé India Limited" --year 2025 --calendar-type indian_fiscal

# Document 3 — Britannia FY2024
python pipeline/run_pipeline.py --pdf "...\BRITANNIA_Annual_Report_2023_24.pdf" --company britannia --company-name "Britannia Industries Limited" --year 2024 --calendar-type indian_fiscal

# Document 4 — Marico FY2024
python pipeline/run_pipeline.py --pdf "...\Marico_Annual_Report_FY24.pdf" --company marico --company-name "Marico Limited" --year 2024 --calendar-type indian_fiscal
```

---

## Output Files

For each `{prefix}` = `{company_id}_fy{year}`:

| File | Stage | Description |
|---|---|---|
| `{prefix}_selected_pages.json` | 1 | Selected page numbers + section metadata |
| `{prefix}_fast_chunks.json` | 1 | Full chunks with linking (chunk_id, page, text, prev/next) |
| `{prefix}_fast_metadata.json` | 1 | Section finder method, coverage risk, warnings |
| `{prefix}_section_coverage_audit.csv` | 2 | Missed high-signal pages |
| `{prefix}_pass1.json` | 3 | Raw extracted facts (schema_version, facts[]) |
| `{prefix}_pass1_partial.jsonl` | 3 | Incremental per-chunk facts (crash recovery) |
| `{prefix}_pass1_telemetry.json` | 3 | Per-chunk timing, token counts, drop reasons |
| `{prefix}_cost_summary.json` | 3 | API cost: prompt/completion tokens + USD |
| `{prefix}_pass2.json` | 4 | Normalized facts with canonical_id, normalised_value, status |
| `{prefix}_new_metric_distance_audit.csv` | 5 | new_metric facts with nearest canonical suggestions |
| `registry_gap_report.csv` | tool | Cross-company new_metric clusters + action recommendations |
| `registry_gap_aliases.json` | tool | Ready-to-merge alias suggestions |
| `{prefix}_pass1_facts.docx` | tool | Word doc export of Pass 1 keep-decision facts |

---

## Tools and Utilities

### `tools/registry_gap_analysis.py`

Queries Neo4j for all `new_metric` observations, clusters by semantic similarity (cosine threshold 0.85, falls back to difflib), and scores each cluster against the existing registry.

```
Output 1: registry_gap_report.csv
  cluster_id | representative_name | companies | frequency | suggested_canonical | match_score | action

Output 2: registry_gap_aliases.json
  {"raw_name": "suggested_canonical_id"}  — only add_alias entries (score > 0.75)

Console: Top 20 clusters, cross-company count, action breakdown
```

### `eval/eval_pipeline.py`

Measures pipeline quality against a hand-annotated gold set of 69 Nestlé FY2024 facts. Checks value (within 1% tolerance), unit (with aliases), period, and canonical_id match.

**Graph coverage: 97.1% (67/69 facts found)**  
**Fully correct: 78.3% (54/69)** — all four dimensions matching

Known misses and partial failures:
- g006, g014: facts not found in graph (chunks not ingested)
- g026: `employee_headcount` canonical_id mismatch
- g033: `water_withdrawal` vs `water_consumption_absolute` canonical mismatch
- g052: energy intensity canonical empty in graph
- g003, g007, g015, g028, g035, g044, g045: unit symbol mismatches (count/% handling)

### `export_readable_facts.py`

Exports Pass 1 or Pass 2 facts to CSV with columns: raw_name, metric_core, period, unit, value, normalization_status, evidence.

### `eval_gold_set.py`

Contains `GOLD_FACTS` — 69 annotated Nestlé FY2024 facts with expected canonical_id, value, unit, and period. Used by `eval_pipeline.py`.

---

## Demo Application

**File**: `graph/demo_app.py` — Streamlit app on port 8502

A portfolio-quality interactive demo surfacing the knowledge graph to a non-technical audience. Uses brand colors, Plotly charts, and provenance traces from the graph.

### Three tabs

**Tab 1 — Questions**  
Six pre-answered ESG questions with live Neo4j queries, dynamic worded summaries, and source text expanders showing the exact PDF sentence and page number.

| # | Question | Type | Chart |
|---|---|---|---|
| Q1 | How many permanent employees do these companies have? | Social | Horizontal bar |
| Q2 | How do Scope 1 emissions compare across companies? | Environmental | Horizontal bar |
| Q3 | What % of Britannia's energy is still from fossil fuels? | Environmental | Stat card (dark) |
| Q4 | What share of total wages goes to female employees? | Social | % bar |
| Q5 | How have Nestlé's Scope 1 emissions changed over time? | Environmental | Line trend (CY2023–FY2025) |
| Q6 | How confident are we in Nestlé's water withdrawal figure? | Provenance | Confidence card |

**Tab 2 — Graph Explorer**  
13 verified metrics selectable via dropbox. Dynamic year/company filters per metric. Horizontal bar chart with value+unit labels outside bars. Single-company results fall back to a stat card.

Verified metrics include: Scope 1/2 Emissions, Water Withdrawal/Consumption (kL), Total Energy Renewable/Non-Renewable, Plastic Waste Generated/Collected, Employee Headcount, Recordable Injuries (Workers/Employees), Worker Union Membership, Waste Generated.

**Tab 3 — Ask a Question**  
Disabled NL interface (placeholder for future LLM→Cypher integration). Shows 4 example question cards and a capability summary grid.

### Key implementation details

- **Colors**: Nestlé `#009EDB`, Britannia `#C41E3A`, Marico `#E8832A`  
- **Deduplication**: `max(o.normalised_value)` within `WITH c, ...` groups removes comparative sub-segment rows  
- **Evidence**: `ev.text` property; `clean_evidence()` extracts ≤200-char keyword-anchored snippet  
- **Q3 (fossil %)**: Two-query Python computation — non_renewable ÷ total energy × 100 for Britannia  
- **Q5 (trend)**: Filters `normalised_value < 1,000,000` to exclude erroneous scale readings; note shown about 15-month FY2024 transition period  
- **Q6 (provenance)**: Traverses `HAS_CONFIDENCE → ConfidenceRecord` for `final_confidence` score  
- **Company name**: All nodes use `c.name` (not `c.display_name`, which is NULL in all nodes)

---



### pipeline_config.json

```json
{
    "neo4j_uri": "neo4j://127.0.0.1:7687",
    "neo4j_user": "neo4j",
    "neo4j_pass": "Watermelon@123",
    "output_dir": "workspace_test_outputs",
    "default_sector": "FMCG",
    "default_country": "India",
    "default_currency": "INR",
    "openai_model_pass1": "gpt-4.1-mini",
    "openai_model_pass2_tiebreaker": "gpt-4.1-mini"
}
```

### .env

```
OPENAI_API_KEY=sk-proj-...
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASS=Watermelon@123
```

### Key tuning constants (in code)

| Constant | File | Value | Purpose |
|---|---|---|---|
| `MODEL` | extractor.py | `gpt-4.1-mini` | LLM for Pass 1 |
| `MAX_CONCURRENT_CALLS` | extractor.py | 4 | Parallel API calls |
| `SCORE_FLOOR` | gold_set.py | 0.65 | Min score to consider a canonical match |
| `SCORE_MARGIN` | gold_set.py | 0.20 | Margin to trigger tiebreaker |
| `SIMILARITY_THRESHOLD` | registry_gap_analysis.py | 0.85 | Cosine threshold for clustering |
| `ALIAS_SCORE_MIN` | registry_gap_analysis.py | 0.75 | Threshold for alias suggestion |
