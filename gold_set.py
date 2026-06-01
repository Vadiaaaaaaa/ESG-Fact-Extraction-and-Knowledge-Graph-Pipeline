from __future__ import annotations

import sys
import json
import re
from difflib import SequenceMatcher
from statistics import mean

from definitions import definition_similarity, set_registry
from metric_registry_seed import REGISTRY, build_alias_index
from normalizer_guardrails import are_unit_families_compatible, unit_family_from_raw_unit

SCORE_FLOOR = 0.65
SCORE_MARGIN = 0.20

_LEVEL_CANONICAL_IDS = {
    "scope_1_emissions",
    "scope_2_emissions",
    "scope_3_emissions",
    "energy_intensity",
    "water_consumption_intensity",
    "water_consumption_per_unit",
    "ghg_emissions_intensity",
    "carbon_intensity_per_product",
    "energy_consumption_per_unit",
    "water_withdrawal",
}

_INTENSITY_CANONICAL_IDS = {
    "ghg_emissions_intensity",
    "energy_intensity",
    "energy_consumption_per_unit",
    "water_consumption_intensity",
    "water_consumption_per_unit",
    "carbon_intensity_per_product",
}

_PURE_LEVEL_CANONICAL_IDS = {
    "scope_1_emissions",
    "scope_2_emissions",
    "scope_3_emissions",
    "water_withdrawal",
    "waste_generated",
    "plastic_waste_collected",
}

_REDUCTION_RE = re.compile(r"\b(reduction|reduced|reduce|decrease|decreased|lower|lesser)\b", re.I)
_PREVENTION_RE = re.compile(r"\b(prevent(?:ed|s|ing)?|avoid(?:ed|s|ing)?|divert(?:ed|s|ing)?|from\s+reaching\s+landfills?)\b", re.I)
_NON_RENEWABLE_RE = re.compile(r"\b(non[-\s]?renewable|fossil|conventional energy)\b", re.I)
_VALUE_GROWTH_RE = re.compile(r"\b(value|revenue|sales|turnover)\s+growth\b|\bgrowth\s+in\s+(value|revenue|sales|turnover)\b", re.I)
_VOLUME_GROWTH_RE = re.compile(r"\b(unit\s+volume|volume|unit|case)\s+growth\b|\bgrowth\s+in\s+(unit\s+volume|volume|units|cases)\b", re.I)
_EMISSIONS_RE = re.compile(r"\b(ghg|greenhouse gas|emissions?|co2|carbon|transport emissions?)\b", re.I)
_RECYCLABLE_PACKAGING_RE = re.compile(r"\brecyclable packaging|packaging material share|packaging recyclability\b", re.I)
_WATER_CONSERVATION_POTENTIAL_RE = re.compile(r"\bwater (?:conservation|replenishment)?\s*potential|water capacity created|rainwater conservation potential\b", re.I)
_RND_SPEND_RE = re.compile(r"\br\s*&\s*d|research and development|rnd\b", re.I)
_BRAND_MARKETING_SPEND_RE = re.compile(r"\bbrand building|asp to sales|advertising and sales promotion|a&p|marketing spend|brand investment\b", re.I)

# Remaining true matcher errors to tighten definitions against later:
# - "7 categories of corporate value chain emissions" should map to
#   scope_3_emissions_categories, not scope_3_emissions (~0.621)
# - "0.84 kL/Ton" should map to water_consumption_intensity (~0.447)
# - "Finished Goods Movement" should map to finished_goods_movement (~0.395)
# - "3,63,395 man-hours training" should map to training_hours (~0.353)


