# Knowledge Graph Structure

This document describes the exact structure of the Neo4j knowledge graph as it exists today. All node counts, property names, and relationship types are verified against the live database.

---

## At a Glance

| Total nodes | 10,271 |
|---|---|
| Total relationships | 18,108 |
| Observation nodes | 2,431 |
| Companies | 3 |
| Documents | 4 |
| Periods | 4 |
| Canonical metrics | 249 |
| Provisional metrics | 1,456 |

---

## Node Types

### Observation `(2,431 nodes)`

The central node type. One Observation per extracted ESG fact. Every Observation connects to exactly one Company, one Period, one Metric, one Chunk, one Evidence, and one ConfidenceRecord.

**Properties:**

| Property | Type | Example | Notes |
|---|---|---|---|
| `obs_id` | string | `nestle_india_p209_1_fact_1_norm` | Unique identifier |
| `raw_name` | string | `"Total volume of water withdrawal"` | Metric name as extracted from PDF |
| `raw_value` | string | `"3232635"` | Value as extracted (string, may contain commas) |
| `raw_unit_string` | string | `"kiloliters"` | Unit as extracted |
| `normalised_value` | float | `3232635.0` | Unit-converted numeric value |
| `normalised_unit_symbol` | string | `"kL"` | Canonical unit symbol |
| `normalisation_confidence` | string | `"exact"` | `exact` / `inferred` / `needs_context` / `failed` |
| `normalization_status` | string | `"normalized"` | `normalized` / `partial` / `new_metric` |
| `canonical_id` | string | `"water_withdrawal_absolute"` | Registry ID (null for new_metric) |
| `source_doc_id` | string | `"nestle_india_fy2024"` | Source document |
| `chunk_id` | string | `"nestle_india_p209_1"` | Source chunk |
| `page` | integer | `209` | PDF page number |
| `period_label` | string | `"FY2024"` | Period alias (matches Period.fiscal_year) |
| `period_start` | string | `"2023-04-01"` | ISO date |
| `period_end` | string | `"2024-03-31"` | ISO date |
| `period_type` | string | `"full_year"` | `full_year` / `partial` / `point_in_time` / `target` |
| `period_confidence` | string | `"high"` | Confidence in period assignment |
| `fact_type` | string | `"measurement"` | `measurement` / `target` / `baseline` / `ratio` / `count` |

**Normalization status breakdown:**

| Status | Count | % | Linked to Canonical? |
|---|---|---|---|
| `new_metric` | 1,872 | 77% | No — linked to Provisional node |
| `partial` | 310 | 13% | Yes |
| `normalized` | 249 | 10% | Yes |

**Per company:**

| Company | new_metric | partial | normalized | Total |
|---|---|---|---|---|
| Nestlé India | 1,025 | 150 | 136 | 1,311 |
| Marico Limited | 519 | 103 | 65 | 687 |
| Britannia Industries | 328 | 57 | 48 | 433 |

**Per period:**

| Period | Observations |
|---|---|
| FY2024 | 1,655 |
| FY2025 | 775 |
| CY2023 | 1 |

---

### Company `(3 nodes)`

| Property | Type | Values |
|---|---|---|
| `company_id` | string | `nestle_india` / `britannia` / `marico` |
| `name` | string | `Nestle India Limited` / `Britannia Industries Limited` / `Marico Limited` |
| `sector` | string | `FMCG` (all three) |
| `country` | string | `India` (all three) |

> **Important:** `display_name` is NULL on all Company nodes. Always use `c.name` in queries.

---

### Document `(4 nodes)`

One per annual report filing.

| Property | Type | Example |
|---|---|---|
| `doc_id` | string | `nestle_india_fy2024` |
| `fiscal_year` | string | `FY2024` |
| `filing_year` | integer | `2024` |
| `report_type` | string | `annual_report` |
| `calendar_type` | string | `indian_fiscal` / `calendar_year` |

**Documents in graph:**

