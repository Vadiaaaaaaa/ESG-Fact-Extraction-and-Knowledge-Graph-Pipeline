from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from normalizer import _metric_registry_with_seed
from semantic_registry import infer_fact_semantics_draft, semantic_alias_gate, semantic_typing_from_registry, unit_family_for_fact
from unit_normaliser import normalise_fact_value


DEFAULT_COMPANIES = {
    "tata_consumer": Path("workspace_test_outputs/tata_consumer_pass2.json"),
    "gcpl": Path("workspace_test_outputs/gcpl_pass2.json"),
    "nestle_india": Path("workspace_test_outputs/nestle_india_pass2.json"),
    "itc": Path("workspace_test_outputs/itc_pass2.json"),
}

CONFIDENCE_FIELDS = [
    "normalization_status",
    "similarity_score",
    "gate_result",
    "tiebreaker_used",
    "tiebreaker_result",
    "period_confidence",
    "normalisation_confidence",
    "final_confidence",
]


def _load_fact_list(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        facts = payload.get("facts", [])
    else:
        facts = payload
    return [fact for fact in facts if isinstance(fact, dict)]


def _field_present(fact: dict[str, Any], field: str) -> bool:
    if field not in fact:
        return False
    value = fact.get(field)
    if field == "tiebreaker_result" and fact.get("tiebreaker_used") is False:
        return True
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _derive_gate_result(fact: dict[str, Any], registry_lookup: dict[str, dict[str, Any]]) -> str:
    canonical_id = str(fact.get("canonical_id") or "")
    if not canonical_id or canonical_id not in registry_lookup:
        return "fail" if str(fact.get("normalization_decision") or "").lower() in {"new_metric", "quarantine"} else "not_applicable"
    registry_entry = registry_lookup[canonical_id]
    gate = semantic_alias_gate(
        fact_semantics=infer_fact_semantics_draft(fact),
        canonical_semantics=semantic_typing_from_registry(registry_entry),
        fact_unit_family=unit_family_for_fact(fact),
        canonical_unit_family=str(registry_entry.get("unit_family") or ""),
    )
    substantive = [reason for reason in gate.block_reasons if reason not in {"canonical_untyped", "fact_untyped"}]
    if gate.eligible:
        return "pass"
    if substantive:
        return "fail"
    return "not_applicable"


def _derive_similarity_score(fact: dict[str, Any], registry_lookup: dict[str, dict[str, Any]]) -> float:
    if fact.get("best_score") is not None:
        return float(fact.get("best_score") or 0.0)
    if fact.get("alias_resolved"):
        return 1.0
    confidence = str(fact.get("mapping_confidence") or "").lower()
    if confidence == "high":
        return 0.95
    if confidence == "medium":
        return 0.75
    if confidence == "low":
        return 0.55
    return 0.0


def _derive_final_confidence(fact: dict[str, Any]) -> float:
    similarity = float(fact.get("similarity_score") or 0.0)
    decision = str(fact.get("normalization_status") or fact.get("normalization_decision") or "").lower()
    if decision == "normalized":
        return similarity
    if decision == "partial" and fact.get("tiebreaker_used") and fact.get("tiebreaker_result") == "accept":
        return similarity * 0.85
    if fact.get("tiebreaker_result") == "reject":
        return 0.5
    if decision == "new_metric":
        return 0.0
    return similarity


def _enrich_fact(fact: dict[str, Any], registry_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    updated = dict(fact)
    updated["normalization_status"] = str(updated.get("normalization_status") or updated.get("normalization_decision") or "")
    updated["similarity_score"] = float(updated.get("similarity_score") or _derive_similarity_score(updated, registry_lookup))
    updated["gate_result"] = str(updated.get("gate_result") or _derive_gate_result(updated, registry_lookup))
    resolution_method = str(updated.get("resolution_method") or "scorer")
    updated["tiebreaker_used"] = bool(
        updated.get("tiebreaker_used")
        if "tiebreaker_used" in updated
        else resolution_method in {"tiebreaker_layer1_token", "tiebreaker_layer2_llm"}
    )
    if "tiebreaker_result" not in updated:
        if updated["tiebreaker_used"]:
            updated["tiebreaker_result"] = "accept" if updated["normalization_status"] in {"normalized", "partial"} else "reject"
        elif str(updated.get("tiebreaker_layer") or ""):
            updated["tiebreaker_result"] = "reject"
        else:
            updated["tiebreaker_result"] = None
    updated["period_confidence"] = str(
        updated.get("period_confidence")
        or ((updated.get("raw") or {}).get("period_confidence"))
        or "inferred"
    )
    updated["normalisation_confidence"] = str(
        updated.get("normalisation_confidence")
        or normalise_fact_value(updated).get("normalisation_confidence")
        or "failed"
    )
    updated["final_confidence"] = float(updated.get("final_confidence") or _derive_final_confidence(updated))
    return updated


def check_company(name: str, path: Path, registry_lookup: dict[str, dict[str, Any]], *, apply: bool = False) -> dict[str, Any]:
    facts = [_enrich_fact(fact, registry_lookup) for fact in _load_fact_list(path)]
    if apply:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(facts, handle, ensure_ascii=False, indent=2)

    percentages = {
        field: (sum(1 for fact in facts if _field_present(fact, field)) / len(facts) * 100.0 if facts else 100.0)
        for field in CONFIDENCE_FIELDS
    }
    return {"company": name, "total_facts": len(facts), "field_coverage": percentages}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify ConfidenceRecord fields in Pass 2 outputs.")
    parser.add_argument("--apply", action="store_true", help="Write missing confidence fields back to the Pass 2 files.")
    args = parser.parse_args()

    registry_lookup = {
        str(entry.get("canonical_id") or ""): entry
        for entry in _metric_registry_with_seed()
        if str(entry.get("canonical_id") or "")
    }

    reports = [
        check_company(name, path, registry_lookup, apply=args.apply)
        for name, path in DEFAULT_COMPANIES.items()
    ]
    print("confidence field check")
    for report in reports:
        print(f"{report['company']}: total={report['total_facts']}")
        for field in CONFIDENCE_FIELDS:
            print(f"  {field}: {report['field_coverage'][field]:.1f}%")


if __name__ == "__main__":
    main()
