from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from gold_set import compute_match_score, compute_match_signals
from metric_registry_seed import REGISTRY as SEED_REGISTRY
from semantic_registry import (
    AliasGateResult,
    infer_fact_semantics_draft,
    semantic_alias_gate,
    semantic_typing_from_registry,
    unit_family_for_fact,
    validate_registry_semantics,
)


AUDIT_FIELDS = [
    "fact_id",
    "raw_name",
    "metric_core",
    "evidence",
    "nearest_canonical_1",
    "score_1",
    "nearest_canonical_2",
    "score_2",
    "nearest_canonical_3",
    "score_3",
    "unit_compatible",
    "role_compatible",
    "denominator_compatible",
    "block_reasons",
    "why_not_top_candidate",
    "recommended_action",
    "review_status",
    "fact_metric_subject_draft",
    "fact_metric_role_draft",
    "fact_flow_direction_draft",
    "fact_denominator_type_draft",
    "fact_unit_family",
    "top_canonical_metric_subject",
    "top_canonical_metric_role",
    "top_canonical_flow_direction",
    "top_canonical_denominator_type",
    "top_canonical_unit_family",
    "definition_score_1",
    "metric_core_score_1",
    "alias_score_1",
    "definition_drifted_1",
]


def _load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_registry() -> list[dict[str, Any]]:
    base_path = Path("consumer_master_registry_v1.json")
    base_registry = _load_json(base_path) if base_path.exists() else []
    by_id = {str(entry.get("canonical_id") or ""): dict(entry) for entry in base_registry}
    for seed_entry in SEED_REGISTRY:
        canonical_id = str(seed_entry.get("canonical_id") or "")
        if not canonical_id:
            continue
        existing = by_id.get(canonical_id, {})
        merged = dict(existing)
        merged.update(seed_entry)
        by_id[canonical_id] = merged
    return list(by_id.values())


def _facts_from_pass2(path: str | Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, dict):
        facts = payload.get("facts", [])
        return facts if isinstance(facts, list) else []
    return payload if isinstance(payload, list) else []


def _raw_name(fact: dict[str, Any]) -> str:
    raw = fact.get("raw") if isinstance(fact.get("raw"), dict) else {}
    return str(raw.get("raw_name") or fact.get("metric") or "")


def _metric_core(fact: dict[str, Any]) -> str:
    raw = fact.get("raw") if isinstance(fact.get("raw"), dict) else {}
    return str(raw.get("metric_core") or fact.get("metric") or "")


def _match_fact_for_score(fact: dict[str, Any]) -> dict[str, Any]:
    raw = fact.get("raw") if isinstance(fact.get("raw"), dict) else {}
    return {
        "raw_name": _raw_name(fact),
        "metric_core": _metric_core(fact),
        "metric_definition": str(fact.get("metric_definition") or raw.get("metric_definition") or ""),
        "raw_unit": str(raw.get("raw_unit") or fact.get("unit") or ""),
        "fact_class": str(raw.get("fact_class") or fact.get("fact_class") or ""),
        "source_sentence": str(raw.get("source_sentence") or fact.get("evidence") or ""),
    }