GOLD_SET = [
    {
        "raw_name": "9% improvement in overall manufacturing productivity",
        "metric_core": "manufacturing_productivity",
        "raw_unit": "%",
        "fact_class": "change",
        "period": "FY2025",
        "correct_canonical_id": "manufacturing_productivity",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Efficiency (Capital Investment for Smart factory automation)",
        "metric_core": "Capital Investment",
        "raw_unit": "INR Lakhs",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "capital_investment",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Reduction in unplanned production downtime",
        "metric_core": "Unplanned Production Downtime",
        "raw_unit": "%",
        "fact_class": "change",
        "period": "FY2025",
        "correct_canonical_id": "unplanned_downtime",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Improvement in Overall Equipment Effectiveness",
        "metric_core": "Overall Equipment Effectiveness",
        "raw_unit": "%",
        "fact_class": "transition",
        "period": "FY2025",
        "correct_canonical_id": "overall_equipment_effectiveness",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "On-time order fulfilment",
        "metric_core": "On-time order fulfilment",
        "raw_unit": "%",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "on_time_order_fulfillment",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Finished Goods Distributed",
        "metric_core": "Finished Goods Distributed",
        "raw_unit": "million",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "finished_goods_distributed",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Finished Goods Movement",
        "metric_core": "Finished Goods Movement",
        "raw_unit": "metric tons",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "finished_goods_movement",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "co2 emissions reduction",
        "metric_core": "CO2 emissions reduction",
        "raw_unit": "metric tons",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "co2_emissions_reduction",
        "metric_core_quality": "good",
        "exclude_from_ceiling": True,
    },
    {
        "raw_name": "rail-based transportation volumes",
        "metric_core": "rail-based transportation volumes",
        "raw_unit": "",
        "fact_class": "ratio_change",
        "period": "FY2025",
        "correct_canonical_id": "rail_transport_volume_change",
        "metric_core_quality": "junk",
    },
    {
        "raw_name": "pack sizes",
        "metric_core": "pack_size",
        "raw_unit": "ml",
        "fact_class": "range",
        "period": "FY2025",
        "correct_canonical_id": "pack_size",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Packaging line productivity",
        "metric_core": "packaging_productivity",
        "raw_unit": "%",
        "fact_class": "change",
        "period": "FY2025",
        "correct_canonical_id": "packaging_productivity",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Average batch changeover time",
        "metric_core": "batch_changeover_time",
        "raw_unit": "%",
        "fact_class": "change",
        "period": "FY2025",
        "correct_canonical_id": "batch_changeover_time",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Warehouse dispatch accuracy",
        "metric_core": "dispatch_accuracy",
        "raw_unit": "%",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "warehouse_dispatch_accuracy",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "12% reduction in Energy Intensity",
        "metric_core": "Energy Intensity",
        "raw_unit": "%",
        "fact_class": "change",
        "period": "FY2025",
        "correct_canonical_id": "energy_intensity",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "Amla Hair Oil Line",
        "metric_core": "productivity",
        "raw_unit": "cases/person",
        "fact_class": "transition",
        "period": "FY2025",
        "correct_canonical_id": "labor_productivity",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "logistics management",
        "metric_core": "logistics management",
        "raw_unit": "tonnage",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "finished_goods_movement",
        "metric_core_quality": "junk",
    },
    {
        "raw_name": "warehouse count",
        "metric_core": "warehouse_count",
        "raw_unit": "Mother Warehouses",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "warehouse_count",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "cf agent count",
        "metric_core": "cf_agent_count",
        "raw_unit": "Carrying & Forwarding Agents (C&FAs)",
        "fact_class": "scalar_kpi",
        "period": "FY2025",
        "correct_canonical_id": "cf_agent_count",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "14 Lines",
        "metric_core": "production_lines",
        "raw_unit": "Lines",
        "fact_class": "scalar_kpi",
        "period": "FY2024",
        "correct_canonical_id": "production_lines",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "3,63,395 man-hours training",
        "metric_core": "training_hours",
        "raw_unit": "man-hours",
        "fact_class": "scalar_kpi",
        "period": "FY2024",
        "correct_canonical_id": "training_hours",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "0.84 kL/Ton",
        "metric_core": "specific_water_consumption",
        "raw_unit": "kL/Ton",
        "fact_class": "transition",
        "period": "FY2024",
        "correct_canonical_id": "water_consumption_intensity",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "manufacturing facilities",
        "metric_core": "manufacturing facilities",
        "raw_unit": "",
        "fact_class": "scalar_kpi",
        "period": "FY2024",
        "correct_canonical_id": "manufacturing_facilities_count",
        "metric_core_quality": "junk",
    },
    {
        "raw_name": "28% share of renewable electricity",
        "metric_core": "renewable_energy_share",
        "raw_unit": "%",
        "fact_class": "scalar_kpi",
        "period": "FY2024",
        "correct_canonical_id": "renewable_energy_mix",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "6% decrease in renewable electricity share",
        "metric_core": "renewable_energy_share",
        "raw_unit": "%",
        "fact_class": "change",
        "period": "FY2024",
        "correct_canonical_id": "renewable_energy_mix",
        "metric_core_quality": "good",
    },
    {
        "raw_name": "~3% increase in GHG emissions intensity",
        "metric_core": "GHG emissions intensity change",
        "raw_unit": "%",
        "fact_class": "change",
        "period": "FY2024",
        "correct_canonical_id": "ghg_emissions_intensity",
        "metric_core_quality": "junk",
    },
    {
        "raw_name": "7 categories of corporate value chain emissions",
        "metric_core": "scope 3 emissions categories",
        "raw_unit": "categories",
        "fact_class": "scalar_kpi",
        "period": "FY2024",
        "correct_canonical_id": "scope_3_emissions_categories",
        "metric_core_quality": "good",
    },
]

