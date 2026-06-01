from __future__ import annotations

import argparse
import csv
import importlib
from pathlib import Path
from typing import Any

from apply_gcpl_nestle_registry_round import _base_registry_ids, _dedupe_by_id, _load_list, _seed_registry_by_id
from apply_reviewed_registry_changes import _load_json, _write_json, rerun_new_metric_subset, verify_rebuilt_registry


INTENSITY_LABEL_UPDATES = [
    {
        "canonical_id": "energy_intensity_physical_output",
        "metric_subject": "energy",
        "metric_role": "intensity",
        "flow_direction": "ratio",
        "denominator_type": "production",
        "allowed_unit_families": ["ratio", "energy", "per_unit"],
        "comparable": True,
        "comparability_notes": "Comparable when denominator unit is consistent.",
        "external_refs": [
            {"standard": "GRI", "id": "GRI 302-3", "label": "Energy intensity"},
            {
                "standard": "BRSR",
                "id": "Principle 6 Essential",
                "label": "Energy intensity in terms of physical output",
            },
        ],
        "recurrence": ["Tata", "Nestle", "ITC"],
        "review_status": "approved",
    },
    {
        "canonical_id": "waste_intensity_physical_output",
        "metric_subject": "waste",
        "metric_role": "intensity",
        "flow_direction": "ratio",
        "denominator_type": "production",
        "allowed_unit_families": ["ratio", "weight", "per_unit"],
        "comparable": True,
        "comparability_notes": "Comparable when denominator unit is consistent.",
        "external_refs": [
            {"standard": "GRI", "id": "GRI 306-3/306-4", "label": "Waste intensity"},
            {
                "standard": "BRSR",
                "id": "Principle 6 Essential",
                "label": "Waste intensity in terms of physical output",
            },
        ],
        "recurrence": ["Tata", "Nestle", "ITC"],
        "review_status": "approved",
    },
]

APPROVED_ALIASES = {
    "energy_intensity_physical_output": [
        "energy intensity in terms of physical output",
        "specific energy consumption reduction",
    ],
    "waste_intensity_physical_output": [
        "waste intensity in terms of physical output",
        "Waste intensity in terms of physical output",
        "Waste intensity",
    ],
    "water_saved_absolute": ["water savings"],
    "water_consumption_absolute": ["Total volume of water consumption"],
}

APPROVED_ALIAS_METADATA = {
    "water_saved_absolute": {"recurrence": ["GCPL", "Nestle", "ITC"]},
    "water_consumption_absolute": {"recurrence": ["GCPL", "Nestle", "ITC"]},
}

REVIEWED_TRIAGE_ACTIONS = {
    "CSR_PROVISIONAL": "true_provisional",
    "EXTRACTION_ARTIFACT": "do_not_promote",
    "TARGET_NOT_MEASUREMENT": "do_not_promote",
    "TRUE_PROVISIONAL": "true_provisional",
}


def _write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _clean_new_canonical(raw: dict[str, Any]) -> dict[str, Any]:
    entry = dict(raw)
    entry.pop("verdict", None)
    entry["review_status"] = "approved"
    return entry


def _raw_seed_entry(canonical_id: str) -> dict[str, Any]:
    import metric_registry_seed

    for entry in metric_registry_seed._build_registry():
        if str(entry.get("canonical_id") or "") == canonical_id:
            return dict(entry)
    return {}


