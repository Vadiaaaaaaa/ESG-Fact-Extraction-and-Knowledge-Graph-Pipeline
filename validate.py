import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable


DEFAULT_INPUT = "pass2_output.json"
CRITICAL_METRICS = {
    "total_revenue",
    "net_income",
    "operating_cash_flow",
    "free_cash_flow",
    "capex",
    "ebit",
}


def _load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _print_header(title: str) -> None:
    print(title)
    print("-" * len(title))


def _get_segment_name(fact: dict[str, Any]) -> str:
    raw = fact.get("raw", {})
    return str(raw.get("segment_name") or fact.get("segment") or "").strip()


def _print_counter(counter: Counter[str], keys: list[str]) -> None:
    for key in keys:
        print(f"{key}: {counter.get(key, 0)}")


def print_section_1(facts: list[dict[str, Any]], _: list[dict[str, Any]]) -> None:
    _print_header("SECTION 1 - PIPELINE SUMMARY")
    print(f"Total facts: {len(facts)}")
    print()
    print("By Pass 1 decision:")
    _print_counter(
        Counter(str(fact.get("decision", "")).lower() for fact in facts),
        ["keep", "rescue", "drop"],
    )
    print()
    print("By normalization_decision:")
    _print_counter(
        Counter(str(fact.get("normalization_decision", "")).lower() for fact in facts),
        ["normalized", "partial", "new_metric", "drop"],
    )
    print()
    print("By mapping_confidence:")
    _print_counter(
        Counter(str(fact.get("mapping_confidence", "")).lower() for fact in facts),
        ["high", "medium", "low", "no_match"],
    )


def print_section_2(facts: list[dict[str, Any]], registry: list[dict[str, Any]]) -> None:
    _print_header("SECTION 2 - METRIC COVERAGE")
    canonical_counts = Counter(
        str(fact.get("canonical_id", "")).strip()
        for fact in facts
        if str(fact.get("canonical_id", "")).strip()
    )
    print("Mapped canonical_id counts:")
    for canonical_id, count in sorted(
        canonical_counts.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"{canonical_id}: {count}")

    registry_ids = [
        str(metric.get("canonical_id", "")).strip()
        for metric in registry
        if str(metric.get("canonical_id", "")).strip()
    ]
    missing_ids = [canonical_id for canonical_id in registry_ids if canonical_id not in canonical_counts]

    print()
    print("Missing canonical_ids from metric_registry.json:")
    for canonical_id in missing_ids:
        prefix = "MISSING" if canonical_id in CRITICAL_METRICS else "missing"
        print(f"{prefix}: {canonical_id}")


def print_section_3(facts: list[dict[str, Any]], _: list[dict[str, Any]]) -> None:
    _print_header("SECTION 3 - VALUE SPOT CHECK")
    print('Ratio facts (unit_canonical = "ratio"):')
    ratio_facts = [fact for fact in facts if fact.get("unit_canonical") == "ratio"]
    for fact in ratio_facts:
        value_normalized = fact.get("value_normalized")
        flag = ""
        if isinstance(value_normalized, (int, float)) and value_normalized > 1.0:
            flag = "  FLAG: ratio > 1.0"
        print(
            f"{fact.get('fact_id')} | {fact.get('canonical_id')} | "
            f"{fact.get('raw', {}).get('raw_value')} | {value_normalized}{flag}"
        )

    print()
    print('USD facts (unit_canonical = "USD"):')
    usd_facts = [fact for fact in facts if fact.get("unit_canonical") == "USD"]
    for fact in usd_facts:
        value_normalized = fact.get("value_normalized")
        raw_scale = fact.get("raw_scale")
        flag = ""
        if (
            isinstance(value_normalized, (int, float))
            and value_normalized < 1000
            and raw_scale == "billions"
        ):
            flag = "  FLAG: billions scale not applied"
        print(
            f"{fact.get('fact_id')} | {fact.get('canonical_id')} | "
            f"{fact.get('raw', {}).get('raw_value')} | {value_normalized}{flag}"
        )


def print_section_4(facts: list[dict[str, Any]], _: list[dict[str, Any]]) -> None:
    _print_header("SECTION 4 - SEGMENT FACTS")
    segment_facts = [fact for fact in facts if _get_segment_name(fact)]
    for fact in segment_facts:
        print(
            f"{fact.get('fact_id')} | {fact.get('canonical_id')} | "
            f"{_get_segment_name(fact)} | {fact.get('value_normalized')}"
        )


def print_section_5(facts: list[dict[str, Any]], _: list[dict[str, Any]]) -> None:
    _print_header("SECTION 5 - RESCUE QUEUE")
    partial_facts = [
        fact for fact in facts
        if str(fact.get("normalization_decision", "")).lower() == "partial"
    ]
    for fact in partial_facts:
        raw = fact.get("raw", {})
        print(
            f"{fact.get('fact_id')} | {fact.get('canonical_id')} | "
            f"{fact.get('mapping_confidence')} | {fact.get('mapping_note')} | "
            f"{raw.get('rescue_note', '')}"
        )


def print_section_6(facts: list[dict[str, Any]], _: list[dict[str, Any]]) -> None:
    _print_header("SECTION 6 - NEW METRICS")
    new_metric_facts = [fact for fact in facts if fact.get("is_new_metric") is True]
    for fact in new_metric_facts:
        raw = fact.get("raw", {})
        print(
            f"{fact.get('fact_id')} | {raw.get('raw_name', '')} | "
            f"{fact.get('proposed_canonical_id')}"
        )


SECTIONS: dict[str, Callable[[list[dict[str, Any]], list[dict[str, Any]]], None]] = {
    "1": print_section_1,
    "2": print_section_2,
    "3": print_section_3,
    "4": print_section_4,
    "5": print_section_5,
    "6": print_section_6,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit Pass 2 normalization output")
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        metavar="PATH",
        help="Path to Pass 2 output JSON (default: pass2_output.json)",
    )
    parser.add_argument(
        "--section",
        metavar="N",
        choices=sorted(SECTIONS.keys()),
        help="Print only one report section",
    )
    args = parser.parse_args()

    facts = _load_json(args.input)
    registry = _load_json("metric_registry.json")

    if args.section:
        SECTIONS[args.section](facts, registry)
    else:
        for index in sorted(SECTIONS.keys()):
            SECTIONS[index](facts, registry)
            if index != "6":
                print()