_GOLD_DEFINITION_LOOKUP = {
    str(entry.get("canonical_id") or ""): str(entry.get("canonical_definition") or "")
    for entry in REGISTRY
    if str(entry.get("canonical_id") or "")
}

for _entry in GOLD_SET:
    _entry.setdefault(
        "metric_definition",
        _GOLD_DEFINITION_LOOKUP.get(str(_entry.get("correct_canonical_id") or ""), ""),
    )

_GOLD_ALIAS_INDEX = build_alias_index()
_GOLD_CANONICAL_DEFINITION_BY_ID = {
    str(entry.get("canonical_id") or ""): str(entry.get("canonical_definition") or "")
    for entry in REGISTRY
    if str(entry.get("canonical_id") or "")
}
_GOLD_ALIAS_PAIRS = []
for _entry in REGISTRY:
    _canonical_id = str(_entry.get("canonical_id") or "")
    if not _canonical_id:
        continue
    for _alias in [*_entry.get("aliases", []), _canonical_id.replace("_", " ")]:
        _alias_text = str(_alias or "").strip().lower()
        if _alias_text:
            _GOLD_ALIAS_PAIRS.append((_alias_text, _canonical_id))
_MOVEMENT_RE = __import__("re").compile(
    r"\b(improvement|improved|increase|increased|decrease|decreased|reduction|reduced|growth|grew|decline|declined|target|versus|compared|comparison|basis points?|bps|percentage points?)\b",
    __import__("re").IGNORECASE,
)
_TAXONOMY_RE = __import__("re").compile(
    r"\b(scope 1|scope 2|scope 3|purchased electricity|purchased energy|steam|heating|cooling|"
    r"indirect greenhouse gas|direct greenhouse gas|value chain emissions?)\b",
    __import__("re").IGNORECASE,
)