def _merge_aliases(base_aliases: list[Any], new_aliases: list[Any]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for alias in [*base_aliases, *new_aliases]:
        alias_text = str(alias or "").strip()
        key = alias_text.lower()
        if alias_text and key not in seen:
            merged.append(alias_text)
            seen.add(key)
    return merged


def _add_alias_overrides(label_updates: list[dict[str, Any]], seed_by_id: dict[str, dict[str, Any]]) -> int:
    added = 0
    for canonical_id, aliases_to_add in APPROVED_ALIASES.items():
        seed_entry = dict(seed_by_id.get(canonical_id, {}))
        aliases = list(seed_entry.get("aliases") or [])
        seen = {str(alias).strip().lower() for alias in aliases}
        for alias in aliases_to_add:
            key = alias.strip().lower()
            if key and key not in seen:
                aliases.append(alias)
                seen.add(key)
                added += 1
        label_updates.append(
            {
                "canonical_id": canonical_id,
                "aliases": aliases,
                **APPROVED_ALIAS_METADATA.get(canonical_id, {}),
            }
        )
    return added


def apply_registry_round(draft_path: str | Path) -> dict[str, Any]:
    draft_entries = _load_list(draft_path)
    seed_by_id = _seed_registry_by_id()
    base_ids = _base_registry_ids()
    existing_overrides = _load_list("registry_semantic_overrides.json") if Path("registry_semantic_overrides.json").exists() else []
    existing_additions = _load_list("registry_additions_approved.json") if Path("registry_additions_approved.json").exists() else []

    warnings: list[str] = []
    label_updates: list[dict[str, Any]] = []
    new_additions: list[dict[str, Any]] = []
    existing_enrichments = 0
    current_addition_ids = {str(entry.get("canonical_id") or "") for entry in existing_additions}

    for update in INTENSITY_LABEL_UPDATES:
        canonical_id = str(update.get("canonical_id") or "")
        if canonical_id not in seed_by_id and canonical_id not in base_ids and canonical_id not in current_addition_ids:
            warnings.append(f"label update skipped, canonical not found: {canonical_id}")
            continue
        label_updates.append(dict(update))

    alias_count = _add_alias_overrides(label_updates, seed_by_id)

    for raw in draft_entries:
        canonical_id = str(raw.get("canonical_id") or "").strip()
        if not canonical_id:
            warnings.append("new canonical skipped, missing canonical_id")
            continue
        if canonical_id in base_ids and canonical_id not in current_addition_ids:
            enrichment = _clean_new_canonical(raw)
            enrichment["aliases"] = _merge_aliases(
                list(_raw_seed_entry(canonical_id).get("aliases") or []),
                list(raw.get("aliases") or []),
            )
            existing_enrichments += 1
            label_updates.append(enrichment)
            warnings.append(f"existing canonical enriched instead of duplicated: {canonical_id}")
            continue
        if canonical_id in current_addition_ids:
            warnings.append(f"new canonical collision skipped: {canonical_id}")
            continue
        new_additions.append(_clean_new_canonical(raw))
        current_addition_ids.add(canonical_id)

    merged_overrides = _dedupe_by_id(existing_overrides + label_updates)
    merged_additions = _dedupe_by_id(existing_additions + new_additions)
    _write_json("registry_semantic_overrides.json", merged_overrides)
    _write_json("registry_additions_approved.json", merged_additions)

    alias_path = Path("registry_aliases.json")
    aliases = _load_json(alias_path) if alias_path.exists() else {}
    for canonical_id, alias_list in APPROVED_ALIASES.items():
        for alias in alias_list:
            aliases[alias] = canonical_id
    _write_json(alias_path, aliases)

    return {
        "label_updates": len(INTENSITY_LABEL_UPDATES),
        "alias_strings_added": alias_count,
        "new_additions": len(new_additions),
        "existing_enrichments": existing_enrichments,
        "warnings": warnings,
    }


def apply_triage_to_audit(
    *,
    triage_path: str | Path,
    audit_path: str | Path,
    output_path: str | Path,
) -> dict[str, int]:
    triage_rows = _read_csv(triage_path)
    verdict_by_fact_id = {
        str(row.get("fact_id") or "").strip(): str(row.get("verdict") or "").strip().upper()
        for row in triage_rows
    }
    audit_rows = _read_csv(audit_path)
    counts: dict[str, int] = {}
    updated = 0
    for row in audit_rows:
        verdict = verdict_by_fact_id.get(str(row.get("fact_id") or "").strip())
        action = REVIEWED_TRIAGE_ACTIONS.get(verdict or "")
        if not action:
            continue
        row["recommended_action"] = action
        row["review_status"] = "reviewed"
        counts[verdict or ""] = counts.get(verdict or "", 0) + 1
        updated += 1
    _write_csv(output_path, audit_rows, list(audit_rows[0].keys()) if audit_rows else [])
    counts["updated_rows"] = updated
    return counts


def _print_rerun(label: str, summary: dict[str, Any]) -> None:
    after = summary["after_counts"]
    other = sum(count for decision, count in after.items() if decision not in {"normalized", "partial", "new_metric"})
    print(f"{label}: before {summary['before_new_metric']} new_metric")
    print(
        "     after:  "
        f"{after.get('normalized', 0)} normalized, "
        f"{after.get('partial', 0)} partial, "
        f"{after.get('new_metric', 0)} new_metric, "
        f"{other} other"
    )
    print(
        "     delta:  "
        f"{summary['resolved_by_new_canonical']} resolved by new canonicals, "
        f"{summary['resolved_by_existing_canonical']} resolved by labels/aliases/existing canonicals"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the reviewed ITC registry round and rerun ITC new_metric facts.")
    parser.add_argument("--draft", default="itc_registry_additions_draft.json")
    parser.add_argument("--triage", default="itc_smc_triage.csv")
    parser.add_argument("--audit", default="itc_new_metric_distance_audit.csv")
    args = parser.parse_args()

    apply_summary = apply_registry_round(args.draft)
    triage_summary = apply_triage_to_audit(
        triage_path=args.triage,
        audit_path=args.audit,
        output_path="itc_new_metric_distance_audit_applied.csv",
    )
    itc_summary = rerun_new_metric_subset(
        pass2_path="itc_pass2.json",
        metadata_path="itc_fast_metadata.json",
        output_csv="itc_new_metric_rerun_v2.csv",
    )

    registry_check = verify_rebuilt_registry()
    import metric_registry_seed

    importlib.reload(metric_registry_seed)
    registry_check["recurrence_present"] = any("recurrence" in entry for entry in metric_registry_seed.REGISTRY)

    additions = _load_list("registry_additions_approved.json")
    approved_additions = sum(1 for entry in additions if entry.get("review_status") == "approved")

    print("ITC registry round applied")
    print(f"- semantic labels activated: {apply_summary['label_updates']}")
    print(f"- existing canonicals enriched: {apply_summary['existing_enrichments']}")
    print(f"- approved alias strings applied: {apply_summary['alias_strings_added']}")
    print(f"- new canonicals approved: {apply_summary['new_additions']}")
    print(f"- approved supplemental canonicals total: {approved_additions}")
    print(f"- audit triage applied: {triage_summary}")
    for warning in apply_summary["warnings"]:
        print(f"WARNING: {warning}")
    _print_rerun("ITC", itc_summary)
    print(f"ITC rerun output: {Path('itc_new_metric_rerun_v2.csv').resolve()}")
    print(f"ITC applied audit output: {Path('itc_new_metric_distance_audit_applied.csv').resolve()}")
    print(f"rebuilt registry metadata check: {registry_check}")


if __name__ == "__main__":
    main()
