import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Any


COUNTRY_TERMS = {
    "united states",
    "canada",
    "germany",
    "france",
    "mexico",
    "brazil",
    "china",
    "india",
    "japan",
    "latin america",
    "north america",
    "europe",
    "asia pacific",
    "emea",
}


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def _token_set(text: str) -> set[str]:
    return set(_normalize(text).split())


def _infer_unit_family(raw_name: str, raw_unit: str) -> str:
    combined = f"{raw_name} {raw_unit}".lower()
    if "%" in combined or any(
        token in combined
        for token in ["percent", "percentage", "margin", "rate", "growth", "share"]
    ):
        return "percentage"
    if any(
        token in combined
        for token in ["stores", "store count", "count", "visits", "traffic", "headcount"]
    ):
        return "count"
    if any(
        token in combined
        for token in ["days", "turnover", "turns", "ratio", "x"]
    ):
        return "ratio"
    return "monetary"


def _dimension_hint(raw_name: str, section_title: str) -> str | None:
    raw = _normalize(raw_name)
    section = _normalize(section_title)
    if raw in COUNTRY_TERMS:
        return "geography"
    if any(term in raw for term in ["wholesale", "direct to consumer", "e commerce", "foodservice"]):
        return "channel"
    if any(term in raw for term in ["brand", "category"]):
        return "brand_or_category"
    if any(term in section for term in ["geographic", "region", "market"]):
        return "geography"
    if any(term in section for term in ["segment", "brand", "category"]):
        return "segment_or_brand"
    return None


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_alias_lookup(registry: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for entry in registry:
        canonical_id = str(entry.get("canonical_id", "")).strip()
        if not canonical_id:
            continue
        display_name = str(entry.get("display_name", "")).strip()
        aliases[_normalize(canonical_id)] = canonical_id
        if display_name:
            aliases[_normalize(display_name)] = canonical_id
        note_tokens = [
            token.strip()
            for token in re.split(r"[.;]", str(entry.get("notes", "")))
            if token.strip()
        ]
        for token in note_tokens[:2]:
            if len(token.split()) <= 4:
                aliases[_normalize(token)] = canonical_id
    return aliases


def shortlist_candidates(
    raw_name: str,
    section_title: str,
    raw_unit: str,
    registry: list[dict[str, Any]],
    top_n: int = 8,
) -> dict[str, Any]:
    aliases = _build_alias_lookup(registry)
    normalized_raw = _normalize(raw_name)
    unit_family = _infer_unit_family(raw_name, raw_unit)
    section_tokens = _token_set(section_title)
    raw_tokens = _token_set(raw_name)
    dimension_hint = _dimension_hint(raw_name, section_title)

    exact_match = aliases.get(normalized_raw)
    scored: list[dict[str, Any]] = []

    for entry in registry:
        canonical_id = str(entry.get("canonical_id", ""))
        display_name = str(entry.get("display_name", ""))
        entry_unit = str(entry.get("unit", ""))
        entry_category = str(entry.get("category", ""))
        entry_notes = str(entry.get("notes", ""))
        candidate_text = f"{display_name} {canonical_id} {entry_category} {entry_notes}"
        candidate_tokens = _token_set(candidate_text)

        score = 0.0
        reasons: list[str] = []

        if exact_match == canonical_id:
            score += 2.0
            reasons.append("exact alias/display match")

        fuzzy_name = difflib.SequenceMatcher(
            None, normalized_raw, _normalize(display_name)
        ).ratio()
        fuzzy_id = difflib.SequenceMatcher(
            None, normalized_raw, _normalize(canonical_id)
        ).ratio()
        fuzzy_score = max(fuzzy_name, fuzzy_id)
        score += fuzzy_score
        if fuzzy_score >= 0.8:
            reasons.append("strong fuzzy match")

        token_overlap = len(raw_tokens & candidate_tokens)
        if token_overlap:
            score += min(token_overlap * 0.18, 0.54)
            reasons.append("token overlap")

        section_overlap = len(section_tokens & candidate_tokens)
        if section_overlap:
            score += min(section_overlap * 0.12, 0.36)
            reasons.append("section overlap")

        if unit_family == "percentage" and entry_unit == "percentage":
            score += 0.35
            reasons.append("unit family match")
        elif unit_family == "count" and entry_unit in {"count", "count_or_index"}:
            score += 0.35
            reasons.append("unit family match")
        elif unit_family == "monetary" and "monetary" in entry_unit:
            score += 0.2
            reasons.append("unit family match")

        if dimension_hint == "geography" and canonical_id in {
            "total_revenue",
            "brand_performance",
            "segment_operating_profit",
            "organic_revenue_growth",
        }:
            score += 0.15
            reasons.append("geography-compatible metric")

        if dimension_hint == "channel" and canonical_id in {
            "digital_sales",
            "ecommerce_sales",
            "direct_to_consumer_revenue",
            "wholesale_revenue",
        }:
            score += 0.25
            reasons.append("channel-compatible metric")

        scored.append(
            {
                "canonical_id": canonical_id,
                "display_name": display_name,
                "category": entry_category,
                "unit": entry_unit,
                "score": round(score, 4),
                "reasons": reasons,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return {
        "raw_name": raw_name,
        "section_title": section_title,
        "raw_unit": raw_unit,
        "unit_family": unit_family,
        "dimension_hint": dimension_hint,
        "top_candidates": scored[:top_n],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shortlist ontology candidates.")
    parser.add_argument(
        "--registry",
        default="consumer_master_registry_v1.json",
        help="Path to the metric registry JSON.",
    )
    parser.add_argument(
        "--samples",
        required=True,
        help="Path to a JSON array of sample fact contexts.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write shortlist results.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    registry = _load_json(args.registry)
    samples = _load_json(args.samples)
    output = []
    for sample in samples:
        output.append(
            shortlist_candidates(
                raw_name=str(sample.get("raw_name", "")),
                section_title=str(sample.get("section_title", "")),
                raw_unit=str(sample.get("raw_unit", "")),
                registry=registry,
            )
        )
    Path(args.output).write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"wrote {args.output} with {len(output)} shortlist results")


if __name__ == "__main__":
    main()