| doc_id | fiscal_year | calendar_type |
|---|---|---|
| `nestle_india_fy2024` | FY2024 | indian_fiscal |
| `nestle_india_fy2025` | FY2025 | indian_fiscal |
| `britannia_fy2024` | FY2024 | indian_fiscal |
| `marico_fy2024` | FY2024 | indian_fiscal |

---

### Period `(4 nodes)`

| Property | Type | Description |
|---|---|---|
| `fiscal_year` | string | `FY2024` / `FY2025` / `CY2023` / `CY2022` — the lookup key |
| `year_start` | string | ISO date, e.g. `2023-04-01` |
| `year_end` | string | ISO date, e.g. `2024-03-31` |
| `calendar` | string | `indian_fiscal` or `calendar_year` |

**All periods:**

| fiscal_year | year_start | year_end | calendar | Notes |
|---|---|---|---|---|
| `FY2024` | 2023-04-01 | 2024-03-31 | indian_fiscal | Nestlé: 15-month Jan 2023–Mar 2024 |
| `FY2025` | 2024-04-01 | 2025-03-31 | indian_fiscal | Standard 12-month |
| `CY2023` | 2023-01-01 | 2023-12-31 | calendar_year | Nestlé CY2023 annual |
| `CY2022` | 2022-01-01 | 2022-12-31 | calendar_year | Legacy |

`FY2024 -[:NEXT_YEAR]-> FY2025` is the only active chain.

---

### Metric:Canonical `(249 nodes)`

Registry-defined metrics with stable IDs. Used for cross-company comparison.

| Property | Type | Example |
|---|---|---|
| `canonical_id` | string | `scope_1_emissions` |
| `display_name` | string | `Scope 1 GHG Emissions (Absolute)` |
| `category` | string | `emissions` |
| `unit_family` | string | `mass_equivalent` |
| `metric_subject` | string | `company` |
| `metric_role` | string | `total` |
| `comparable` | boolean | `true` |
| `external_refs` | string | `[{"standard":"BRSR","id":"Principle 6"}]` |

**By category:**

| category | count |
|---|---|
| operational_seed | 182 |
| waste | 23 |
| water | 14 |
| energy | 9 |
| social | 8 |
| emissions | 7 |
| governance | 3 |
| environmental | 3 |

**By unit_family:**

| unit_family | count |
|---|---|
| percentage | 91 |
| count | 57 |
| weight | 29 |
| ratio | 17 |
| monetary | 16 |
| volume | 11 |
| energy | 7 |
| time / duration | 10 |
| emissions | 2 |
| intensity / per_unit / rate / other | 7 |

---

### Metric:Provisional `(1,456 nodes)`

Auto-generated nodes for raw metric names that didn't match any canonical. Stored for registry gap analysis.

| Property | Type | Example |
|---|---|---|
| `provisional_id` | string | `nestle_india__p_training_coverage_ethics_employees` |
| `raw_name` | string | `"% of training coverage - ethics - employees"` |
| `owner_company` | string | `nestle_india` |

---

### Chunk `(741 nodes)`

Text passages extracted from PDFs. Source of all Observations.

| Property | Type | Description |
|---|---|---|
| `chunk_id` | string | Unique, e.g. `nestle_india_p209_1` |
| `page` | integer | PDF page number |
| `text` | string | Full chunk text (~600 tokens) |
| `char_count` | integer | Character length |
| `token_count` | integer | Estimated token count |

Chunks are linked in document order: `(Chunk)-[:NEXT]->(Chunk)` (737 edges — most chunks have a successor).

---

### Section `(470 nodes)`

Groups chunks into logical document sections.

| Property | Type | Description |
|---|---|---|
| `section_id` | string | e.g. `nestle_india_page_209` |
| `title` | string | Section name from PDF (e.g. `BRSR`, `Board's Report`) |

---

### Evidence `(2,431 nodes)`

One per Observation. Stores the exact PDF sentence that supports the extracted fact.

| Property | Type | Description |
|---|---|---|
| `evidence_id` | string | Unique identifier |
| `text` | string | Exact source sentence from the PDF |

