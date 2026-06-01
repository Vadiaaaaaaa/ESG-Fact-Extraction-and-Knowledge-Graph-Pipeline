from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from review_memory import REVIEW_MEMORY_VERSION


def _decision_signature(decision: dict[str, Any]) -> str:
    return json.dumps(
        {
            "action": decision.get("action"),
            "canonical_id": decision.get("canonical_id"),
            "dimension": decision.get("dimension"),
        },
        sort_keys=True,
    )


def _source_labels(memory: dict[str, Any], memory_path: Path) -> list[str]:
    labels: list[str] = []
    source_review_csv = memory.get("source_review_csv")
    if source_review_csv:
        labels.append(str(source_review_csv))
    for source in memory.get("source_review_csvs") or []:
        if source:
            labels.append(str(source))
    labels.append(str(memory_path))
    deduped: list[str] = []
    for label in labels:
        if label not in deduped:
            deduped.append(label)
    return deduped


def _with_sources(decision: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    merged = dict(decision)
    existing_sources = list(merged.get("memory_sources") or [])
    for source in sources:
        if source not in existing_sources:
            existing_sources.append(source)
    merged["memory_sources"] = existing_sources
    return merged


def merge_review_memories(paths: list[str | Path]) -> dict[str, Any]:
    merged_decisions: dict[str, dict[str, Any]] = {}
    conflicts: dict[str, list[dict[str, Any]]] = {}
    source_review_csvs: list[str] = []

    for raw_path in paths:
        memory_path = Path(raw_path)
        with memory_path.open("r", encoding="utf-8") as handle:
            memory = json.load(handle)
        sources = _source_labels(memory, memory_path)
        for source in sources:
            if source not in source_review_csvs:
                source_review_csvs.append(source)

        for key, decision in (memory.get("decisions") or {}).items():
            if not isinstance(decision, dict):
                continue
            sourced_decision = _with_sources(decision, sources)
            existing = merged_decisions.get(key)
            if not existing:
                merged_decisions[key] = sourced_decision
                continue
            if _decision_signature(existing) == _decision_signature(sourced_decision):
                merged_decisions[key] = _with_sources(existing, sources)
            else:
                conflicts.setdefault(key, [existing]).append(sourced_decision)

    return {
        "version": REVIEW_MEMORY_VERSION,
        "source_review_csvs": source_review_csvs,
        "decisions": merged_decisions,
        "merge_conflicts": conflicts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge reviewed provisional memories.")
    parser.add_argument("memory_files", nargs="+", help="Review memory JSON files to merge.")
    parser.add_argument(
        "--output",
        default="review_memory.json",
        help="Merged memory output path, default: review_memory.json",
    )
    args = parser.parse_args()

    memory = merge_review_memories(args.memory_files)
    output_path = Path(args.output)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(memory, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(
        f"Wrote {len(memory['decisions'])} merged keys to {output_path.resolve()} "
        f"with {len(memory['merge_conflicts'])} conflicts"
    )


if __name__ == "__main__":
    main()