def _gold_fallback_definition(entry: dict) -> str:
    raw_candidates = [
        str(entry.get("metric_core") or "").replace("_", " "),
        str(entry.get("raw_name") or ""),
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        normalized = " ".join(candidate.split()).strip(" ,.-")
        stripped = _MOVEMENT_RE.sub(" ", candidate.replace("_", " "))
        stripped = " ".join(stripped.split()).strip(" ,.-")
        for variant in (normalized, stripped):
            key = variant.lower()
            if key and key not in seen:
                seen.add(key)
                candidates.append(variant)
    for candidate in candidates:
        cleaned = candidate.lower()
        canonical_id = _GOLD_ALIAS_INDEX.get(cleaned)
        if canonical_id:
            canonical_definition = _GOLD_CANONICAL_DEFINITION_BY_ID.get(canonical_id, "")
            if canonical_definition:
                return canonical_definition
    best_match_score = 0.0
    best_match_id = ""
    for candidate in candidates:
        cleaned = candidate.lower()
        if not cleaned:
            continue
        for alias_text, canonical_id in _GOLD_ALIAS_PAIRS:
            score = SequenceMatcher(None, cleaned, alias_text).ratio()
            if score > best_match_score:
                best_match_score = score
                best_match_id = canonical_id
    if best_match_score >= 0.58 and best_match_id:
        canonical_definition = _GOLD_CANONICAL_DEFINITION_BY_ID.get(best_match_id, "")
        if canonical_definition:
            return canonical_definition
    return ""


def _gold_definition_introduces_unanchored_taxonomy(entry: dict, definition: str) -> bool:
    definition_text = str(definition or "").lower()
    if not definition_text:
        return False
    definition_terms = {match.group(0).lower() for match in _TAXONOMY_RE.finditer(definition_text)}
    if not definition_terms:
        return False
    fact_text = " ".join(
        str(entry.get(key) or "")
        for key in ("raw_name", "metric_core")
    ).lower()
    return any(term not in fact_text for term in definition_terms)


def _sanitize_gold_metric_definition(entry: dict, metric_definition: str | None) -> str | None:
    fallback = _gold_fallback_definition(entry)
    text = " ".join(str(metric_definition or "").split()).strip()
    if not text:
        return fallback or None
    if _MOVEMENT_RE.search(text):
        return fallback or text
    if _gold_definition_introduces_unanchored_taxonomy(entry, text):
        return fallback or text
    return text


_LIVE_GOLD_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "gold_metric_definitions",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "definitions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "metric_definition": {"type": ["string", "null"]},
                        },
                        "required": ["index", "metric_definition"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["definitions"],
            "additionalProperties": False,
        },
    },
}


def _load_openai_client():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    from openai import OpenAI
    return OpenAI()


