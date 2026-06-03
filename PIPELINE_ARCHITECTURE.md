# ESG Fact Extraction Pipeline — Architecture

**Project:** Consumer company ESG & operational KPI extraction from annual reports  
**Stack:** Python · OpenAI GPT · Neo4j · Node.js (Word docs)  
**Benchmark companies:** Nestle India, Tata Consumer, GCPL, ITC

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
   - [Chunk](#chunk)
   - [Pass 1 Fact (EDC)](#pass-1-fact-edc)
   - [Pass 2 Fact (Enriched)](#pass-2-fact-enriched)
5. [Registry System](#5-registry-system)
6. [Unit Normalisation](#6-unit-normalisation)
7. [Financial Classifier](#7-financial-classifier)
8. [Knowledge Graph Schema](#8-knowledge-graph-schema)
9. [Verification & Quality Gates](#9-verification--quality-gates)
10. [Benchmark Run System](#10-benchmark-run-system)
11. [Known Issues & Current Status](#11-known-issues--current-status)
12. [Cost & Token Profile](#12-cost--token-profile)

---

## 1. Overview

The pipeline converts raw PDF annual reports into a structured Neo4j knowledge graph of ESG and operational metrics. It does this in two LLM passes separated by a deterministic normalisation layer.

```
PDF
 │
 ▼
[Stage 0] fast_pdf_text_ingest.py
 │  Page selection → text extraction → chunking → prev/next linking
 │
 ▼  nestle_india_rerun_fast_chunks.json
[Stage 1] extractor.py  (LLM: gpt-4.1-mini)
 │  Per-chunk fact extraction → validation → dedup → rescue pass
 │
 ▼  nestle_india_pass1_rerun.json
[Stage 2] normalizer.py  (fuzzy match + LLM tiebreaker: gpt-4.1-mini)
 │  Registry matching → unit normalisation → financial filtering → enrichment
 │
 ▼  nestle_india_pass2_rerun.json
[Stage 3] kg_loader_nestle.py  (Neo4j)
 │  Node creation → relationship wiring → provenance chain
 │
 ▼  Neo4j KG
```

---

## 2. Repository Layout

```
test/
│
├── PIPELINE ENTRY POINTS
│   ├── fast_pdf_text_ingest.py       Stage 0 — PDF → chunks
│   ├── extractor.py                  Stage 1 — chunks → Pass 1 facts
│   ├── normalizer.py                 Stage 2 — Pass 1 → Pass 2 facts
│   ├── kg_loader_nestle.py           Stage 3 — Pass 2 → Neo4j
│   └── benchmark_rerun.py           Orchestrates Stages 0–2 for all companies
│
├── PROMPTS & SCHEMA
│   ├── pass1_prompt_lean.py          Primary extraction prompt (gpt-4.1-mini)
│   ├── pass1_prompt_balanced.py      Secondary extraction prompt (fallback)
│   ├── pass1_lean_schema.py          JSON schema for Pass 1 output fields
│   └── pass1_validate.py             Period normalisation, fact type inference
│
├── REGISTRY
│   ├── consumer_master_registry_v1.json    51 canonical metric definitions
│   ├── registry_additions_approved.json   42 approved additions
│   ├── registry_aliases.json              229 raw-name → canonical_id aliases
│   └── registry_semantic_overrides.json   Semantic typing overrides
│
├── NORMALISATION
│   ├── unit_normaliser.py            Unit conversion + confidence scoring
│   ├── metric_registry_seed.py       Registry seed + alias index builder
│   ├── gold_set.py                   Fuzzy match scoring (cosine + alias)
│   ├── semantic_registry.py          Semantic typing, alias gate
│   └── definitions.py               Metric definition matching
│
├── QUALITY & VERIFICATION
│   ├── verify_unit_normalisation.py  Checks exact/inferred confidence vs null value
│   ├── verify_provenance_fields.py   Checks all 5 provenance fields present
│   ├── check_confidence_fields.py    Confidence enrichment helper
│   ├── check_provenance_fields.py    Provenance backfill helper
│   └── test_pre_kg_pipeline_fixes.py 41 regression tests
│
├── SUPPORT
│   ├── models.py                     Chunk, Fact, TemporalContext dataclasses
│   ├── section_finder.py             PDF section detection
│   ├── audit_selected_pages.py       Page selection coverage audit
│   ├── provisional_dedup.py          Cross-company new_metric clustering
│   ├── export_readable_facts.py      Pass1+Pass2 → readable CSV
│   ├── normalizer_guardrails.py      Value extraction guardrails
│   ├── provisional_review.py         Review file writer
│   └── review_memory.py / .json      Human review decisions (persisted)
│
└── workspace_test_outputs/           All pipeline artifacts
```

---

## 3. Pipeline Stages

### Stage 0 — PDF Ingestion & Chunking

**File:** `fast_pdf_text_ingest.py`  
**Input:** Annual report PDF  
**Output:** `{company}_rerun_fast_chunks.json`

#### What it does

1. **Page selection** — scans all PDF pages and scores each for operational/ESG content using keyword weights from `section_finder.py`. Pages below the threshold are excluded. Produces `{company}_rerun_selected_pages.json`.

2. **Section detection** — groups selected pages into logical sections (Board's Report, BRSR, Cash Flow, Notes, etc.).

3. **Text extraction** — uses PyMuPDF (`fitz`) to extract raw text from selected pages, preserving table structure where possible.

4. **Chunking** — splits section text into overlapping chunks with a max word limit (default ~500 words), 5-word overlap. Large table chunks are split further by `_split_large_table_chunk`.

5. **Prev/next linking** — after all chunks are built, iterates the list and sets `prev_chunk_id` / `next_chunk_id` on each chunk. This is the provenance chain used by the KG.

6. **Historical reprint detection** — chunks from reprinted prior-year data (identified by temporal context patterns) are flagged `is_historical_reprint=True` and excluded from extraction.

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

`audit_selected_pages.py` re-scans the PDF after page selection and flags any high-signal pages that were not selected (`high_signal_unselected`). Acts as a recall check on the page selector.

---

### Stage 1 — Pass 1: Fact Extraction (LLM)

**File:** `extractor.py`  
**Model:** `gpt-4.1-mini` (was `gpt-4o-mini`)  
**Input:** `{company}_rerun_fast_chunks.json`  
**Output:** `{company}_pass1_rerun.json`

#### What it does

For each chunk, sends a structured extraction prompt to the LLM asking it to return all quantitative business facts as JSON. The lean prompt (`pass1_prompt_lean.py`) instructs the model to:

- Extract every metric-value pair with raw unit, period, scope, dimension
- Never normalise values or resolve canonical names — downstream does that
- Tag `graph_fact_type` (operational_metric, financial_metric, mix_share_metric, etc.)
- Tag `fact_type` (measurement, target, baseline, ratio, count, boolean)
- Follow explicit rules for absolute-vs-relative values, sustainability targets, and biographical noise

#### Extraction rules (key prompt additions)

- **Absolute value rule** — when a sentence has both an absolute figure and a fold-increase ("4 million outlets, a two-fold increase"), extract the absolute as primary. Never extract the multiplier as the count value.
- **Sustainability targets** — explicitly extract future commitments as `fact_type=target` with the target year as `period_end`. Do not drop targets because they lack a current measured value.
- **Anti-noise** — exclude tenure years, award counts, committee seat numbers, page/section references.

#### Validation & dedup (`pass1_validate.py`)

After LLM response:

1. **Schema enforcement** — checks all required fields present, fills defaults
2. **Period resolution** — resolves `raw_period` strings ("FY2022", "last two years", etc.) to `period_start`/`period_end` ISO dates
3. **Fact type inference** — infers measurement/target/baseline/count/boolean from context when LLM omits it
4. **Anchor dedup** — removes facts that are structural anchors (table headers, section labels) with no real numeric content
5. **Duplicate removal** — deduplicates on (metric_core, raw_value, period) key

#### Rescue pass (neighbor context)

After initial extraction, facts that were dropped or uncertain are re-sent with neighboring chunk text prepended for context. The model sees prev_chunk → current_chunk → next_chunk. This recovers facts where the column header or unit is on a different page.

```
Rescue stats (Nestle FY2024): sent=11, confirmed=10, corrected=1, rejected=0
```

#### Pass 1 output per fact

```json
{
  "fact_id": "nestle_india_p209_1_fact_1",
  "chunk_id": "nestle_india_p209_1",
  "section_id": "nestle_india_page_209",
  "doc_id": "nestle_india",
  "prev_chunk_id": "nestle_india_p203_2",
  "next_chunk_id": "nestle_india_p210_1",
  "metric": "total volume of water withdrawal",
  "value": "3,232,635",
  "unit": "kiloliters",
  "period": "FY2024",
  "period_start": "2023-04-01",
  "period_end": "2024-03-31",
  "period_type": "full_year",
  "period_confidence": "inferred",
  "fact_type": "measurement",
  "evidence": "Total volume of water withdrawal [in kiloliters] 3,232,635 2,800,232",
  "decision": "keep",
  "confidence": "high",
  "raw": {
    "raw_name": "total volume of water withdrawal",
    "metric_core": "water_withdrawal",
    "raw_value": "3,232,635",
    "raw_unit": "kiloliters",
    "graph_fact_type": "operational_metric",
    "fact_class": "scalar_kpi",
    "source_sentence": "..."
  }
}
```

---

### Stage 2 — Pass 2: Normalization & Registry Matching

**File:** `normalizer.py`  
**Model:** `gpt-4.1-mini` (tiebreaker calls only)  
**Input:** `{company}_pass1_rerun.json`  
**Output:** `{company}_pass2_rerun.json`

#### What it does

Takes Pass 1 facts and maps each to a canonical metric in the registry, then runs unit normalisation. No new LLM extraction happens — the LLM is only used for tiebreaking ambiguous registry matches.

#### Processing flow (per fact)

```
Pass 1 fact
     │
     ▼
[Financial classifier]
     │  Is this a financial metric? → out_of_scope_financial (skip to output)
     │  Checked BEFORE alias lookup so financial facts can't bypass it
     │
     ▼
[Alias lookup]  registry_aliases.json (229 entries)
     │  Exact raw_name match → canonical_id, normalization_decision=normalized
     │
     ▼ (if no alias match)
[Fuzzy registry match]  gold_set.py
     │  Cosine similarity on metric_core + alias_score + definition_score
     │  Score > threshold + margin → accept
     │  Score in margin band → provisional (needs tiebreaker)
     │  Score too low → new_metric
     │
     ▼ (if provisional)
[Semantic tiebreaker]  LLM call
     │  Sends fact + top-2 candidates + definitions
     │  Returns accept/reject with reasoning
     │
     ▼
[_enrich_normalized_fact]
     │  Unit normalisation via unit_normaliser.py
     │  Adds: normalised_value, normalised_unit_symbol, normalisation_confidence
     │  Adds: raw_value, raw_unit (promoted from raw sub-object)
     │  Adds: period_label (alias of period field)
     │  Adds: canonical_name, canonical_category, canonical_definition
     │
     ▼
Pass 2 enriched fact
```

#### Normalization decisions

| Decision | Meaning |
|---|---|
| `normalized` | Matched to a canonical_id with high confidence |
| `partial` | Matched but with caveats (rescue fact, medium confidence) |
| `new_metric` | No registry match — proposed as a new canonical candidate |
| `out_of_scope_financial` | Financial/P&L metric — excluded from ESG KG |
| `drop` | Pass 1 already dropped, carried through |
| `quarantine` | Flagged for human review (e.g. implausible Scope 3 magnitude) |

#### Nestle benchmark results (gpt-4o-mini, full run)

| Decision | Count |
|---|---|
| normalized | 15 |
| partial | 23 |
| new_metric | 45 |
| out_of_scope_financial | 56 |
| drop | 49 |
| **Total** | **188** |

---

### Stage 3 — Knowledge Graph Loading

**File:** `kg_loader_nestle.py`  
**Database:** Neo4j 5.x, `neo4j://127.0.0.1:7687`  
**Input:** `{company}_pass2_rerun.json` + `{company}_rerun_fast_chunks.json`

#### Node types created

| Label | Count (Nestle) | Description |
|---|---|---|
| Company | 1 | Top-level company node |
| Document | 1 | Annual report filing |
| Section | 28 | PDF sections |
| Chunk | 40 | Text chunks with full content |
| Observation | 83 | One per extracted fact (normalized/partial/new_metric only) |
| Metric:Canonical | 93 | Registry metric definitions |
| Metric:Provisional | ~45 | New metric candidates |
| Period | 15 | FY2018–FY2030 + CY2022 + FY2023_15M |
| Unit | 18 | With CONVERTS_TO edges |
| MetricCategory | 41 | 3-level hierarchy |
| Evidence | 83 | Source sentences |
| ConfidenceRecord | 83 | Normalisation confidence metadata |

#### Relationship types

```
(Company)-[:FILED]->(Document)
(Section)-[:IN_DOCUMENT]->(Document)
(Chunk)-[:IN_SECTION]->(Section)
(Chunk)-[:NEXT]->(Chunk)                     ← provenance chain
(Observation)-[:REPORTED_BY]->(Company)
(Observation)-[:IN_PERIOD]->(Period)
(Observation)-[:EXTRACTED_FROM]->(Chunk)     ← source traceability
(Observation)-[:MEASURED_IN]->(Unit)
(Observation)-[:OF_METRIC]->(Metric)
(Observation)-[:SUPPORTED_BY]->(Evidence)
(Observation)-[:HAS_CONFIDENCE]->(ConfidenceRecord)
(Evidence)-[:FOUND_IN]->(Chunk)
(Metric)-[:BELONGS_TO]->(MetricCategory)
(MetricCategory)-[:SUBCATEGORY_OF]->(MetricCategory)
(Unit)-[:CONVERTS_TO {factor}]->(Unit)
(Period)-[:NEXT_YEAR]->(Period)
```

#### Facts loaded vs skipped

Only `normalized`, `partial`, and `new_metric` facts are loaded. `out_of_scope_financial`, `drop`, and `quarantine` are excluded entirely. This keeps the KG clean — no P&L contamination.

---

## 4. Data Models

### Chunk

Defined in `models.py` as a dataclass.

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

### Pass 1 Fact (EDC)

Schema version: `edc_v1`. Key fields:

| Field | Description |
|---|---|
| `fact_id` | Unique, derived from chunk_id + sequence |
| `chunk_id`, `section_id`, `doc_id` | Provenance chain |
| `prev_chunk_id`, `next_chunk_id` | Chunk navigation (required for KG) |
| `metric` | Raw metric name as extracted |
| `value` | Raw numeric value as string |
| `unit` | Raw unit string |
| `period` | Resolved period label (FY2024, CY2022, etc.) |
| `period_start` / `period_end` | ISO dates |
| `period_type` | full_year / partial / point_in_time / target / baseline |
| `fact_type` | measurement / target / baseline / ratio / count / boolean |
| `evidence` | Source sentence from PDF |
| `decision` | keep / drop / rescue |
| `raw` | Full LLM output sub-object (raw_name, metric_core, graph_fact_type, etc.) |

### Pass 2 Fact (Enriched)

All Pass 1 fields plus:

| Field | Description |
|---|---|
| `canonical_id` | Matched registry ID, null for new_metric |
| `canonical_name` | Human-readable registry name |
| `canonical_category` | e.g. `water`, `emissions`, `workforce` |
| `normalization_decision` | normalized / partial / new_metric / out_of_scope_financial / drop |
| `normalised_value` | Float, unit-converted value |
| `normalised_unit_symbol` | Canonical unit (kL, tCO2e, %, count, etc.) |
| `normalisation_confidence` | exact / inferred / needs_context / failed |
| `raw_value` | Promoted from raw sub-object |
| `raw_unit` | Promoted from raw sub-object |
| `raw_unit_string` | Original unit string |
| `period_label` | Alias of `period` field (for KG compatibility) |
| `mapping_confidence` | high / medium / low / no_match |
| `tiebreaker_used` | bool — whether LLM tiebreaker was called |
| `final_confidence` | Float 0–1 |

---

## 5. Registry System

Three files are merged at runtime to form the active registry:

| File | Entries | Description |
|---|---|---|
| `consumer_master_registry_v1.json` | 51 | Core canonical metrics |
| `registry_additions_approved.json` | 42 | Human-reviewed additions from new_metric analysis |
| `registry_semantic_overrides.json` | — | Typing corrections for specific canonical IDs |
| `registry_aliases.json` | 229 | raw_name → canonical_id fast lookup |

Each canonical metric entry contains:

```json
{
  "canonical_id": "water_consumption_absolute",
  "display_name": "Water Consumption (Absolute)",
  "category": "water",
  "unit_family": "volume",
  "metric_subject": "water",
  "metric_role": "consumption",
  "comparable": true,
  "canonical_definition": "Total volume of water consumed...",
  "external_refs": {"GRI": "303-5", "BRSR": "P6-E1"}
}
```

#### Registry matching algorithm (`gold_set.py`)

Score = weighted combination of:
- `alias_score` — BM25/cosine match between raw_name and registry aliases
- `metric_core_score` — snake_case metric_core similarity
- `definition_score` — semantic similarity between metric_definition and canonical_definition

If `score > SCORE_FLOOR + SCORE_MARGIN` → accept  
If `score > SCORE_FLOOR` → provisional (tiebreaker)  
If `score < SCORE_FLOOR` → new_metric

#### Semantic alias gate

Before accepting a fuzzy match, `semantic_alias_gate` checks that the metric subject (water, emissions, energy, etc.) is compatible between the input fact and the candidate canonical. Blocks subject mismatches even when surface similarity is high.

---

## 6. Unit Normalisation

**File:** `unit_normaliser.py`

Called inside `_enrich_normalized_fact` for every fact that passes the financial filter. Converts raw units to canonical symbols and produces a confidence score.

#### Confidence levels

| Level | Meaning |
|---|---|
| `exact` | Unit found directly in UNIT_MAP, no inference needed |
| `inferred` | Unit inferred from context (count hint, compound unit decomposed) |
| `needs_context` | Unit present but ambiguous — value set to null |
| `failed` | Unit not recognised — value set to null |

#### Key invariant (enforced by bug fix)

If `normalised_value is None` and confidence would be `exact` or `inferred`, confidence is downgraded to `needs_context`. A confident label with a null value is an error.

#### Verification script

`verify_unit_normalisation.py` checks:
- **ERROR:** any fact where `normalisation_confidence IN (exact, inferred)` AND `normalised_value IS NULL`
- Reports total facts, null facts by confidence level, PASS/FAIL verdict per company

Current status: **all 4 benchmark companies PASS** (0 exact/inferred but null errors).

---

## 7. Financial Classifier

**Function:** `_is_financial_fact()` in `normalizer.py`

Runs before alias lookup and fuzzy matching. If a fact is classified as financial, it goes directly to `out_of_scope_financial` and is never sent to the registry matcher.

#### Detection layers (in order)

1. `graph_fact_type == "financial_metric"` from Pass 1 LLM output
2. Fact's own `metric` field matches `_FINANCIAL_METRIC_NAMES` set (exact lowercased match)
3. Fact's own `metric` field matches `_FINANCIAL_KEYWORD_RE` regex
4. Fact's own `metric` field matches `_GROWTH_RATE_RE` regex (YoY, CAGR, year-on-year)
5. Registry match's `raw_name`/`metric_core` matches `_FINANCIAL_KEYWORD_RE`

#### Key patterns blocked

EBITDA, EBIT, revenue, turnover, profit (all variants), EPS, earnings per share, cash and cash equivalents, operating/investing/financing cash flow, CAPEX, capital expenditure, return on equity/net worth/capital employed, ROCE, margins (operating/net/gross/profit), CAGR, retained earnings, shareholders fund, tax expense, working capital ratios.

#### Critical implementation note

The classifier runs as a **pre-filter in `run_pass2`** before facts reach the batch/alias/fuzzy loop. This was a bug fix — previously alias lookup ran first, so facts like `sales → total_revenue` and `operating cash flow → operating_cash_flow` bypassed the classifier via the alias index.

#### Regression tests

41 regression tests in `test_pre_kg_pipeline_fixes.py` including:
- EBITDA, EBITDA margin, revenue growth, cash equivalents, operating cash flow, EPS, CAGR, ROCE → all classified as financial
- water intensity, GHG emissions, outlet count, number of employees (from operational context) → not classified as financial

---

## 8. Knowledge Graph Schema

### Neo4j node labels and properties

```
(:Company)
  company_id, name, sector, country

(:Document)
  doc_id, fiscal_year, report_type, page_count,
  has_brsr, has_third_party_assurance, assurance_provider, assurance_level

(:Section)
  section_id, title

(:Chunk)
  chunk_id, page, text, char_count, token_count

(:Observation)
  obs_id, raw_name, raw_value, raw_unit_string,
  normalised_value, normalised_unit_symbol, normalisation_confidence,
  period_label, period_start, period_end, period_type, period_confidence,
  fact_type, normalization_status, page, chunk_id, canonical_id

(:Metric:Canonical)
  canonical_id, display_name, category, unit_family,
  metric_subject, metric_role, comparable, external_refs

(:Metric:Provisional)
  provisional_id, raw_name, owner_company

(:Period)
  fiscal_year, year_start, year_end, calendar

(:Unit)
  symbol, label, unit_family

(:MetricCategory)
  category_id, name, level

(:Evidence)
  evidence_id, text

(:ConfidenceRecord)
  conf_id, normalization_status, normalisation_confidence, final_confidence
```

### Category hierarchy (3 levels)

```
Environmental → Water → Water Consumption/Withdrawal/Discharge/Recharge/Conservation
             → Energy → Energy Consumption/Intensity/Renewable/Conservation
             → Emissions → Scope 1/2/3/GHG Intensity/Air Emissions
             → Waste → Generation/Recovery/Disposal/Intensity/Plastic
             → Packaging → Plastic Packaging/Recyclable/EPR
Social       → Workforce → Headcount/Safety/Training/Diversity
             → Community → CSR/Complaints
Governance   → Compliance → BRSR/EPR Compliance
```

### Fulltext indexes

```cypher
chunk_text_index    ON Chunk(text)
evidence_text_index ON Evidence(text)
```

---

## 9. Verification & Quality Gates

Two verification scripts run after every Pass 2 output:

### verify_unit_normalisation.py

Checks: no fact has `normalisation_confidence IN (exact, inferred)` with `normalised_value = null`.

```
python verify_unit_normalisation.py --root .
```

### verify_provenance_fields.py

Checks: all 5 provenance fields present on every fact — `chunk_id`, `section_id`, `doc_id`, `prev_chunk_id`, `next_chunk_id`.

```
python verify_provenance_fields.py --root .
```

### Current benchmark status

| Company | Unit Normalisation | Provenance | Pass 1 Facts | Pass 2 Facts |
|---|---|---|---|---|
| nestle_india | PASS | PASS | 188 | 188 |
| tata_consumer | PASS | PASS | 783 | 783 |
| gcpl | PASS | PASS | 920 | 920 |
| itc | PASS | PASS | 906 | 906 |

*Note: GCPL and ITC pass2_rerun.json were deleted during the alias-bypass fix rerun. Their current pass2 outputs are the pre-fix versions (`gcpl_pass2.json`, `itc_pass2.json`). They need to be regenerated with the fixed normalizer.*

### Regression test suite

```
python -m pytest test_pre_kg_pipeline_fixes.py -v
```

41 tests covering: financial classifier, tiebreaker conflicts, period resolution, unit normalisation, chunk prev/next wiring, new_metric dedup.

---

## 10. Benchmark Run System

**File:** `benchmark_rerun.py`

Orchestrates a full pipeline run for any of the 4 benchmark companies with resume logic — each step is skipped if its output file already exists.

```
python benchmark_rerun.py --company nestle_india
python benchmark_rerun.py --company nestle_india --company tata_consumer
python benchmark_rerun.py --no-resume  # force full rerun
```

#### Resume logic

| Step | Output file | Skipped if exists? |
|---|---|---|
| fast_pdf_text_ingest | `{company}_rerun_fast_chunks.json` | Yes |
| audit_selected_pages | `{company}_rerun_section_coverage_audit.csv` | Yes |
| extractor (Pass 1) | `{company}_pass1_rerun.json` | Yes |
| normalizer (Pass 2) | `{company}_pass2_rerun.json` | Yes |
| export_readable_facts | `{company}_pass2_rerun_readable.csv` | Yes |

#### Benchmark diff report

After each run, `benchmark_diff_report.txt` is written with before/after normalized/partial/new_metric/financial counts, period coverage, fact_type distribution, unit normalisation stats, and provenance field coverage.

#### Important: Pass 2 checkpoint

The normalizer uses the existing `pass2_rerun.json` as a checkpoint — facts already in the file are skipped. **Always delete the pass2 output before rerunning if the normalizer code has changed**, otherwise old results are reused.

---

## 11. Known Issues & Current Status

### Fixed

- **unit_normaliser.py — exact/inferred confidence with null value** — when a unit was recognised but raw_value was null, confidence was left as `exact`/`inferred`. Fixed: downgrade to `needs_context`.
- **normalizer.py — LLM confidence overwrote unit_norm confidence** — `enriched = dict(fact)` copied LLM's `normalisation_confidence` into the enriched dict, and the `or` chain preferred it over `unit_norm`. Fixed: use `unit_norm.get("normalisation_confidence")` exclusively.
- **normalizer.py — alias lookup bypassed financial classifier** — `_resolve_batch_by_alias` ran before `_is_financial_fact`, letting `sales → total_revenue`, `operating cash flow → operating_cash_flow` etc. through as `normalized`. Fixed: pre-filter financial facts in `run_pass2` before batching.
- **Tata Consumer / GCPL / ITC chunks missing prev/next fields** — chunks were generated before the prev/next linking code was added. Fixed: backfilled from chunk ordering.
- **GCPL / ITC pass1 missing section_id / doc_id** — old pass1_edc schema didn't include these. Fixed: backfilled from chunk lookup.
- **raw_value / raw_unit not in pass2 output** — `_enrich_normalized_fact` read them into local variables but never wrote them to the enriched dict. Fixed.
- **period_label missing from pass2 output** — the field is called `period` in pass1 but `period_label` in the KG schema. Fixed: added `enriched["period_label"] = enriched.get("period")`.
- **benchmark_rerun.py period_stats NameError** — generator expression variable leaked. Fixed.
- **benchmark_rerun.py crash on missing before-file** — `nestle_india_pass2.json` archived during cleanup. Fixed: graceful fallback to empty list.

### Outstanding

- **GCPL / ITC need full Pass 2 rerun** — their current `pass2_rerun.json` files were deleted. `gcpl_pass2.json` and `itc_pass2.json` (pre-fix) are the only pass2 outputs for these companies.
- **GCPL / ITC period_type / fact_type all unknown** — their pass1_edc.json was generated with an older extractor schema that didn't include these fields. Needs fresh Pass 1 extraction to populate.
- **gpt-4.1-mini API timeouts on dense table chunks** — 4.1-mini is slower than 4o-mini on large structured text. `API_TIMEOUT_SECONDS = 300` is too low. Fix: increase to 600, or implement streaming to make timeouts based on inter-token silence rather than total response time.
- **`Number of employees` from financial ratios page classified as financial** — LLM tags it `graph_fact_type: financial_metric` because it appears on the same page as Sales/EPS. The HR section correctly extracts `total employees` as headcount. Low priority.

---

## 12. Cost & Token Profile

Based on Nestle India FY2024 (40 chunks, 188 facts):

### Token breakdown (one full run)

| Stage | Input tokens | Output tokens |
|---|---|---|
| Pass 1 (40 chunks × ~5,000) | ~201,000 | ~80,000 |
| Pass 2 tiebreaker (23 calls × 400/100) | ~9,200 | ~2,300 |
| **Total** | **~210,000** | **~82,000** |

System prompt dominates: 4,433 tokens × 40 chunks = 177,320 tokens of input.

### Cost per run (Nestle only)

| Model | Per run | 4 companies | 10 companies |
|---|---|---|---|
| gpt-4o-mini (old) | $0.08 | $0.28 | $0.71 |
| gpt-4.1-mini (current) | $0.22 | $0.76 | $1.89 |
| gpt-4.1-nano | $0.05 | $0.19 | $0.47 |
| gpt-5-mini ($0.25/$0.025c/$2.00) | $0.22 | $0.76 | $1.90 |

*4 companies uses 3.5x Nestle multiplier (others average ~400 pages vs Nestle's 244).*

### API calls

- Pass 1: 40 calls (1 per chunk)
- Pass 2: ~23 calls (tiebreaker only)
- **Total: ~63 calls per company**

### Timeout issue

`API_TIMEOUT_SECONDS = 300` in `extractor.py`. gpt-4.1-mini exceeded this on 13/40 chunks (dense ESG tables). Fix: increase to 600 or implement streaming.
