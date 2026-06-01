from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any

from apply_reviewed_registry_changes import (
    _load_json,
    _write_json,
    rerun_new_metric_subset,
    verify_rebuilt_registry,
)


APPROVED_ALIAS = "total waste generated"
APPROVED_ALIAS_CANONICAL = "waste_generated"


def _load_list(path: str | Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON list")
    return payload


def _dedupe_by_id(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in entries:
        canonical_id = str(entry.get("canonical_id") or "").strip()
        if not canonical_id:
            continue
        if canonical_id not in merged:
            order.append(canonical_id)
            merged[canonical_id] = {}
        merged[canonical_id].update(entry)
    return [merged[canonical_id] for canonical_id in order]


def _seed_registry_by_id() -> dict[str, dict[str, Any]]:
    import metric_registry_seed

    importlib.reload(metric_registry_seed)
    return {
        str(entry.get("canonical_id") or ""): dict(entry)
        for entry in metric_registry_seed.REGISTRY
        if entry.get("canonical_id")
    }


def _base_registry_ids() -> set[str]:
    ids: set[str] = set()
    if Path("consumer_master_registry_v1.json").exists():
        ids.update(str(entry.get("canonical_id") or "") for entry in _load_list("consumer_master_registry_v1.json"))
    import metric_registry_seed

    for entry in metric_registry_seed._build_registry():
        ids.add(str(entry.get("canonical_id") or ""))
    return {item for item in ids if item}


def _clean_existing_label_entry(raw: dict[str, Any]) -> dict[str, Any]:
    existing_id = str(raw.get("existing_id") or "").strip()
    labels = dict(raw.get("semantic_labels") or {})
    entry = {"canonical_id": existing_id, **labels}
    if raw.get("external_refs"):
        entry["external_refs"] = raw["external_refs"]
    if raw.get("recurrence"):
        entry["recurrence"] = raw["recurrence"]
    entry["review_status"] = "approved"
    return entry


def _clean_new_canonical(raw: dict[str, Any]) -> dict[str, Any]:
    entry = {
        key: value
        for key, value in raw.items()
        if key not in {"verdict", "existing_id", "action", "semantic_labels"}
    }
    entry["review_status"] = "approved"
    return entry


def apply_registry_round(draft_path: str | Path) -> dict[str, Any]:
    draft_entries = _load_list(draft_path)
    seed_by_id = _seed_registry_by_id()
    base_ids = _base_registry_ids()

    existing_overrides = _load_list("registry_semantic_overrides.json") if Path("registry_semantic_overrides.json").exists() else []
    existing_additions = _load_list("registry_additions_approved.json") if Path("registry_additions_approved.json").exists() else []

    warnings: list[str] = []
    label_updates: list[dict[str, Any]] = []
    new_additions: list[dict[str, Any]] = []
    current_addition_ids = {str(entry.get("canonical_id") or "") for entry in existing_additions}

    for raw in draft_entries:
        if str(raw.get("verdict") or "").strip().upper() == "LABEL_EXISTING_CANONICAL":
            existing_id = str(raw.get("existing_id") or "").strip()
            if existing_id not in seed_by_id and existing_id not in base_ids:
                warnings.append(f"existing canonical label skipped, not found: {existing_id}")
                continue
            label_updates.append(_clean_existing_label_entry(raw))
            continue

        canonical_id = str(raw.get("canonical_id") or "").strip()
        if not canonical_id:
            warnings.append("new canonical skipped, missing canonical_id")
            continue
        if canonical_id in base_ids or canonical_id in current_addition_ids:
            warnings.append(f"new canonical collision skipped: {canonical_id}")
            continue
        new_additions.append(_clean_new_canonical(raw))
        current_addition_ids.add(canonical_id)

    # Approved alias as a supplemental override, preserving all existing aliases.
    waste_entry = dict(seed_by_id.get(APPROVED_ALIAS_CANONICAL, {}))
    waste_aliases = list(waste_entry.get("aliases") or [])
    alias_seen = {str(alias).lower().strip() for alias in waste_aliases}
    for alias in (APPROVED_ALIAS, "Total Waste generated"):
        if alias.lower().strip() not in alias_seen:
            waste_aliases.append(alias)
            alias_seen.add(alias.lower().strip())
    label_updates.append({"canonical_id": APPROVED_ALIAS_CANONICAL, "aliases": waste_aliases})

    merged_overrides = _dedupe_by_id(existing_overrides + label_updates)
    merged_additions = _dedupe_by_id(existing_additions + new_additions)
    _write_json("registry_semantic_overrides.json", merged_overrides)
    _write_json("registry_additions_approved.json", merged_additions)

    # Also keep the explicit alias lookup in sync for exact alias matching.
    alias_path = Path("registry_aliases.json")
    aliases = _load_json(alias_path) if alias_path.exists() else {}
    aliases[APPROVED_ALIAS] = APPROVED_ALIAS_CANONICAL
    aliases["Total Waste generated"] = APPROVED_ALIAS_CANONICAL
    _write_json(alias_path, aliases)

    return {
        "label_updates": len(label_updates) - 1,
        "new_additions": len(new_additions),
        "warnings": warnings,
    }


def _print_rerun(label: str, summary: dict[str, Any]) -> None:
    after = summary["after_counts"]
    other = sum(count for decision, count in after.items() if decision not in {"normalized", "partial", "new_metric"})
    print(f"{label}: before {summary['before_new_metric']} new_metric")
    print(
        "       after:  "
        f"{after.get('normalized', 0)} normalized, "
        f"{after.get('partial', 0)} partial, "
        f"{after.get('new_metric', 0)} new_metric, "
        f"{other} other"
    )
    print(
        "       delta:  "
        f"{summary['resolved_by_new_canonical']} resolved by new canonicals, "
        f"{summary['resolved_by_existing_canonical']} resolved by label corrections/existing canonicals"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply GCPL/Nestle registry additions and rerun new_metric subsets.")
    parser.add_argument("--draft", default="gcpl_nestle_registry_additions_draft.json")
    args = parser.parse_args()

    apply_summary = apply_registry_round(args.draft)
    gcpl_summary = rerun_new_metric_subset(
        pass2_path="gcpl_pass2.json",
        metadata_path="gcpl_fast_metadata.json",
        output_csv="gcpl_new_metric_rerun_v2.csv",
    )
    nestle_summary = rerun_new_metric_subset(
        pass2_path="nestle_india_pass2.json",
        metadata_path="nestle_india_fast_metadata.json",
        output_csv="nestle_new_metric_rerun_v2.csv",
    )
    registry_check = verify_rebuilt_registry()
    import metric_registry_seed

    importlib.reload(metric_registry_seed)
    entries = metric_registry_seed.REGISTRY
    registry_check["recurrence_present"] = any("recurrence" in entry for entry in entries)

    print("GCPL/Nestle registry round applied")
    print(f"- existing canonicals labelled: {apply_summary['label_updates']}")
    print(f"- new canonicals approved: {apply_summary['new_additions']}")
    print("- approved aliases applied: total waste generated -> waste_generated")
    for warning in apply_summary["warnings"]:
        print(f"WARNING: {warning}")
    _print_rerun("GCPL", gcpl_summary)
    _print_rerun("Nestle", nestle_summary)
    print(f"GCPL rerun output: {Path('gcpl_new_metric_rerun_v2.csv').resolve()}")
    print(f"Nestle rerun output: {Path('nestle_new_metric_rerun_v2.csv').resolve()}")
    print(f"rebuilt registry metadata check: {registry_check}")


if __name__ == "__main__":
    main()
