import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT = "pass2_output.json"
FLAGGED_PATH = "flagged.json"
REVIEW_OUTPUT_PATH = "review_output.json"
DIVIDER = "─" * 41


def _load_json(path: str | Path, default: Any) -> Any:
    file_path = Path(path)
    if not file_path.exists():
        return default
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str | Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _shorten(text: Any, width: int) -> str:
    value = str(text or "").replace("\n", " ").strip()
    if len(value) <= width:
        return value
    return value[: max(0, width - 3)] + "..."


def _display_period(fact: dict[str, Any]) -> str:
    raw = fact.get("raw", {})
    start = str(raw.get("resolved_period_start", "")).strip()
    end = str(raw.get("resolved_period_end", "")).strip()
    if len(start) >= 4 and start[:4].isdigit() and start == f"{start[:4]}-01-01" and end == f"{start[:4]}-12-31":
        return f"FY{start[:4]}"
    if start and end:
        return f"{start} to {end}"
    return str(raw.get("raw_period") or fact.get("period") or "unknown")


def _display_normalized_value(fact: dict[str, Any]) -> str:
    value_normalized = fact.get("value_normalized")
    unit_canonical = fact.get("unit_canonical") or ""
    if value_normalized is None:
        return f"n/a {unit_canonical}".strip()
    return f"{value_normalized} {unit_canonical}".strip()


def _matches_filter(fact: dict[str, Any], filter_value: str | None) -> bool:
    if not filter_value:
        return True

    value = filter_value.strip().lower()
    normalization_decision = str(fact.get("normalization_decision", "")).lower()
    mapping_confidence = str(fact.get("mapping_confidence", "")).lower()

    if value in {"partial", "new_metric", "normalized", "drop"}:
        return normalization_decision == value
    if value in {"high", "medium", "low", "no_match"}:
        return mapping_confidence == value
    return False


def _matches_section(fact: dict[str, Any], section_query: str | None) -> bool:
    if not section_query:
        return True

    query = section_query.strip().lower()
    haystacks = [
        str(fact.get("chunk_id", "")).lower(),
        str(fact.get("section_title", "")).lower(),
        str(fact.get("parent_section", "")).lower(),
    ]
    return any(query in haystack for haystack in haystacks)


def _filter_facts(
    facts: list[dict[str, Any]],
    filter_value: str | None,
    section_query: str | None,
) -> list[dict[str, Any]]:
    return [
        fact
        for fact in facts
        if _matches_filter(fact, filter_value) and _matches_section(fact, section_query)
    ]


def _print_fact(fact: dict[str, Any], index: int, total: int) -> None:
    raw = fact.get("raw", {})
    print(DIVIDER)
    print(f"[{index}/{total}] {fact.get('fact_id', '')}")
    print(DIVIDER)
    print(f"Raw name:     {raw.get('raw_name') or fact.get('metric') or ''}")
    print(f"Raw value:    {raw.get('raw_value') or fact.get('value') or ''}")
    print(f"Period:       {_display_period(fact)}")
    print(f"Section:      {fact.get('section_title', '')}")
    print(f'Source:       "{_shorten(raw.get("source_sentence") or fact.get("evidence") or "", 90)}"')
    print()
    print(
        "→ Canonical:  "
        f"{fact.get('canonical_id', '')} ({fact.get('canonical_name', '')})"
    )
    print(f"→ Confidence: {fact.get('mapping_confidence', '')}")
    print(f"→ Normalized: {_display_normalized_value(fact)}")
    print(f"→ Decision:   {fact.get('normalization_decision', '')}")
    print(DIVIDER)


def _load_existing_reviews() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    flagged_raw = _load_json(FLAGGED_PATH, [])
    review_raw = _load_json(REVIEW_OUTPUT_PATH, [])

    flagged = {
        str(item.get("fact_id", "")): item
        for item in flagged_raw
        if str(item.get("fact_id", ""))
    }
    review = {
        str(item.get("fact_id", "")): item
        for item in review_raw
        if str(item.get("fact_id", ""))
    }
    return flagged, review


def _save_reviews(
    flagged: dict[str, dict[str, Any]],
    review: dict[str, dict[str, Any]],
) -> None:
    _write_json(FLAGGED_PATH, list(flagged.values()))
    _write_json(REVIEW_OUTPUT_PATH, list(review.values()))


def browse_facts(facts: list[dict[str, Any]]) -> None:
    if not facts:
        print("No facts matched the requested view.")
        return

    flagged, review = _load_existing_reviews()
    current_index = 0
    reviewed_ids: set[str] = set()
    flagged_this_session: set[str] = set()
    dropped_this_session: set[str] = set()

    while 0 <= current_index < len(facts):
        fact = facts[current_index]
        fact_id = str(fact.get("fact_id", ""))
        reviewed_ids.add(fact_id)
        _print_fact(fact, current_index + 1, len(facts))
        command = input("ENTER=next, p=prev, s=skip10, f=flag, d=drop, q=quit: ").strip().lower()

        if command == "":
            current_index = min(len(facts) - 1, current_index + 1)
            continue
        if command == "p":
            current_index = max(0, current_index - 1)
            continue
        if command == "s":
            current_index = min(len(facts) - 1, current_index + 10)
            continue
        if command == "f":
            note = input("Flag note: ").strip()
            flagged_entry = {
                "fact_id": fact_id,
                "note": note,
                "canonical_id": fact.get("canonical_id", ""),
                "normalization_decision": fact.get("normalization_decision", ""),
            }
            flagged[fact_id] = flagged_entry
            review[fact_id] = {
                "fact_id": fact_id,
                "action": "flag",
                "note": note,
            }
            flagged_this_session.add(fact_id)
            _save_reviews(flagged, review)
            current_index = min(len(facts) - 1, current_index + 1)
            continue
        if command == "d":
            review[fact_id] = {
                "fact_id": fact_id,
                "action": "drop",
                "note": "marked drop in fact_viewer",
            }
            dropped_this_session.add(fact_id)
            _save_reviews(flagged, review)
            current_index = min(len(facts) - 1, current_index + 1)
            continue
        if command == "q":
            break

    _save_reviews(flagged, review)
    print(f"Facts reviewed: {len(reviewed_ids)}")
    print(f"Facts flagged: {len(flagged_this_session)}")
    print(f"Facts marked drop: {len(dropped_this_session)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interactive viewer for Pass 2 facts")
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        metavar="PATH",
        help="Path to Pass 2 output JSON (default: pass2_output.json)",
    )
    parser.add_argument(
        "--filter",
        metavar="VALUE",
        help="Filter by normalization_decision or mapping_confidence",
    )
    parser.add_argument(
        "--section",
        metavar="TEXT",
        help="Only show facts whose chunk_id/section contains this text",
    )
    args = parser.parse_args()

    all_facts = _load_json(args.input, [])
    filtered_facts = _filter_facts(all_facts, args.filter, args.section)
    browse_facts(filtered_facts)