> **Important:** The property is `ev.text` — not `ev.evidence_text` (that property does not exist).

Each Evidence node also connects back to its source Chunk: `(Evidence)-[:FOUND_IN]->(Chunk)`.

---

### ConfidenceRecord `(2,431 nodes)`

One per Observation. Stores normalisation quality metadata.

| Property | Type | Values |
|---|---|---|
| `conf_id` | string | Unique identifier |
| `normalization_status` | string | `normalized` / `partial` / `new_metric` |
| `normalisation_confidence` | string | `exact` / `inferred` / `needs_context` / `failed` |
| `final_confidence` | float | 0.0–1.0 composite score |

---

### MetricCategory `(51 nodes)`

A 3-level taxonomy for grouping canonical metrics.

| Property | Type | Description |
|---|---|---|
| `category_id` | string | Slug, e.g. `water_consumption` |
| `name` | string | Display name, e.g. `Water Consumption` |
| `level` | integer | `0` = root, `1` = mid, `2` = leaf |

**Full hierarchy:**

```
Environmental (0)
├── Emissions (1)
│   ├── Scope 1 (2)
│   ├── Scope 2 (2)
│   ├── Scope 3 (2)
│   ├── GHG Intensity (2)
│   └── Air Emissions (2)
├── Energy (1)
│   ├── Energy Consumption (2)
│   ├── Energy Intensity (2)
│   ├── Renewable Energy (2)
│   └── Energy Conservation (2)
├── Water (1)
│   ├── Water Withdrawal (2)
│   ├── Water Consumption (2)
│   ├── Water Discharge (2)
│   ├── Water Recharge (2)
│   └── Water Conservation (2)
├── Waste (1)
│   ├── Waste Generation (2)
│   ├── Waste Recovery (2)
│   ├── Waste Disposal (2)
│   ├── Waste Intensity (2)
│   └── Plastic Waste (2)
└── Packaging (1)
    ├── Plastic Packaging (2)
    ├── Recyclable Packaging (2)
    └── EPR (2)

Social (0)
├── Workforce (1)
│   ├── Headcount (2)
│   ├── Safety (2)
│   ├── Training (2)
│   └── Diversity (2)
└── Community (1)
    ├── CSR (2)
    └── Complaints (2)

Governance (0)
└── Compliance (1)
    ├── BRSR (2)
    └── EPR Compliance (2)

Operational (0)
├── Financial (1)
│   ├── Revenue (2)
│   ├── Profitability (2)
│   └── Market Share (2)
└── Supply Chain (1)
    ├── Distribution (2)
    └── Logistics (2)

Financial Backbone (0)
New Metric (0)  ← catches unclassified provisional metrics
```

---

## Relationships

| Type | From → To | Count | Purpose |
|---|---|---|---|
| `REPORTED_BY` | Observation → Company | 2,431 | Which company reported this fact |
| `IN_PERIOD` | Observation → Period | 2,431 | Which fiscal year |
| `EXTRACTED_FROM` | Observation → Chunk | 2,431 | Source text passage |
| `SUPPORTED_BY` | Observation → Evidence | 2,431 | Exact supporting sentence |
| `HAS_CONFIDENCE` | Observation → ConfidenceRecord | 2,431 | Normalisation quality metadata |
| `FOUND_IN` | Evidence → Chunk | 2,431 | Evidence back-link to source chunk |
| `OF_METRIC` | Observation → Metric | 2,401 | Canonical or Provisional metric node |
| `BELONGS_TO` | Metric:Canonical → MetricCategory | 1,705 | Category taxonomy |
| `IN_SECTION` | Chunk → Section | 741 | Document structure grouping |
| `NEXT` | Chunk → Chunk | 737 | Sequential chunk order within document |
| `IN_DOCUMENT` | Section → Document | 470 | Section belongs to document |
| `SUBCATEGORY_OF` | MetricCategory → MetricCategory | 46 | Category hierarchy |
| `FILED` | Company → Document | 4 | Company–report link |
| `NEXT_YEAR` | Period → Period | 1 | FY2024 → FY2025 |

