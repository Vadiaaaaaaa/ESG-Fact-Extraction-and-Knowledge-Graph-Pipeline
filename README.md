# ESG Knowledge Graph

An end-to-end pipeline that extracts ESG metrics from corporate annual reports and loads them into a Neo4j knowledge graph for cross-company, cross-year analysis.

## What This Project Does

Takes PDF annual reports, runs a two-pass LLM extraction pipeline, normalises raw metrics against a canonical registry, audits outliers, and loads structured observations into Neo4j — enabling graph queries like "compare Scope 1 emissions across all companies FY2023-FY2025."

## Quick Start

### 1. Install dependencies

```bash
pip install neo4j openai pymupdf streamlit httpx pandas python-dotenv numpy
```

### 2. Configure Neo4j

Copy the example config and fill in your credentials:

```bash
cp config/pipeline_config.json.example pipeline_config.json
# edit pipeline_config.json: set neo4j_pass, neo4j_uri, etc.
```

### 3. Run the pipeline

```bash
python pipeline/run_pipeline.py \
  --pdf /path/to/annual_report.pdf \
  --company nestle_india \
  --company-name "Nestlé India Limited" \
  --year 2024
```

Use `--dry-run` to preview what would run without executing. Use `--pass1-only` or `--pass2-only` to run individual stages.

## Directory Structure

```
esg-knowledge-graph/
├── pipeline/          # Core extraction and normalisation scripts
├── registry/          # Canonical metric registry (JSON + seed script)
├── graph/             # Neo4j loaders and query interface
├── audit/             # Outlier detection, dedup, review memory
├── tests/             # Pytest suite
├── config/            # Config template (credentials stripped)
├── dimension_model.md # Metric dimension taxonomy
├── ARCHITECTURE.md    # Neo4j schema and system design
└── workspace_test_outputs/  # Pipeline outputs (gitignored)
```

## Pipeline Stages

| Stage | Script | Description |
|-------|--------|-------------|
| 1. PDF Ingest | `pipeline/fast_pdf_text_ingest.py` | Page selection, chunking with section metadata |
| 2. Coverage Audit | `pipeline/audit_selected_pages.py` | Flags high-signal pages missed by selector |
| 3. Pass 1 Extraction | `pipeline/extractor.py` | LLM extraction of raw facts from chunks |
| 4. Pass 2 Normalisation | `pipeline/normalizer.py` | Maps raw metrics to canonical registry entries |
| 5. Distance Audit | `audit/new_metric_distance_audit.py` | Flags `new_metric` facts that are close to canonicals |
| 6. KG Load | `pipeline/run_pipeline.py` (embedded) | Loads observations into Neo4j |

## Companies Currently in Graph

| Company | Years |
|---------|-------|
| Nestlé India | FY2021, FY2022, FY2024 |
| Tata Consumer Products | FY2024 |
| GCPL (Godrej Consumer Products) | FY2023 |
| ITC Limited | FY2025 |
