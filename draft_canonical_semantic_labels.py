from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from new_metric_distance_audit import _load_registry
from semantic_registry import infer_fact_semantics_draft, validate_registry_semantics


FIELDS = [
    "canonical_id",
    "canonical_name",
    "category",
    "unit_family",
    "usage_count",
    "draft_metric_subject",
    "draft_metric_role",
    "draft_flow_direction",
    "draft_denominator_type",
    "draft_impact_polarity",
    "canonical_definition",
    "aliases",
    "review_status",
]


def _load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _facts(path: str | Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, dict):
        facts = payload.get("facts", [])
        return facts if isinstance(facts, list) else []
    return payload if isinstance(payload, list) else []


def _usage_counts(pass2_path: str | Path | None) -> Counter:
    counts: Counter = Counter()
    if not pass2_path:
        return counts
    for fact in _facts(pass2_path):
        canonical_id = str(fact.get("canonical_id") or "")
        if canonical_id:
            counts[canonical_id] += 1
        proposed = str(fact.get("proposed_canonical_id") or "")
        if proposed:
            counts[proposed] += 0
    return counts


def _pseudo_fact(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "metric": str(entry.get("canonical_name") or entry.get("display_name") or entry.get("canonical_id") or ""),
        "metric_definition": str(entry.get("canonical_definition") or entry.get("notes") or ""),
        "evidence": " ".join(str(alias) for alias in entry.get("aliases", [])[:8]),
        "raw": {
            "raw_name": str(entry.get("canonical_name") or entry.get("display_name") or entry.get("canonical_id") or ""),
            "metric_core": str(entry.get("canonical_id") or ""),
            "source_sentence": str(entry.get("canonical_definition") or entry.get("notes") or ""),
        },
    }


def draft_labels(pass2_path: str | Path | None, *, min_usage: int) -> list[dict[str, str]]:
    registry = _load_registry()
    errors = validate_registry_semantics(registry)
    if errors:
        formatted = "; ".join(f"{key}: {value}" for key, value in errors.items())
        raise ValueError(f"Registry semantic validation failed: {formatted}")
    counts = _usage_counts(pass2_path)
    rows = []
    for entry in registry:
        canonical_id = str(entry.get("canonical_id") or "")
        usage = counts.get(canonical_id, 0)
        if pass2_path and usage < min_usage:
            continue
        semantics = infer_fact_semantics_draft(_pseudo_fact(entry))
        rows.append(
            {
                "canonical_id": canonical_id,
                "canonical_name": str(entry.get("canonical_name") or entry.get("display_name") or ""),
                "category": str(entry.get("category") or ""),
                "unit_family": str(entry.get("unit_family") or entry.get("unit") or ""),
                "usage_count": str(usage),
                "draft_metric_subject": semantics.metric_subject or "",
                "draft_metric_role": semantics.metric_role or "",
                "draft_flow_direction": semantics.flow_direction,
                "draft_denominator_type": semantics.denominator_type or "",
                "draft_impact_polarity": semantics.impact_polarity or "",
                "canonical_definition": str(entry.get("canonical_definition") or entry.get("notes") or ""),
                "aliases": "; ".join(str(alias) for alias in entry.get("aliases", [])[:20]),
                "review_status": "pending",
            }
        )
    return sorted(rows, key=lambda row: (-int(row["usage_count"]), row["canonical_id"]))


def write_csv(rows: list[dict[str, str]], output_path: str | Path) -> None:
    with Path(output_path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft inert semantic labels for canonical review.")
    parser.add_argument("--pass2", default="", help="Optional Pass 2 JSON to prioritize used canonicals")
    parser.add_argument("--min-usage", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = draft_labels(args.pass2 or None, min_usage=args.min_usage)
    write_csv(rows, args.output)
    print(f"canonical label draft rows: {len(rows)}")
    print(f"Wrote {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
