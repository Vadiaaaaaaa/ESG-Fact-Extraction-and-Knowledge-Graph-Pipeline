from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import normalizer


def _load_facts(path: str | Path) -> list[dict]:
    payload = json.load(open(path, encoding="utf-8"))
    facts = payload.get("facts", payload) if isinstance(payload, dict) else payload
    if not isinstance(facts, list):
        raise ValueError(f"Expected a list of facts in {path}")
    return facts


def _result_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("raw_name") or ""),
        str(row.get("metric_core") or ""),
        str(row.get("period") or ""),
        str(row.get("raw_unit") or ""),
        str(row.get("fact_class") or ""),
    )


def _fact_key(fact: dict) -> tuple[str, str, str, str, str]:
    raw = fact.get("raw") or {}
    return (
        str(raw.get("raw_name") or fact.get("metric") or ""),
        str(raw.get("metric_core") or ""),
        str(raw.get("raw_period") or fact.get("period") or ""),
        str(raw.get("raw_unit") or fact.get("unit") or ""),
        str(raw.get("fact_class") or ""),
    )


def export_readable_facts(input_path: str | Path, output_path: str | Path) -> int:
    facts = _load_facts(input_path)
    results = normalizer.dry_run(facts)
    by_key: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for rows in results.values():
        for row in rows:
            by_key.setdefault(_result_key(row), []).append(row)

    columns = [
        "fact_id",
        "section_title",
        "page_start",
        "page_end",
        "raw_name",
        "metric_core",
        "metric_definition",
        "value",
        "unit",
        "period",
        "fact_class",
        "direction",
        "entity",
        "segment",
        "scope",
        "graph_fact_type",
        "dimension_type",
        "dimension_member",
        "normalization_decision",
        "canonical_id",
        "best_score",
        "second_best_score",
        "normalization_reason",
        "review_action",
        "review_status",
        "evidence",
    ]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for fact in facts:
            raw = fact.get("raw") or {}
            matches = by_key.get(_fact_key(fact)) or []
            match = matches.pop(0) if matches else {}
            dimension = match.get("dimension") if isinstance(match.get("dimension"), dict) else {}
            writer.writerow(
                {
                    "fact_id": fact.get("fact_id") or raw.get("fact_id"),
                    "section_title": fact.get("section_title"),
                    "page_start": fact.get("page_start"),
                    "page_end": fact.get("page_end"),
                    "raw_name": raw.get("raw_name") or fact.get("metric"),
                    "metric_core": raw.get("metric_core"),
                    "metric_definition": fact.get("metric_definition") or raw.get("metric_definition"),
                    "value": fact.get("value") or raw.get("raw_value"),
                    "unit": fact.get("unit") or raw.get("raw_unit"),
                    "period": fact.get("period") or raw.get("raw_period"),
                    "fact_class": raw.get("fact_class"),
                    "direction": raw.get("direction"),
                    "entity": fact.get("entity"),
                    "segment": fact.get("segment"),
                    "scope": raw.get("scope"),
                    "graph_fact_type": raw.get("graph_fact_type"),
                    "dimension_type": dimension.get("dimension_type") or raw.get("dimension_type"),
                    "dimension_member": dimension.get("dimension_member") or raw.get("dimension_member"),
                    "normalization_decision": match.get("decision"),
                    "canonical_id": match.get("best_canonical_id"),
                    "best_score": match.get("best_score"),
                    "second_best_score": match.get("second_best_score"),
                    "normalization_reason": match.get("reason"),
                    "review_action": match.get("review_action"),
                    "review_status": match.get("review_status"),
                    "evidence": fact.get("evidence") or raw.get("source_sentence"),
                }
            )
    return len(facts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Pass 1 facts plus Pass 2 decisions as a readable CSV.")
    parser.add_argument("input", help="Pass 1 EDC JSON path")
    parser.add_argument("output", help="Readable CSV output path")
    args = parser.parse_args()
    count = export_readable_facts(args.input, args.output)
    print(f"Wrote {count} rows to {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
