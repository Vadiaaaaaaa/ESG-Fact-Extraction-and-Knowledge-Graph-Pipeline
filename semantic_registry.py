from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from normalizer_guardrails import are_unit_families_compatible, unit_family_from_raw_unit


DENOMINATOR_TYPES = {
    None,
    "none",
    "production",
    "revenue",
    "employee",
    "worker",
    "floor_area",
    "store",
    "outlet",
    "unit_sold",
    "energy",
    "water",
    "waste",
}

BLOCK_REASONS = {
    "unit_mismatch",
    "subject_mismatch",
    "role_mismatch",
    "denominator_mismatch",
    "canonical_untyped",
    "fact_untyped",
    "near_duplicate_risk",
    "energy_source_mismatch",
}

ROLE_FLOW_DIRECTION = {
    "recharge": "restoration",
    "withdrawal": "input",
    "consumption": "consumed",
    "generation": "output",
    "recycling": "recovery",
    "recovery": "recovery",
    "diversion": "recovery",
    "disposal": "output",
    "discharge": "output",
    "intensity": "ratio",
    "conservation": "avoided",
    "reduction": "avoided",
    "avoidance": "avoided",
    "harvest": "restoration",
    "investment": "input",
    "rating": "unknown",
}

INTENSITY_DENOMINATOR_PATTERNS = [
    ("production", re.compile(r"\b(per|/)\s*(?:mt|tonne|ton|unit|kg|kilogram|production|output|product)\b", re.I)),
    ("revenue", re.compile(r"\b(per|/)\s*(?:revenue|turnover|sales|rupee|crore|inr)\b", re.I)),
    ("employee", re.compile(r"\b(per|/)\s*(?:employee|associate)\b", re.I)),
    ("worker", re.compile(r"\b(per|/)\s*worker\b", re.I)),
    ("floor_area", re.compile(r"\b(per|/)\s*(?:sq\.?\s*ft|square\s+feet|floor\s+area|m2|sqm)\b", re.I)),
    ("store", re.compile(r"\b(per|/)\s*store\b", re.I)),
    ("outlet", re.compile(r"\b(per|/)\s*outlet\b", re.I)),
    ("unit_sold", re.compile(r"\b(per|/)\s*(?:unit\s+sold|units\s+sold|case|cases)\b", re.I)),
    ("energy", re.compile(r"\b(per|/)\s*(?:gj|kwh|energy)\b", re.I)),
    ("water", re.compile(r"\b(per|/)\s*(?:kl|kilolitre|water)\b", re.I)),
    ("waste", re.compile(r"\b(per|/)\s*waste\b", re.I)),
]


@dataclass(frozen=True)
class SemanticTyping:
    metric_subject: str | None = None
    metric_role: str | None = None
    denominator_type: str | None = None
    impact_polarity: str | None = None
    energy_source: str | None = None

    @property
    def flow_direction(self) -> str:
        return derive_flow_direction(self.metric_role)

    @property
    def is_typed(self) -> bool:
        return bool(self.metric_subject and self.metric_role)


@dataclass(frozen=True)
class AliasGateResult:
    eligible: bool
    block_reasons: tuple[str, ...]
    unit_compatible: bool
    subject_compatible: bool
    role_compatible: bool
    denominator_compatible: bool
    flow_direction_compatible: bool


def derive_flow_direction(metric_role: str | None) -> str:
    return ROLE_FLOW_DIRECTION.get(str(metric_role or "").strip().lower(), "unknown")