def regenerate_gold_definitions() -> list[dict]:
    client = _load_openai_client()
    regenerated = [dict(entry) for entry in GOLD_SET]
    for start in range(0, len(regenerated), 12):
        batch = regenerated[start : start + 12]
        payload = {
            "facts": [
                {
                    "index": start + idx,
                    "raw_name": entry["raw_name"],
                    "metric_core": entry["metric_core"],
                    "raw_unit": entry["raw_unit"],
                    "fact_class": entry["fact_class"],
                }
                for idx, entry in enumerate(batch)
            ]
        }
        system_prompt = """You are writing metric family definitions for a gold evaluation set.

Write one sentence per fact describing the underlying metric family in neutral terms.

Rules:
- Define the underlying metric, not the movement or change.
- Do not mention values, percentages, basis points, time periods, targets, prior year, or company names.
- Avoid movement wording such as improvement, increase, decrease, reduction, growth, decline, target, compared to, versus, or basis points.
- The definition must describe the metric named in the fact itself, using the fact's own subject.
- Do not substitute a related, more technical, or more specific concept.
- Do not introduce taxonomy or framework terms such as Scope 1/2/3, purchased electricity, or value-chain emissions unless those exact words appear in the fact.
- The definition's subject must match the fact's subject.
- Keep the definition short, neutral, and semantically informative.
- If the metric is unclear, return null.
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format=_LIVE_GOLD_RESPONSE_FORMAT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
            ],
            timeout=120,
        )
        response_json = json.loads(response.choices[0].message.content or "{}")
        for item in response_json.get("definitions", []):
            if not isinstance(item, dict):
                continue
            index = int(item.get("index", -1))
            if 0 <= index < len(regenerated):
                regenerated[index]["metric_definition"] = _sanitize_gold_metric_definition(
                    regenerated[index],
                    item.get("metric_definition"),
                )
    return regenerated


def is_definition_extraction_failure(metric_definition: str | None) -> bool:
    text = " ".join(str(metric_definition or "").split()).strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered in {
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "a mathematical ratio expressed as a fraction of 100.",
    }:
        return True
    if len(lowered.split()) < 4:
        return True
    return False


def _normalize_similarity_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("_", "")
    return "".join(char for char in text if char.isalnum() or char.isspace()).strip()


def _sequence_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


_DEFINITION_CONTENT_STOPWORDS = {
    "about",
    "above",
    "across",
    "associated",
    "between",
    "business",
    "company",
    "from",
    "have",
    "into",
    "than",
    "that",
    "their",
    "through",
    "where",
    "which",
    "with",
    "company",
    "during",
    "generated",
    "including",
    "measure",
    "measured",
    "measures",
    "metric",
    "operation",
    "operations",
    "overall",
    "percentage",
    "period",
    "proportion",
    "quantity",
    "ratio",
    "reduction",
    "reduced",
    "share",
    "specific",
    "total",
    "value",
    "waste",
}


def _stem_token(token: str) -> str:
    token = re.sub(r"[^a-z0-9]", "", str(token or "").lower())
    for suffix in ("ing", "edly", "ed", "ies", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            if suffix == "ies":
                return token[: -len(suffix)] + "y"
            return token[: -len(suffix)]
    return token


def _definition_content_tokens(metric_definition: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw_token in re.findall(r"[a-z0-9]+", str(metric_definition or "").lower()):
        token = _stem_token(raw_token)
        if len(token) < 4 or token in _DEFINITION_CONTENT_STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def _token_is_supported_by_source(token: str, source_text: str) -> bool:
    if not token:
        return False
    source_tokens = {_stem_token(item) for item in re.findall(r"[a-z0-9]+", str(source_text or "").lower())}
    if token in source_tokens:
        return True
    if any(token in source_token or source_token in token for source_token in source_tokens if len(source_token) >= 4):
        return True
    return any(_sequence_score(token, source_token) > 0.5 for source_token in source_tokens if len(source_token) >= 4)


def definition_is_drifted_for_fact(fact: dict) -> bool:
    metric_definition = str(fact.get("metric_definition") or "")
    content_tokens = _definition_content_tokens(metric_definition)
    if not content_tokens:
        return False
    source_text = " ".join(
        str(fact.get(key) or "")
        for key in ("raw_name", "metric_core", "source_sentence")
    )
    return not any(_token_is_supported_by_source(token, source_text) for token in content_tokens)


def compute_match_signals(fact: dict, canonical: dict) -> dict[str, float | bool]:
    definition_score = definition_similarity(
        str(fact.get("metric_definition") or ""),
        str(canonical.get("canonical_id") or ""),
    )
    metric_core_score = _sequence_score(
        _normalize_similarity_text(fact.get("metric_core", "")),
        _normalize_similarity_text(canonical.get("canonical_id", "")),
    )
    raw_name_normalized = _normalize_similarity_text(fact.get("raw_name", ""))
    alias_candidates = [
        *list(canonical.get("aliases", []) or []),
        str(canonical.get("canonical_id") or "").replace("_", " "),
        str(canonical.get("canonical_name") or ""),
    ]
    alias_score = max(
        (
            _sequence_score(raw_name_normalized, _normalize_similarity_text(alias))
            for alias in alias_candidates
        ),
        default=0.0,
    )
    return {
        "definition_score": definition_score,
        "metric_core_score": metric_core_score,
        "alias_score": alias_score,
        "definition_drifted": definition_is_drifted_for_fact(fact),
    }


def _scope_score(fact_scope: str, canonical_scope: str) -> float:
    fact_value = str(fact_scope or "unknown").strip().lower() or "unknown"
    canonical_value = str(canonical_scope or "unknown").strip().lower() or "unknown"
    if fact_value == "unknown" or canonical_value == "unknown" or fact_value == canonical_value:
        return 1.0
    return 0.5


def compute_match_score(fact: dict, canonical: dict) -> float:
    fact_unit_family = unit_family_from_raw_unit(fact.get("raw_unit"))
    canonical_unit_family = str(canonical.get("unit_family") or "").strip()
    allowed_unit_families = list(canonical.get("allowed_unit_families") or [])
    fact_class = str(fact.get("fact_class") or "").strip()
    if allowed_unit_families:
        if not any(
            are_unit_families_compatible(
                fact_unit_family,
                str(unit_family or "unknown"),
                fact_class=fact_class or None,
            )
            for unit_family in allowed_unit_families
        ):
            return 0.0
    elif not are_unit_families_compatible(
        fact_unit_family,
        canonical_unit_family or "unknown",
        fact_class=fact_class or None,
    ):
        return 0.0

    allowed_fact_classes = list(canonical.get("allowed_fact_classes") or [])
    if allowed_fact_classes and fact_class and fact_class not in allowed_fact_classes:
        return 0.0

    signals = compute_match_signals(fact, canonical)
    definition_score = float(signals["definition_score"])
    metric_core_score = float(signals["metric_core_score"])
    alias_score = float(signals["alias_score"])
    if bool(signals["definition_drifted"]):
        score = (0.20 * definition_score) + (0.50 * metric_core_score) + (0.30 * alias_score)
    else:
        score = (0.70 * definition_score) + (0.20 * metric_core_score) + (0.10 * alias_score)

    canonical_id = str(canonical.get("canonical_id") or "")
    canonical_text = " ".join(
        str(canonical.get(key) or "")
        for key in ("canonical_id", "canonical_name", "canonical_definition")
    )
    fact_text = " ".join(
        str(fact.get(key) or "")
        for key in ("raw_name", "metric_core", "metric_definition")
    )
    fact_subject_text = " ".join(
        str(fact.get(key) or "")
        for key in ("raw_name", "metric_core", "source_sentence")
    )
    is_baseline_reduction_fact = (
        bool(str(fact.get("baseline_year") or "").strip())
        and (
            str(fact.get("direction") or "").strip().lower() == "decreased"
            or bool(_REDUCTION_RE.search(fact_text))
        )
    )
    if is_baseline_reduction_fact:
        is_baseline_reduction_candidate = (
            canonical_id.endswith("_reduction_vs_baseline")
            or ("baseline" in canonical_text.lower() and bool(_REDUCTION_RE.search(canonical_text)))
        )
        is_reduction_candidate = bool(_REDUCTION_RE.search(canonical_text)) or "change" in canonical_id
        if is_baseline_reduction_candidate:
            score += 0.25
        elif is_reduction_candidate:
            score += 0.10
        elif canonical_id in _LEVEL_CANONICAL_IDS:
            score -= 0.35
        if _EMISSIONS_RE.search(fact_text):
            if canonical_id == "ghg_reduction_vs_baseline":
                score += 0.25
            elif canonical_id == "co2_emissions_reduction":
                score -= 0.45

    is_level_fact = (
        fact_class in {"scalar_kpi", "transition"}
        and not bool(str(fact.get("baseline_year") or "").strip())
        and str(fact.get("direction") or "").strip().lower() != "decreased"
        and not bool(_REDUCTION_RE.search(fact_subject_text))
        and not bool(re.search(r"\b(intensity|per\s+unit|per\s+tonne|per\s+kg|per\s+crore|/unit)\b", fact_subject_text, re.I))
    )
    if is_level_fact:
        if canonical_id in _INTENSITY_CANONICAL_IDS or "intensity" in canonical_id:
            score -= 0.30
        elif canonical_id in _PURE_LEVEL_CANONICAL_IDS:
            score += 0.08

        scope_numbers = set(re.findall(r"\bscope\s*([123])\b", fact_subject_text, re.I))
        for first_scope, second_scope in re.findall(
            r"\bscope\s*([123])\s*(?:\+|&|and)\s*(?:scope\s*)?([123])\b",
            fact_subject_text,
            re.I,
        ):
            scope_numbers.update({first_scope, second_scope})
        if len(scope_numbers) == 1:
            expected_scope_canonical = f"scope_{next(iter(scope_numbers))}_emissions"
            if canonical_id == expected_scope_canonical:
                score += 0.30
            elif canonical_id in {"scope_1_emissions", "scope_2_emissions", "scope_3_emissions"}:
                score -= 0.20
        elif len(scope_numbers) > 1 and canonical_id in {
            "scope_1_emissions",
            "scope_2_emissions",
            "scope_3_emissions",
        }:
            score -= 0.30

    # Negative compatibility: adjacent concepts can be very similar in embeddings
    # while still meaning the opposite thing or a different growth basis.
    if canonical_id == "renewable_energy_mix" and _NON_RENEWABLE_RE.search(fact_text):
        score = 0.0
    if canonical_id == "non_renewable_energy_share" and not _NON_RENEWABLE_RE.search(fact_text):
        score = 0.0

    scope_subject_numbers = set(re.findall(r"\bscope\s*([123])\b", fact_subject_text, re.I))
    for first_scope, second_scope in re.findall(
        r"\bscope\s*([123])\s*(?:\+|&|and)\s*(?:scope\s*)?([123])\b",
        fact_subject_text,
        re.I,
    ):
        scope_subject_numbers.update({first_scope, second_scope})
    if canonical_id.startswith("combined_scope_1_2_") and scope_subject_numbers == {"3"}:
        score = 0.0

    if canonical_id == "unit_volume_growth" and _VALUE_GROWTH_RE.search(fact_subject_text):
        score = 0.0

    if canonical_id in {"reported_revenue_growth", "comparable_sales_growth"} and _VOLUME_GROWTH_RE.search(fact_subject_text):
        score = 0.0

    if canonical_id == "waste_generated" and _PREVENTION_RE.search(fact_subject_text):
        score = 0.0

    if (
        canonical_id in {"scope_1_emissions", "scope_2_emissions", "scope_3_emissions"}
        and (_REDUCTION_RE.search(fact_subject_text) or _PREVENTION_RE.search(fact_subject_text))
        and not re.search(r"\bscope\s*[123]\b", fact_subject_text, re.I)
    ):
        score = 0.0

    if _RECYCLABLE_PACKAGING_RE.search(fact_text):
        if canonical_id == "packaging_recyclability":
            score += 0.20
        elif canonical_id == "recycled_content_in_packaging":
            score -= 0.20

    if _WATER_CONSERVATION_POTENTIAL_RE.search(fact_subject_text):
        if canonical_id == "water_conservation_potential":
            score += 0.35
        elif canonical_id == "water_consumption_intensity":
            score -= 0.35

    if _RND_SPEND_RE.search(fact_subject_text):
        if canonical_id == "rnd_investment_intensity":
            score += 0.35
        elif canonical_id in {"recycled_content_in_packaging", "packaging_recyclability"}:
            score -= 0.20

    if _BRAND_MARKETING_SPEND_RE.search(fact_subject_text):
        if canonical_id == "marketing_investment_intensity":
            score += 0.40
        elif canonical_id in {"brand_performance", "market_share", "brand_penetration"}:
            score -= 0.15

    return max(0.0, min(1.0, score))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return SCORE_FLOOR
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    return lower + ((upper - lower) * fraction)


def calibrate_thresholds(
    registry: list[dict],
    *,
    exclude_extraction_failures: bool = False,
) -> dict:
    set_registry(registry)
    gold_entries = regenerate_gold_definitions()
    correct_scores: list[float] = []
    wrong_scores: list[float] = []
    margins: list[float] = []
    dangerous_near_misses: list[tuple[dict, str, float, float]] = []
    true_error_wrong_scores: list[float] = []
    skipped_extraction_failures = 0

    for gold_fact in gold_entries:
        if exclude_extraction_failures and is_definition_extraction_failure(
            gold_fact.get("metric_definition")
        ):
            skipped_extraction_failures += 1
            continue
        scored = []
        for canonical in registry:
            score = compute_match_score(gold_fact, canonical)
            if score > 0.0:
                scored.append((str(canonical.get("canonical_id", "")), score))
        scored.sort(key=lambda item: item[1], reverse=True)

        if not scored:
            continue

        best_id, best_score = scored[0]
        second_best_score = scored[1][1] if len(scored) > 1 else 0.0
        margins.append(best_score - second_best_score)

        if best_id == gold_fact["correct_canonical_id"]:
            correct_scores.append(best_score)
        else:
            wrong_scores.append(best_score)
            dangerous_near_misses.append((gold_fact, best_id, best_score, second_best_score))
            if not bool(gold_fact.get("exclude_from_ceiling")):
                true_error_wrong_scores.append(best_score)

    floor_suggestion = _percentile(correct_scores, 0.10)
    margin_suggestion = mean(margins) if margins else SCORE_MARGIN

    print("Calibration report" + (" (excluding extraction failures)" if exclude_extraction_failures else ""))
    print(
        f"- correct matches: {len(correct_scores)}"
        + (
            f" | mean score: {mean(correct_scores):.3f}"
            if correct_scores
            else " | mean score: n/a"
        )
    )
    print(
        f"- wrong matches: {len(wrong_scores)}"
        + (
            f" | mean score: {mean(wrong_scores):.3f}"
            if wrong_scores
            else " | mean score: n/a"
        )
    )
    print(
        "- max true-error wrong-match score: "
        + (f"{max(true_error_wrong_scores):.3f}" if true_error_wrong_scores else "n/a")
    )
    print(
        "- correct-match 10th percentile: "
        + (f"{_percentile(correct_scores, 0.10):.3f}" if correct_scores else "n/a")
    )
    print(f"- suggested FLOOR: {floor_suggestion:.3f}")
    print(f"- suggested MARGIN: {margin_suggestion:.3f}")
    if exclude_extraction_failures:
        print(f"- skipped extraction failures: {skipped_extraction_failures}")

    if dangerous_near_misses:
        print("- dangerous near-misses:")
        for fact, wrong_id, best_score, second_best_score in dangerous_near_misses:
            print(
                "  * "
                f"{fact['raw_name']} -> {wrong_id} "
                f"(expected {fact['correct_canonical_id']}, "
                f"best={best_score:.3f}, second={second_best_score:.3f})"
            )

    return {
        "floor": floor_suggestion,
        "margin": margin_suggestion,
        "skipped_extraction_failures": skipped_extraction_failures,
        "max_true_error_wrong_score": max(true_error_wrong_scores) if true_error_wrong_scores else 0.0,
        "correct_match_mean": mean(correct_scores) if correct_scores else 0.0,
        "correct_match_p10": _percentile(correct_scores, 0.10) if correct_scores else 0.0,
    }


def audit_definition_similarity(registry: list[dict]) -> dict:
    set_registry(registry)
    gold_entries = regenerate_gold_definitions()
    scores: list[float] = []

    print("Definition similarity audit")
    for gold_fact in gold_entries:
        metric_definition = str(gold_fact.get("metric_definition") or "")
        correct_canonical_id = str(gold_fact.get("correct_canonical_id") or "")
        score = definition_similarity(metric_definition, correct_canonical_id)
        scores.append(score)
        print(
            f"- metric_definition: {metric_definition}\n"
            f"  correct_canonical_id: {correct_canonical_id}\n"
            f"  definition_similarity: {score:.3f}"
        )

    summary = {
        "mean": mean(scores) if scores else 0.0,
        "min": min(scores) if scores else 0.0,
        "p10": _percentile(scores, 0.10) if scores else 0.0,
    }
    print(
        "Summary stats\n"
        f"- mean: {summary['mean']:.3f}\n"
        f"- min: {summary['min']:.3f}\n"
        f"- 10th-percentile: {summary['p10']:.3f}"
    )
    return summary


if __name__ == "__main__":
    if "--audit" in sys.argv:
        audit_definition_similarity(REGISTRY)
    else:
        calibrate_thresholds(REGISTRY)