def _nearest_candidates(
    fact: dict[str, Any],
    registry: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    match_fact = _match_fact_for_score(fact)
    rows = []
    for entry in registry:
        score = compute_match_score(match_fact, entry)
        if score <= 0:
            continue
        signals = compute_match_signals(match_fact, entry)
        rows.append(
            {
                "canonical_id": str(entry.get("canonical_id") or ""),
                "score": float(score),
                "definition_score": float(signals["definition_score"]),
                "metric_core_score": float(signals["metric_core_score"]),
                "alias_score": float(signals["alias_score"]),
                "definition_drifted": bool(signals["definition_drifted"]),
                "entry": entry,
            }
        )
    return sorted(rows, key=lambda row: row["score"], reverse=True)[:limit]


def _recommended_action(
    *,
    gate_result: AliasGateResult | None,
    top_score: float,
    fact_semantics_typed: bool,
    top_canonical_typed: bool,
    evidence_text: str,
) -> str:
    if gate_result and gate_result.eligible and top_score >= 0.65:
        return "alias_candidate"
    if _standard_hint(evidence_text):
        return "standard_mapping_candidate"
    if not fact_semantics_typed or not top_canonical_typed:
        return "true_provisional"
    if gate_result and "role_mismatch" in gate_result.block_reasons:
        return "true_provisional"
    if top_score < 0.45:
        return "true_provisional"
    return "do_not_promote"


def _standard_hint(text: str) -> bool:
    return bool(
        re.search(
            r"\b(brsr|gri|sasb|scope\s*[123]|energy|water|waste|epr|plastic|emissions?|ghg|effluent|renewable)\b",
            text,
            re.I,
        )
    )


def _why_not(
    *,
    gate_result: AliasGateResult | None,
    top_score: float,
    top_id: str,
) -> str:
    if gate_result is None:
        return "No nearest canonical was available for comparison."
    if gate_result.eligible:
        return f"Nearest canonical {top_id} passed the semantic gate; alias requires human approval."
    reasons = ", ".join(gate_result.block_reasons) or "unknown"
    return f"Nearest canonical {top_id} is not alias-eligible because: {reasons}."


def audit_new_metrics(pass2_path: str | Path) -> list[dict[str, Any]]:
    registry = _load_registry()
    semantic_errors = validate_registry_semantics(registry)
    if semantic_errors:
        formatted = "; ".join(f"{key}: {value}" for key, value in semantic_errors.items())
        raise ValueError(f"Registry semantic validation failed: {formatted}")

    facts = [
        fact
        for fact in _facts_from_pass2(pass2_path)
        if str(fact.get("normalization_decision") or "") == "new_metric"
    ]
    rows: list[dict[str, Any]] = []
    for fact in facts:
        raw = fact.get("raw") if isinstance(fact.get("raw"), dict) else {}
        nearest = _nearest_candidates(fact, registry)
        fact_semantics = infer_fact_semantics_draft(fact)
        fact_unit = unit_family_for_fact(fact)
        top = nearest[0] if nearest else None
        top_entry = top["entry"] if top else {}
        top_semantics = semantic_typing_from_registry(top_entry) if top else None
        gate_result = (
            semantic_alias_gate(
                fact_semantics=fact_semantics,
                canonical_semantics=top_semantics,
                fact_unit_family=fact_unit,
                canonical_unit_family=str(top_entry.get("unit_family") or top_entry.get("unit") or "unknown"),
            )
            if top and top_semantics
            else None
        )
        evidence = str(fact.get("evidence") or raw.get("source_sentence") or "")
        recommended_action = _recommended_action(
            gate_result=gate_result,
            top_score=float(top["score"]) if top else 0.0,
            fact_semantics_typed=fact_semantics.is_typed,
            top_canonical_typed=bool(top_semantics and top_semantics.is_typed),
            evidence_text=" ".join([evidence, _raw_name(fact), _metric_core(fact)]),
        )
        row = {
            "fact_id": str(fact.get("fact_id") or ""),
            "raw_name": _raw_name(fact),
            "metric_core": _metric_core(fact),
            "evidence": evidence,
            "nearest_canonical_1": top["canonical_id"] if top else "",
            "score_1": f"{top['score']:.3f}" if top else "",
            "nearest_canonical_2": nearest[1]["canonical_id"] if len(nearest) > 1 else "",
            "score_2": f"{nearest[1]['score']:.3f}" if len(nearest) > 1 else "",
            "nearest_canonical_3": nearest[2]["canonical_id"] if len(nearest) > 2 else "",
            "score_3": f"{nearest[2]['score']:.3f}" if len(nearest) > 2 else "",
            "unit_compatible": str(gate_result.unit_compatible if gate_result else False).lower(),
            "role_compatible": str(gate_result.role_compatible if gate_result else False).lower(),
            "denominator_compatible": str(gate_result.denominator_compatible if gate_result else False).lower(),
            "block_reasons": ";".join(gate_result.block_reasons if gate_result else ("canonical_untyped",)),
            "why_not_top_candidate": _why_not(gate_result=gate_result, top_score=float(top["score"]) if top else 0.0, top_id=top["canonical_id"] if top else ""),
            "recommended_action": recommended_action,
            "review_status": "pending",
            "fact_metric_subject_draft": fact_semantics.metric_subject or "",
            "fact_metric_role_draft": fact_semantics.metric_role or "",
            "fact_flow_direction_draft": fact_semantics.flow_direction,
            "fact_denominator_type_draft": fact_semantics.denominator_type or "",
            "fact_unit_family": fact_unit,
            "top_canonical_metric_subject": top_semantics.metric_subject if top_semantics and top_semantics.metric_subject else "",
            "top_canonical_metric_role": top_semantics.metric_role if top_semantics and top_semantics.metric_role else "",
            "top_canonical_flow_direction": top_semantics.flow_direction if top_semantics else "",
            "top_canonical_denominator_type": top_semantics.denominator_type if top_semantics and top_semantics.denominator_type else "",
            "top_canonical_unit_family": str(top_entry.get("unit_family") or top_entry.get("unit") or ""),
            "definition_score_1": f"{top['definition_score']:.3f}" if top else "",
            "metric_core_score_1": f"{top['metric_core_score']:.3f}" if top else "",
            "alias_score_1": f"{top['alias_score']:.3f}" if top else "",
            "definition_drifted_1": str(bool(top["definition_drifted"]) if top else False).lower(),
        }
        rows.append(row)
    return rows


def write_audit(rows: list[dict[str, Any]], output_path: str | Path) -> None:
    output_path = Path(output_path)
    if output_path.suffix.lower() == ".jsonl":
        with output_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False))
                handle.write("\n")
        return
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit unresolved new_metric facts against nearest registry canonicals.")
    parser.add_argument("--pass2", required=True, help="Pass 2 JSON file")
    parser.add_argument("--output", required=True, help="CSV or JSONL audit output")
    args = parser.parse_args()
    rows = audit_new_metrics(args.pass2)
    write_audit(rows, args.output)
    print(f"new_metric rows audited: {len(rows)}")
    print(f"Wrote {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