> `OF_METRIC` has 2,401 edges rather than 2,431 because 30 Observations lack a metric linkage (data quality gap from ingestion).

---

## Full Subgraph: One Observation

Every Observation is the hub of a 6-spoke star. This is the minimal subgraph you traverse for a fully provenance-traced fact:

```
                  ┌─────────────┐
                  │   Company   │  company_id, name
                  └──────┬──────┘
                         │ REPORTED_BY
                         │
┌──────────┐   OF_METRIC │          IN_PERIOD ┌────────┐
│  Metric  │◄────────────┤                    │ Period │
│ Canonical│             │           ─────────┤ fiscal │
│Provisional             │          │          └────────┘
└──────────┘             ▼          │
                  ┌─────────────┐   │
    EXTRACTED_FROM│ Observation │───┘
         ┌────────┤   obs_id    ├────────────┐ HAS_CONFIDENCE
         │        │normalised_  │            │
         │        │value, unit  │            ▼
         ▼        │status, page │    ┌───────────────────┐
  ┌───────────┐   └──────┬──────┘    │  ConfidenceRecord │
  │   Chunk   │          │           │  final_confidence │
  │ page,text │          │ SUPPORTED_BY  normalisation_  │
  └───────────┘          ▼           │  confidence       │
                  ┌─────────────┐    └───────────────────┘
                  │  Evidence   │
                  │  text (raw  │
                  │  PDF quote) │
                  └──────┬──────┘
                         │ FOUND_IN
                         ▼
                  ┌─────────────┐
                  │    Chunk    │
                  └─────────────┘
```

---

## Common Query Patterns

### Cross-company comparison for one metric + year

```cypher
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric {canonical_id: 'scope_1_emissions'}),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period {fiscal_year: 'FY2024'})
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH c.name AS company, max(o.normalised_value) AS value
RETURN company, value, 'tCO2e' AS unit
ORDER BY value DESC
```

> `max(o.normalised_value)` within the `WITH` clause deduplicates comparative rows — BRSR tables report both current and prior year; without this, a company can appear multiple times.


### Full provenance trace for one fact

```cypher
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period),
      (o)-[:SUPPORTED_BY]->(ev:Evidence),
      (o)-[:EXTRACTED_FROM]->(ch:Chunk),
      (o)-[:HAS_CONFIDENCE]->(cr:ConfidenceRecord)
WHERE m.canonical_id = 'water_consumption_absolute'
  AND c.company_id = 'nestle_india'
  AND p.fiscal_year = 'FY2024'
  AND o.normalised_value IS NOT NULL
WITH o, ev, ch, cr
ORDER BY o.normalised_value DESC
LIMIT 1
RETURN o.normalised_value    AS value,
       o.normalised_unit_symbol AS unit,
       o.page                AS page,
       ev.text               AS source_sentence,
       ch.chunk_id           AS chunk,
       cr.final_confidence   AS confidence,
       cr.normalisation_confidence AS unit_confidence
```

### All observations linked to a canonical, any company, any year

```cypher
MATCH (o:Observation)-[:OF_METRIC]->(m:Metric {canonical_id: 'employee_headcount'}),
      (o)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE o.normalization_status IN ['normalized', 'partial']
  AND o.normalised_value IS NOT NULL
WITH c.name AS company, p.fiscal_year AS year, max(o.normalised_value) AS value
RETURN company, year, value
ORDER BY company, year
```

### Navigate from chunk to all facts extracted from it

```cypher
MATCH (ch:Chunk {chunk_id: 'nestle_india_p209_1'})<-[:EXTRACTED_FROM]-(o:Observation)
RETURN o.raw_name, o.normalised_value, o.normalised_unit_symbol, o.normalization_status
```

### Find all provisional metrics for a company (registry gap candidates)

```cypher
MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id: 'nestle_india'}),
      (o)-[:OF_METRIC]->(m:Metric:Provisional)
RETURN m.raw_name, count(o) AS occurrences
ORDER BY occurrences DESC
LIMIT 20
```

---
