# Architecture

## Neo4j Schema

### Node Labels

| Label | Key Property | Description |
|-------|-------------|-------------|
| `Company` | `company_id` | e.g. `nestle_india`, `tata_consumer` |
| `Document` | `doc_id` | e.g. `nestle_india_fy2024` |
| `Section` | `section_id` | Named section within a document |
| `Chunk` | `chunk_id` | ~180-word passage with page reference |
| `Observation` | `obs_id` | A single extracted ESG data point |
| `Metric` | `canonical_id` | Registry canonical (or `:Provisional` for unknowns) |
| `Period` | `fiscal_year` | e.g. `FY2024`, linked by `NEXT_YEAR` chain |
| `Unit` | `symbol` | e.g. `tCO2e`, `%`, `kWh` |
| `Evidence` | `evidence_id` | Source sentence from the PDF |
| `ConfidenceRecord` | `conf_id` | Normalisation status + confidence score |

### Key Relationships

```
(Company)-[:FILED]->(Document)
(Document)<-[:IN_DOCUMENT]-(Section)
(Section)<-[:IN_SECTION]-(Chunk)
(Observation)-[:EXTRACTED_FROM]->(Chunk)
(Observation)-[:REPORTED_BY]->(Company)
(Observation)-[:IN_PERIOD]->(Period)
(Observation)-[:OF_METRIC]->(Metric)
(Observation)-[:MEASURED_IN]->(Unit)
(Observation)-[:SUPPORTED_BY]->(Evidence)
(Observation)-[:HAS_CONFIDENCE]->(ConfidenceRecord)
(Evidence)-[:FOUND_IN]->(Chunk)
(Period)-[:NEXT_YEAR]->(Period)
```

## Registry System

The canonical metric registry consists of two JSON files that are merged at runtime:

- `registry/consumer_master_registry_v1.json` — base 18 BRSR canonicals
- `registry/registry_additions_approved.json` — approved extensions

**Combined total: 57 canonical metrics** (as of June 2024).

Supporting files:
- `registry/registry_aliases.json` — surface-form aliases per canonical
- `registry/registry_semantic_overrides.json` — manual semantic overrides for tiebreaking
- `registry/metric_registry_seed.py` — builds `REGISTRY` dict and `build_alias_index()`

## Normalisation Flow (Pass 2)

```
raw metric name
      │
      ▼
1. Alias match        ← exact/fuzzy match against registry_aliases.json
      │ no match
      ▼
2. Fuzzy match        ← token-based score against canonical display names
      │ score < threshold
      ▼
3. Semantic gate      ← LLM-assisted subject/role/unit-family check
      │ conflict detected
      ▼
4. Tiebreaker         ← margin check + semantic_registry overrides
      │ still ambiguous
      ▼
5. new_metric         ← assigned provisional canonical, flagged for review
```

Outcomes stored in `normalization_decision`:
- `normalized` — high-confidence canonical match
- `partial` — plausible match, lower confidence
- `new_metric` — no suitable canonical found
- `quarantine` — implausible value (e.g. Scope 3 < 1% of Scope 1)
- `drop` / `out_of_scope_financial` — filtered before load

## Pass 2 Decision Logic

1. Load Pass 1 JSON (raw facts from LLM extractor).
2. For each fact, run alias index lookup — O(1) hash match.
3. If no alias hit, compute `compute_match_score()` against all 57 canonicals (gold_set.py).
4. Top candidates enter `semantic_alias_gate()` — checks subject/role compatibility.
5. If top-2 scores are within `SCORE_MARGIN`, run `_semantic_tiebreaker_conflict()`.
6. Review memory (`audit/review_memory.json`) can force-accept or force-reject specific raw names.
7. Facts surviving all gates get `normalization_decision = "normalized"` or `"partial"`.
8. Remaining facts become `new_metric` and are written to a provisional review CSV.
