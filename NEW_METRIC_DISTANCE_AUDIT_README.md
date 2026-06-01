# New Metric Distance Audit

This workflow audits `new_metric` facts. It does not mint canonicals and does not apply aliases.

## Core Rule

`new_metric` means unresolved, not new canonical.

The audit compares each unresolved fact to the nearest existing canonicals and emits a review table. Every row has `review_status=pending`.

## Semantic Gate

The gate is implemented in `semantic_registry.py`.

Hard-gated fields:

- `metric_subject`
- `metric_role`
- derived `flow_direction`
- `denominator_type`
- `unit_family`

`impact_polarity` is metadata only and is not used by the alias gate.

`flow_direction` is derived from `metric_role`; do not store it on registry entries.

Role matching is exact only. A role mismatch always blocks alias eligibility.

## Run Tests

```powershell
python -m pytest test_semantic_alias_gate.py
```

If `pytest` is unavailable, the module can still be imported, but install or run with the local test runner before approving alias changes.

## Run The Tata Audit

```powershell
python new_metric_distance_audit.py --pass2 tata_consumer_pass2.json --output tata_consumer_new_metric_distance_audit.csv
```

The output contains:

- raw fact fields
- nearest 3 canonical candidates
- score components
- unit/role/denominator compatibility
- structured block reasons
- advisory `why_not_top_candidate`
- `recommended_action`
- `review_status=pending`

## Interpreting Actions

- `alias_candidate`: the fact and canonical passed the semantic gate. Still requires human approval.
- `standard_mapping_candidate`: likely belongs to BRSR/GRI/SASB or another standard-backed disclosure family.
- `true_provisional`: keep as a typed provisional; do not add an alias.
- `do_not_promote`: likely noise, poor fit, or not worth registry expansion.

## Re-normalize Only `new_metric` Facts

The current normalizer entry point is:

```powershell
python normalizer.py --input PASS1.json --output PASS2.json
```

It does not yet expose a first-class CLI for re-normalizing only the `new_metric` subset. The extension point is `_resolve_batch_by_fuzzy_match()` in `normalizer.py`: load the previous Pass 2, select facts where `normalization_decision == "new_metric"`, rerun those facts against the updated registry, and merge them back by `fact_id`.

Do not rerun Pass 1 for registry-only changes.

## Draft Canonical Semantic Labels

Before alias candidates can pass the gate, existing canonicals need reviewed semantic labels. Generate an inert review sheet:

```powershell
python draft_canonical_semantic_labels.py --pass2 tata_consumer_pass2.json --min-usage 1 --output tata_consumer_canonical_semantic_label_drafts.csv
```

This does not edit the registry. It only drafts labels for human review. Approved labels can later be copied into registry entries as `metric_subject`, `metric_role`, and `denominator_type`.
