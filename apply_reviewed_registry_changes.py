from __future__ import annotations

import argparse
import csv
import importlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


SEMANTIC_OVERRIDE_FIELDS = [
    "metric_subject",
    "metric_role",
    "flow_direction",
    "denominator_type",
    "impact_polarity",
    "comparability_warning",
    "comparability_notes",
]


def _load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: str | Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _combined_registry_ids() -> set[str]:
    ids: set[str] = set()
    for path in ("consumer_master_registry_v1.json",):
        if Path(path).exists():
            for entry in _load_json(path):
                canonical_id = str(entry.get("canonical_id") or "")
                if canonical_id:
                    ids.add(canonical_id)
    import metric_registry_seed

    for entry in metric_registry_seed.REGISTRY:
        canonical_id = str(entry.get("canonical_id") or "")
        if canonical_id:
            ids.add(canonical_id)
    return ids


def apply_semantic_label_reviews(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows = _read_csv(path)
    registry_ids = _combined_registry_ids()
    overrides: list[dict[str, Any]] = []
    warnings: list[str] = []
    for row in rows:
        canonical_id = str(row.get("canonical_id") or "").strip()
        decision = str(row.get("decision") or "").strip().upper()
        if decision not in {"APPROVE", "FIX", "FLAG"}:
            continue
        if canonical_id not in registry_ids:
            warnings.append(f"semantic label skipped, canonical_id not found: {canonical_id}")
            continue
        entry: dict[str, Any] = {"canonical_id": canonical_id}
        entry["metric_subject"] = str(row.get("final_metric_subject") or "").strip() or None
        entry["metric_role"] = str(row.get("final_metric_role") or "").strip() or None
        entry["flow_direction"] = str(row.get("final_flow_direction") or "").strip() or None
        denominator = str(row.get("final_denominator_type") or "").strip()
        entry["denominator_type"] = denominator if denominator else None
        entry["impact_polarity"] = str(row.get("final_impact_polarity") or "").strip() or None
        if decision == "FLAG":
            entry["comparability_warning"] = True
            entry["comparability_notes"] = str(row.get("review_note") or "").strip()
        overrides.append({key: value for key, value in entry.items() if value is not None})
    _write_json("registry_semantic_overrides.json", overrides)
    return overrides, warnings


def apply_registry_additions(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    additions = _load_json(path)
    if not isinstance(additions, list):
        raise ValueError("registry additions file must contain a list")
    registry_ids = _combined_registry_ids()
    approved: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for raw_entry in additions:
        entry = dict(raw_entry)
        canonical_id = str(entry.get("canonical_id") or "").strip()
        if not canonical_id:
            warnings.append("registry addition skipped, missing canonical_id")
            continue
        if canonical_id in registry_ids or canonical_id in seen:
            warnings.append(f"registry addition collision skipped: {canonical_id}")
            continue
        entry["review_status"] = "approved"
        approved.append(entry)
        seen.add(canonical_id)
    _write_json("registry_additions_approved.json", approved)
    return approved, warnings


def apply_smc_triage_to_audit(
    *,
    triage_path: str | Path,
    audit_path: str | Path,
    output_path: str | Path,
) -> tuple[int, int]:
    triage_rows = _read_csv(triage_path)
    artifact_ids = {
        str(row.get("fact_id") or "").strip()
        for row in triage_rows
        if str(row.get("verdict") or "").strip().upper() == "EXTRACTION_ARTIFACT"
    }
    audit_rows = _read_csv(audit_path)
    updated = 0
    for row in audit_rows:
        if str(row.get("fact_id") or "").strip() in artifact_ids:
            row["recommended_action"] = "do_not_promote"
            row["review_status"] = "reviewed"
            updated += 1
    _write_csv(output_path, audit_rows, list(audit_rows[0].keys()) if audit_rows else [])
    return len(artifact_ids), updated


def _load_metadata(path: str | Path | None) -> dict[str, Any]:
    if path and Path(path).exists():
        return _load_json(path)
    return {
        "currency": "INR",
        "filing_year": 2024,
        "fiscal_year_end_month": "March",
        "company_name": "Tata Consumer Products",
    }


def rerun_new_metric_subset(
    *,
    pass2_path: str | Path,
    metadata_path: str | Path | None,
    output_csv: str | Path,
) -> dict[str, Any]:
    # Reload modules after supplemental registry files have been written.
    import metric_registry_seed
    import normalizer

    importlib.reload(metric_registry_seed)
    importlib.reload(normalizer)

    facts = _load_json(pass2_path)
    if not isinstance(facts, list):
        raise ValueError("Pass 2 output must be a list")
    new_metric_facts = [
        fact
        for fact in facts
        if str(fact.get("normalization_decision") or "") == "new_metric"
    ]
    before_count = len(new_metric_facts)
    metadata = _load_metadata(metadata_path)
    registry = normalizer._metric_registry_with_seed()
    registry_lookup = {
        str(metric.get("canonical_id")): metric
        for metric in registry
        if metric.get("canonical_id")
    }
    alias_resolved_by_id, alias_unresolved = normalizer._resolve_batch_by_alias(
        new_metric_facts,
        normalizer._aliases_with_seed(),
        registry_lookup,
        metadata,
    )
    fuzzy_resolved_by_id, unresolved = normalizer._resolve_batch_by_fuzzy_match(
        alias_unresolved,
        registry_lookup,
        metadata,
    )
    resolved_by_id = {**alias_resolved_by_id, **fuzzy_resolved_by_id}
    addition_ids = {
        str(entry.get("canonical_id") or "")
        for entry in _load_json("registry_additions_approved.json")
        if entry.get("canonical_id")
    } if Path("registry_additions_approved.json").exists() else set()
    rows: list[dict[str, Any]] = []
    after_counter: Counter = Counter()
    resolved_by_new_canonical = 0
    resolved_by_existing_canonical = 0
    for old in new_metric_facts:
        fact_id = str(old.get("fact_id") or "")
        new = resolved_by_id.get(fact_id, old)
        after_decision = str(new.get("normalization_decision") or "")
        after_counter[after_decision] += 1
        canonical_id = str(new.get("canonical_id") or new.get("proposed_canonical_id") or "")
        resolved = after_decision in {"normalized", "partial"}
        if resolved and canonical_id in addition_ids:
            resolved_by_new_canonical += 1
        elif resolved:
            resolved_by_existing_canonical += 1
        raw = old.get("raw") if isinstance(old.get("raw"), dict) else {}
        rows.append(
            {
                "fact_id": fact_id,
                "raw_name": raw.get("raw_name") or old.get("metric") or "",
                "metric_core": raw.get("metric_core") or old.get("metric") or "",
                "value": old.get("value") or raw.get("raw_value") or "",
                "unit": old.get("unit") or raw.get("raw_unit") or "",
                "before_decision": old.get("normalization_decision") or "",
                "after_decision": after_decision,
                "after_canonical_id": new.get("canonical_id") or "",
                "after_proposed_canonical_id": new.get("proposed_canonical_id") or "",
                "mapping_confidence": new.get("mapping_confidence") or "",
                "mapping_note": new.get("mapping_note") or "",
                "resolution_source": (
                    "new_canonical"
                    if resolved and canonical_id in addition_ids
                    else "existing_canonical"
                    if resolved
                    else "still_unresolved"
                ),
                "evidence": old.get("evidence") or raw.get("source_sentence") or "",
            }
        )
    fieldnames = [
        "fact_id",
        "raw_name",
        "metric_core",
        "value",
        "unit",
        "before_decision",
        "after_decision",
        "after_canonical_id",
        "after_proposed_canonical_id",
        "mapping_confidence",
        "mapping_note",
        "resolution_source",
        "evidence",
    ]
    _write_csv(output_csv, rows, fieldnames)
    return {
        "before_new_metric": before_count,
        "after_counts": dict(after_counter),
        "unresolved_count": len(unresolved),
        "resolved_by_new_canonical": resolved_by_new_canonical,
        "resolved_by_existing_canonical": resolved_by_existing_canonical,
    }


def verify_rebuilt_registry() -> dict[str, bool]:
    import metric_registry_seed

    importlib.reload(metric_registry_seed)
    entries = metric_registry_seed.REGISTRY
    return {
        "external_refs_present": any("external_refs" in entry for entry in entries),
        "metric_role_present": any("metric_role" in entry for entry in entries),
        "comparable_present": any("comparable" in entry for entry in entries),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply reviewed registry changes and rerun Tata new_metric subset.")
    parser.add_argument("--labels", default="label_drafts_reviewed.csv")
    parser.add_argument("--triage", default="smc_triage_reviewed.csv")
    parser.add_argument("--additions", default="registry_additions_draft.json")
    parser.add_argument("--audit", default="tata_consumer_new_metric_distance_audit.csv")
    parser.add_argument("--audit-output", default="tata_consumer_new_metric_distance_audit_applied.csv")
    parser.add_argument("--pass2", default="tata_consumer_pass2.json")
    parser.add_argument("--metadata", default="tata_consumer_fast_metadata.json")
    parser.add_argument("--rerun-output", default="tata_consumer_new_metric_rerun.csv")
    args = parser.parse_args()

    overrides, override_warnings = apply_semantic_label_reviews(args.labels)
    additions, addition_warnings = apply_registry_additions(args.additions)
    artifact_count, audit_updated = apply_smc_triage_to_audit(
        triage_path=args.triage,
        audit_path=args.audit,
        output_path=args.audit_output,
    )
    rerun_summary = rerun_new_metric_subset(
        pass2_path=args.pass2,
        metadata_path=args.metadata,
        output_csv=args.rerun_output,
    )
    registry_check = verify_rebuilt_registry()

    print("Reviewed registry application")
    print(f"- semantic overrides written: {len(overrides)} -> registry_semantic_overrides.json")
    print(f"- approved additions written: {len(additions)} -> registry_additions_approved.json")
    print(f"- extraction artifact fact_ids in triage: {artifact_count}")
    print(f"- audit rows updated: {audit_updated} -> {args.audit_output}")
    for warning in override_warnings + addition_warnings:
        print(f"WARNING: {warning}")

    after = rerun_summary["after_counts"]
    other = sum(
        count
        for decision, count in after.items()
        if decision not in {"normalized", "partial", "new_metric"}
    )
    print("Before/after new_metric subset")
    print(f"before: {rerun_summary['before_new_metric']} new_metric")
    print(
        "after: "
        f"{after.get('normalized', 0)} normalized, "
        f"{after.get('partial', 0)} partial, "
        f"{after.get('new_metric', 0)} new_metric still unresolved, "
        f"{other} other"
    )
    print(
        "delta: "
        f"{rerun_summary['resolved_by_new_canonical']} resolved by new canonicals, "
        f"{rerun_summary['resolved_by_existing_canonical']} resolved by existing canonicals/labels"
    )
    print(f"subset output: {Path(args.rerun_output).resolve()}")
    print(f"rebuilt registry metadata check: {registry_check}")


if __name__ == "__main__":
    main()
