from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from metric_registry_seed import REGISTRY
from review_memory import (
    REVIEW_MEMORY_VERSION,
    decision_keys,
    normalize_review_key,
)


ACCEPT_STATUSES = {
    "approve_mapping",
    "approve_mapping_or_add_alias",
    "fix_matcher_preference",
    "fix_registry_or_unit_gate",
    "fix_registry_unit_family",
    "fix_registry_duplicate_or_alias",
    "fix_definition",
}

FINANCIAL_ROUTE_STATUSES = {
    "route_financial",
    "route_financial_or_market",
    "approve_financial_or_market_mapping",
}

KEEP_PROVISIONAL_STATUSES = {
    "company_specific_or_add_canonical",
    "needs_manual_review",
    "do_not_auto_accept",
    "fix_scope_unknown_emissions",
}


def _registry_ids() -> set[str]:
    ids = {str(entry.get("canonical_id") or "") for entry in REGISTRY}
    for path in ("consumer_master_registry_v1.json", "metric_registry.json"):
        registry_path = Path(path)
        if not registry_path.exists():
            continue
        with registry_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            ids.update(
                str(entry.get("canonical_id") or "")
                for entry in payload
                if isinstance(entry, dict)
            )
        break
    return {canonical_id for canonical_id in ids if canonical_id}


def _infer_dimension(row: dict[str, str]) -> dict[str, str] | None:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("raw_name", "metric_core", "metric_definition")
    )
    normalized = normalize_review_key(text)

    packaging_patterns = [
        (r"\bcategory 1\b.*\brigids?\b", "rigids"),
        (r"\brigids?\b.*\bcategory 1\b", "rigids"),
        (r"\bcategory 2\b.*\bflexibles?\b", "flexibles"),
        (r"\bflexibles?\b.*\bcategory 2\b", "flexibles"),
        (r"\bcategory 3\b.*\bmulti layered packaging\b", "multi-layered packaging"),
        (r"\bmulti layered packaging\b.*\bcategory 3\b", "multi-layered packaging"),
        (r"\bcategory 1 packaging\b", "category 1 packaging"),
        (r"\bcategory 2 packaging\b", "category 2 packaging"),
        (r"\bcategory 3 packaging\b", "category 3 packaging"),
    ]
    for pattern, member in packaging_patterns:
        if re.search(pattern, normalized):
            return {"dimension_type": "packaging_type", "dimension_member": member}

    if re.search(r"\bfemale\b|\bwomen\b", normalized):
        return {"dimension_type": "gender", "dimension_member": "female"}
    if re.search(r"\bmale\b|\bmen\b", normalized):
        return {"dimension_type": "gender", "dimension_member": "male"}

    countries = {
        "outside united states": "Outside United States",
        "outside the united states": "Outside United States",
        "u s": "United States",
        "us": "United States",
        "usa": "United States",
        "united states": "United States",
        "ukraine": "Ukraine",
        "russia": "Russia",
        "bangladesh": "Bangladesh",
        "vietnam": "Vietnam",
        "egypt": "Egypt",
        "india": "India",
        "indonesia": "Indonesia",
        "china": "China",
        "brazil": "Brazil",
        "mexico": "Mexico",
        "canada": "Canada",
        "united kingdom": "United Kingdom",
        "germany": "Germany",
        "france": "France",
        "australia": "Australia",
    }
    for token, label in countries.items():
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            return {"dimension_type": "geography", "dimension_member": label}
    return None


def _decision_from_row(
    row: dict[str, str],
    registry_ids: set[str],
) -> dict[str, Any] | None:
    review_status = str(row.get("review_status") or "").strip()
    reviewed_canonical_id = str(row.get("reviewed_canonical_id") or "").strip()
    raw_name = str(row.get("raw_name") or "").strip()
    metric_core = str(row.get("metric_core") or "").strip()
    if not review_status:
        return None

    base = {
        "raw_name": raw_name,
        "metric_core": metric_core,
        "review_status": review_status,
        "review_notes": str(row.get("review_notes") or "").strip(),
    }

    if review_status == "fix_dimension_mapping":
        if reviewed_canonical_id and reviewed_canonical_id in registry_ids:
            return {
                **base,
                "action": "accept",
                "canonical_id": reviewed_canonical_id,
                "dimension": _infer_dimension(row),
            }
        return {**base, "action": "human_review"}

    if review_status in ACCEPT_STATUSES:
        if reviewed_canonical_id and reviewed_canonical_id in registry_ids:
            return {
                **base,
                "action": "accept",
                "canonical_id": reviewed_canonical_id,
                "dimension": _infer_dimension(row),
            }
        return {
            **base,
            "action": "candidate_canonical",
            "canonical_id": reviewed_canonical_id,
        }

    if review_status in FINANCIAL_ROUTE_STATUSES:
        return {
            **base,
            "action": "route_financial",
            "canonical_id": reviewed_canonical_id,
        }

    if review_status in KEEP_PROVISIONAL_STATUSES:
        action = "do_not_auto_accept" if review_status in {"do_not_auto_accept", "fix_scope_unknown_emissions"} else "keep_provisional"
        return {
            **base,
            "action": action,
            "canonical_id": reviewed_canonical_id,
        }

    if review_status in {"add_canonical", "add_canonical_optional"}:
        if reviewed_canonical_id and reviewed_canonical_id in registry_ids:
            return {
                **base,
                "action": "accept",
                "canonical_id": reviewed_canonical_id,
                "dimension": _infer_dimension(row),
            }
        return {
            **base,
            "action": "candidate_canonical",
            "canonical_id": reviewed_canonical_id,
        }

    return {**base, "action": "human_review", "canonical_id": reviewed_canonical_id}


def _decision_signature(decision: dict[str, Any]) -> str:
    return json.dumps(
        {
            "action": decision.get("action"),
            "canonical_id": decision.get("canonical_id"),
            "dimension": decision.get("dimension"),
        },
        sort_keys=True,
    )


def build_review_memory(review_csv: str | Path) -> dict[str, Any]:
    registry_ids = _registry_ids()
    pending: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with Path(review_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            decision = _decision_from_row(row, registry_ids)
            if not decision:
                continue
            for key in decision_keys(
                raw_name=str(row.get("raw_name") or ""),
                metric_core=str(row.get("metric_core") or ""),
                canonical_id=str(decision.get("canonical_id") or ""),
            ):
                pending[key].append(decision)

    decisions: dict[str, dict[str, Any]] = {}
    skipped_conflicting_keys: dict[str, list[dict[str, Any]]] = {}
    for key, keyed_decisions in pending.items():
        signatures = {_decision_signature(decision) for decision in keyed_decisions}
        if len(signatures) == 1:
            decisions[key] = keyed_decisions[-1]
        else:
            skipped_conflicting_keys[key] = keyed_decisions

    return {
        "version": REVIEW_MEMORY_VERSION,
        "source_review_csv": str(Path(review_csv)),
        "decisions": decisions,
        "skipped_conflicting_keys": skipped_conflicting_keys,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build review memory from a reviewed provisional queue CSV.")
    parser.add_argument("review_csv", help="Reviewed provisional action queue CSV")
    parser.add_argument(
        "--output",
        default="review_memory.json",
        help="Output JSON path, default: review_memory.json",
    )
    args = parser.parse_args()

    memory = build_review_memory(args.review_csv)
    output_path = Path(args.output)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(memory, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"Wrote {len(memory['decisions'])} review-memory keys to {output_path.resolve()}")


if __name__ == "__main__":
    main()