def normalize_denominator_type(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "null":
        return None
    if text not in DENOMINATOR_TYPES:
        raise ValueError(f"Invalid denominator_type {value!r}")
    return None if text == "none" else text


def semantic_typing_from_registry(entry: dict[str, Any]) -> SemanticTyping:
    text = " ".join(
        str(value or "")
        for value in (
            entry.get("canonical_id"),
            entry.get("display_name"),
            entry.get("canonical_definition"),
            " ".join(entry.get("aliases") or []),
        )
    ).lower()
    return SemanticTyping(
        metric_subject=_clean_optional(entry.get("metric_subject")),
        metric_role=_clean_optional(entry.get("metric_role")),
        denominator_type=normalize_denominator_type(entry.get("denominator_type")),
        impact_polarity=_clean_optional(entry.get("impact_polarity")),
        energy_source=_clean_optional(entry.get("energy_source")) or _infer_energy_source(text),
    )


def validate_canonical_semantics(entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        normalize_denominator_type(entry.get("denominator_type"))
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def validate_registry_semantics(entries: list[dict[str, Any]]) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for entry in entries:
        entry_errors = validate_canonical_semantics(entry)
        if entry_errors:
            errors[str(entry.get("canonical_id") or "<missing>")] = entry_errors
    return errors


def semantic_alias_gate(
    *,
    fact_semantics: SemanticTyping,
    canonical_semantics: SemanticTyping,
    fact_unit_family: str | None,
    canonical_unit_family: str | None,
) -> AliasGateResult:
    block_reasons: list[str] = []
    unit_compatible = _unit_compatible(fact_unit_family, canonical_unit_family)
    subject_compatible = (
        bool(fact_semantics.metric_subject)
        and bool(canonical_semantics.metric_subject)
        and fact_semantics.metric_subject == canonical_semantics.metric_subject
    )
    role_compatible = (
        bool(fact_semantics.metric_role)
        and bool(canonical_semantics.metric_role)
        and fact_semantics.metric_role == canonical_semantics.metric_role
    )
    denominator_compatible = fact_semantics.denominator_type == canonical_semantics.denominator_type
    flow_direction_compatible = (
        fact_semantics.flow_direction != "unknown"
        and canonical_semantics.flow_direction != "unknown"
        and fact_semantics.flow_direction == canonical_semantics.flow_direction
    )
    energy_source_compatible = _energy_source_compatible(fact_semantics, canonical_semantics)

    if not canonical_semantics.is_typed:
        block_reasons.append("canonical_untyped")
    if not fact_semantics.is_typed:
        block_reasons.append("fact_untyped")
    if not unit_compatible:
        block_reasons.append("unit_mismatch")
    if fact_semantics.metric_subject and canonical_semantics.metric_subject and not subject_compatible:
        block_reasons.append("subject_mismatch")
    if fact_semantics.metric_role and canonical_semantics.metric_role and not role_compatible:
        block_reasons.append("role_mismatch")
    if not denominator_compatible:
        block_reasons.append("denominator_mismatch")
    if (
        role_compatible
        and subject_compatible
        and fact_semantics.flow_direction != canonical_semantics.flow_direction
    ):
        block_reasons.append("near_duplicate_risk")
    if not energy_source_compatible:
        block_reasons.append("energy_source_mismatch")

    block_reasons = [reason for reason in block_reasons if reason in BLOCK_REASONS]
    eligible = (
        not block_reasons
        and unit_compatible
        and subject_compatible
        and role_compatible
        and denominator_compatible
        and flow_direction_compatible
        and energy_source_compatible
    )
    return AliasGateResult(
        eligible=eligible,
        block_reasons=tuple(dict.fromkeys(block_reasons)),
        unit_compatible=unit_compatible,
        subject_compatible=subject_compatible,
        role_compatible=role_compatible,
        denominator_compatible=denominator_compatible,
        flow_direction_compatible=flow_direction_compatible,
    )


def infer_fact_semantics_draft(fact: dict[str, Any]) -> SemanticTyping:
    raw = fact.get("raw") if isinstance(fact.get("raw"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            raw.get("raw_name"),
            raw.get("metric_core"),
            fact.get("metric"),
            fact.get("metric_definition"),
            fact.get("evidence"),
            raw.get("source_sentence"),
        )
    ).lower()
    subject = _infer_subject(text)
    role = _infer_role(text)
    denominator = _infer_denominator(text)
    if denominator and role not in {"intensity", "generation", "consumption", "withdrawal"}:
        role = "intensity"
    return SemanticTyping(
        metric_subject=subject,
        metric_role=role,
        denominator_type=denominator,
        impact_polarity=_infer_polarity(role),
        energy_source=_infer_energy_source(text),
    )


def _energy_source_compatible(fact_semantics: SemanticTyping, canonical_semantics: SemanticTyping) -> bool:
    if fact_semantics.metric_subject != "energy" or canonical_semantics.metric_subject != "energy":
        return True
    if fact_semantics.metric_role != "consumption" or canonical_semantics.metric_role != "consumption":
        return True
    fact_source = fact_semantics.energy_source
    canonical_source = canonical_semantics.energy_source
    if not fact_source and not canonical_source:
        return True
    return bool(fact_source and canonical_source and fact_source == canonical_source)


def unit_family_for_fact(fact: dict[str, Any]) -> str:
    raw = fact.get("raw") if isinstance(fact.get("raw"), dict) else {}
    raw_name = str(raw.get("raw_name") or fact.get("metric") or "")
    raw_unit = str(raw.get("raw_unit") or fact.get("unit") or "")
    raw_value = raw.get("raw_value", fact.get("value"))
    unit_family = unit_family_from_raw_unit(raw_unit)
    if unit_family != "unknown":
        return unit_family
    if re.search(r"\b(count|number of|no\. of|employees?|workers?|stores?|outlets?|sites?|plants?|units?)\b", raw_name, re.I):
        return "count"
    if str(raw_value or "").strip().endswith("%"):
        return "percentage"
    return "unknown"


def _unit_compatible(fact_unit_family: str | None, canonical_unit_family: str | None) -> bool:
    fact_family = str(fact_unit_family or "unknown").lower()
    canonical_family = str(canonical_unit_family or "unknown").lower()
    if "unknown" in {fact_family, canonical_family}:
        return False
    return are_unit_families_compatible(fact_family, canonical_family)


def _clean_optional(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _infer_subject(text: str) -> str | None:
    checks = [
        ("water", r"\b(water|groundwater|rainwater|effluent|wastewater)\b"),
        ("energy", r"\b(energy|electricity|fuel|renewable|non[-\s]?renewable|solar|biomass|gj|kwh)\b"),
        ("emissions", r"\b(ghg|emissions?|co2|co2e|carbon|scope\s*[123])\b"),
        ("waste", r"\b(waste|landfill|recycl|disposal|disposed|epr|plastic)\b"),
        ("employee", r"\b(employee|employees|associate|associates|workforce|staff)\b"),
        ("worker", r"\b(worker|workers|contract\s+labou?r)\b"),
        ("distribution", r"\b(distribution|outlet|outlets|reach|stores?|retail)\b"),
        ("sourcing", r"\b(sourcing|sourced|supplier|suppliers|farmer|farmers|procured|procurement)\b"),
        ("safety", r"\b(safety|injury|injuries|fatalit|ltifr|trir|incident)\b"),
        ("product", r"\b(product|products|launch|launches|portfolio|nutrition|innovation)\b"),
    ]
    for subject, pattern in checks:
        if re.search(pattern, text, re.I):
            return subject
    return None


def _infer_role(text: str) -> str | None:
    checks = [
        ("recharge", r"\b(recharg|replenish|restor|conservation potential|water capacity created)\b"),
        ("withdrawal", r"\b(withdrawal|withdrawn|surface water|groundwater|third party water)\b"),
        ("consumption", r"\b(consumption|consumed|used|usage|use)\b"),
        ("generation", r"\b(generated|generation|produced)\b"),
        ("recycling", r"\b(recycl|reuse|reused|recovery|recovered|collected and recycled)\b"),
        ("disposal", r"\b(dispos|landfill|incinerat)\b"),
        ("intensity", r"\b(intensity|per\s+unit|per\s+tonne|per\s+ton|per\s+mt|per\s+rupee|per\s+revenue|per\s+employee|/\s*(?:mt|tonne|revenue|employee))\b"),
        ("coverage", r"\b(coverage|covered|trained|certified|geofenced|share|percentage|%)\b"),
        ("count", r"\b(number of|count|headcount|stores?|outlets?|sites?|plants?|units?|employees?|workers?)\b"),
    ]
    for role, pattern in checks:
        if re.search(pattern, text, re.I):
            return role
    return None


def _infer_denominator(text: str) -> str | None:
    for denominator, pattern in INTENSITY_DENOMINATOR_PATTERNS:
        if pattern.search(text):
            return denominator
    return None


def _infer_energy_source(text: str) -> str | None:
    if re.search(r"\bnon[-\s]?renewable\b", text, re.I):
        return "non_renewable"
    if re.search(r"\brenewable\b", text, re.I):
        return "renewable"
    if re.search(r"\b(total|overall)\s+energy\b|\benergy\s+(?:consumed|consumption|use|used)\b", text, re.I):
        return "total"
    return None


def _infer_polarity(role: str | None) -> str | None:
    return {
        "recharge": "positive",
        "harvest": "positive",
        "conservation": "positive",
        "reduction": "positive",
        "recycling": "positive",
        "recovery": "positive",
        "diversion": "positive",
        "withdrawal": "resource_use",
        "consumption": "resource_use",
        "investment": "resource_use",
        "generation": "negative",
        "disposal": "negative",
        "discharge": "negative",
    }.get(str(role or ""))
