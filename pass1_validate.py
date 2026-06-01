import calendar
import re
from datetime import date
from typing import Any

from pass1_lean_schema import DIMENSION_TYPE, PERIOD_TYPE
from normalizer_guardrails import extract_primary_numeric
from pass1_validate_fixes import (
    check_unambiguous_fixed,
    derive_segment_flag_fixed,
    resolve_period_fixed,
)

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_QUARTER_RE = re.compile(r"\bQ([1-4])\b", re.IGNORECASE)
_RANGE_HINT = re.compile(r"\b(to|[-??])\b|\bbetween\b|~|approx", re.IGNORECASE)
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_RESTATE_RE = re.compile(
    r"\b(restat(?:ed|ement)?|revis(?:ed|ion)?|reclassif(?:y|ied|ication)|recast)\b",
    re.IGNORECASE,
)
_SUBTOTAL_RE = re.compile(r"^(total|subtotal|combined|consolidated)\b", re.IGNORECASE)
_MIX_SHARE_RE = re.compile(
    r"\b(market share|share gain|share loss|penetration|mix|digital sales|e-?commerce|ecommerce)\b",
    re.IGNORECASE,
)
_CONTRIBUTION_RE = re.compile(
    r"\b(pricing|price|volume/?mix|volume mix|fx|foreign exchange|currency|acquisition|divestiture|contribution)\b",
    re.IGNORECASE,
)
_OPERATIONAL_RE = re.compile(
    r"\b(store|transaction|ticket|member|loyalty|volume|market|traffic|digital|e-?commerce|"
    r"comparable sales|same-store|sales per square foot|square foot|markets|buyback|dividend|"
    r"capacity utilization|oee|equipment effectiveness|wastage|changeover|fulfillment|dispatch|"
    r"complaint resolution|basket size|repeat purchase|inventory turnover|training|attrition|"
    r"injury|water|recycling|renewable|supplier|touchpoints|outlets)\b",
    re.IGNORECASE,
)

def _fiscal_year_end_month(context: dict[str, Any]) -> int:
    raw = str(context.get("fiscal_year_end_month", "December")).strip().lower()
    if raw.isdigit():
        n = int(raw)
        return n if 1 <= n <= 12 else 12
    return _MONTHS.get(raw, 12)

def _fy_bounds(fy_year: int, fye_month: int) -> tuple[date, date]:
    end = date(fy_year, fye_month, calendar.monthrange(fy_year, fye_month)[1])
    if fye_month == 12:
        start = date(fy_year, 1, 1)
    else:
        start = date(fy_year - 1, fye_month + 1, 1)
    return start, end

def resolve_period(fact: dict[str, Any], context: dict[str, Any]) -> tuple[str | None, str | None, str]:
    ptype = str(fact.get("period_type") or "").strip().lower()
    if ptype not in PERIOD_TYPE:
        fact = dict(fact)
        fact["period_type"] = "unknown"
    return resolve_period_fixed(fact, context)

def parse_number(raw_value: Any) -> float | None:
    if raw_value is None:
        return None
    s = str(raw_value).strip()
    num, _ = extract_primary_numeric(s)
    return num


def _sanitize_string_field(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"[,\.;:\-\?\(\)\[\]\{\}/\\]+", text):
        return ""
    return text


def _source_has_number(source_sentence: Any) -> bool:
    return bool(_NUM_RE.search(str(source_sentence or "")))

_IMPLICIT_COUNT_UNIT_RE = re.compile(
    r"\b(lines?|plants?|facilities?|sites?|factories?|warehouses?|suppliers?|"
    r"incidents?|injuries?|products?|skus?|outlets?|stores?|hubs?|depots?)\b",
    re.IGNORECASE,
)


def _has_clear_unit(fact: dict[str, Any], raw_unit: str) -> bool:
    if raw_unit and raw_unit.lower() not in {"", "n/a", "unknown", "not stated"}:
        return True
    unit_context = " ".join(
        str(fact.get(key) or "")
        for key in ("raw_name", "metric_core", "parent_metric_hint", "source_sentence")
    )
    return bool(_IMPLICIT_COUNT_UNIT_RE.search(unit_context))


def run_checks(fact: dict[str, Any], resolution: str, prior_values: dict[str, float] | None = None) -> tuple[dict[str, bool], bool, bool]:
    raw_value = fact.get("raw_value")
    raw_unit = str(fact.get("raw_unit") or "").strip()
    fact_type = str(fact.get("fact_type") or "").strip().lower()
    src = str(fact.get("source_sentence") or "")
    num = parse_number(raw_value)
    has_range = bool(_RANGE_HINT.search(str(raw_value or ""))) and "from" not in str(raw_value or "").lower()
    checks = {
        "check_specific_number": num is not None and not has_range,
        "check_unit_clear": _has_clear_unit(fact, raw_unit),
        "check_period_determinable": resolution in {"resolved", "inferred"},
        "check_is_actual": fact_type not in {"guidance", "estimate"},
        "check_unambiguous": check_unambiguous_fixed(fact),
    }
    extreme = False
    if prior_values and num is not None:
        key = str(fact.get("raw_name") or "").strip().lower()
        prev = prior_values.get(key)
        if prev not in (None, 0):
            try:
                if abs((num - prev) / prev) > 1.0:
                    extreme = True
            except ZeroDivisionError:
                pass
    restatement = bool(_RESTATE_RE.search(src))
    return checks, extreme, restatement

def derive_flags(fact: dict[str, Any]) -> dict[str, bool]:
    gft = str(fact.get("graph_fact_type") or "").strip()
    dim = str(fact.get("dimension_type") or "none").strip()
    if dim not in DIMENSION_TYPE:
        dim = "none"
    return {
        "breakdown_flag": gft == "breakdown_fact" or (dim not in {"", "none"}),
        "driver_flag": bool(fact.get("driver_phrase")),
        "component_flag": bool(fact.get("parent_metric_hint")),
        "contribution_flag": gft == "contribution_metric",
    }


def _reconcile_raw_label_type(fact: dict[str, Any]) -> str:
    raw_name = str(fact.get("raw_name") or "").strip()
    source_sentence = str(fact.get("source_sentence") or "").strip()
    dimension_type = str(fact.get("dimension_type") or "none").strip().lower()
    dimension_member = str(fact.get("dimension_member") or "").strip()
    original = str(fact.get("raw_label_type") or "").strip()

    if dimension_type != "none" and dimension_member:
        return "dimension_member"
    if _SUBTOTAL_RE.search(raw_name):
        return "subtotal_label"
    if original == "narrative_metric_phrase":
        return original
    if source_sentence and raw_name and raw_name.strip() != source_sentence.strip():
        raw_name_lower = raw_name.lower()
        source_lower = source_sentence.lower()
        if raw_name_lower in source_lower and not _SUBTOTAL_RE.search(raw_name):
            return "narrative_metric_phrase"
    if original in {"metric_label", "dimension_member", "subtotal_label", "narrative_metric_phrase"}:
        return original
    return "metric_label"


def _reconcile_graph_fact_type(fact: dict[str, Any]) -> str:
    raw_name = str(fact.get("raw_name") or "").strip()
    source_sentence = str(fact.get("source_sentence") or "").strip()
    raw_unit = str(fact.get("raw_unit") or "").strip()
    dimension_type = str(fact.get("dimension_type") or "none").strip().lower()
    dimension_member = str(fact.get("dimension_member") or "").strip()
    original = str(fact.get("graph_fact_type") or "").strip()
    combined = " ".join(
        part for part in [raw_name, source_sentence, str(fact.get("parent_metric_hint") or ""), raw_unit] if part
    )

    if original == "specialized_note_metric":
        return original
    if _MIX_SHARE_RE.search(combined):
        return "mix_share_metric"
    if _CONTRIBUTION_RE.search(combined):
        return "contribution_metric"
    if dimension_type != "none" and dimension_member:
        return "breakdown_fact"
    if original == "operational_metric":
        return original
    if _OPERATIONAL_RE.search(combined):
        return "operational_metric"
    if original in {
        "financial_metric",
        "operational_metric",
        "breakdown_fact",
        "mix_share_metric",
        "contribution_metric",
        "specialized_note_metric",
        "table_scaffold",
    }:
        return original
    return "financial_metric"


def reconcile_fact_semantics(fact: dict[str, Any]) -> dict[str, Any]:
    reconciled = dict(fact)
    reconciled["raw_name"] = _sanitize_string_field(reconciled.get("raw_name"))
    reconciled["raw_value"] = _sanitize_string_field(reconciled.get("raw_value"))
    reconciled["raw_unit"] = _sanitize_string_field(reconciled.get("raw_unit"))
    reconciled["raw_period"] = _sanitize_string_field(reconciled.get("raw_period"))
    reconciled["raw_label_type"] = _reconcile_raw_label_type(reconciled)
    reconciled["graph_fact_type"] = _reconcile_graph_fact_type(reconciled)
    return reconciled

def decide(checks: dict[str, bool], resolution: str) -> tuple[list[str], bool, str | None, str, str]:
    failed = [name for name, ok in checks.items() if not ok]
    n = len(failed)
    unresolved = resolution == "unresolvable"
    rescue_possible = ("check_unambiguous" in failed) and n <= 2
    rescue_note = None
    if n == 0 and not unresolved:
        decision, confidence = "keep", "high"
    elif (n <= 2 and rescue_possible) or (unresolved and rescue_possible):
        decision, confidence = "rescue", "medium"
        rescue_note = "infer parent metric / period from surrounding context"
    elif n >= 3 or (unresolved and not rescue_possible):
        decision, confidence = "drop", "low"
    else:
        decision, confidence = "rescue", "medium"
        rescue_note = "review failed checks: " + ", ".join(failed)
    return failed, rescue_possible, rescue_note, decision, confidence

def enrich_fact(fact: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    fact = reconcile_fact_semantics(fact)
    prior_values = context.get("prior_values")
    start, end, resolution = resolve_period(fact, context)
    checks, extreme, restatement = run_checks(fact, resolution, prior_values)
    flags = derive_flags(fact)
    failed, rescue_possible, rescue_note, decision, confidence = decide(checks, resolution)
    full = dict(fact)
    full.update({
        "resolved_period_start": start,
        "resolved_period_end": end,
        "period_resolution": resolution,
        **flags,
        **checks,
        "extreme_movement_flag": extreme,
        "restatement_flag": restatement,
        "confidence": confidence,
        "failed_checks": failed,
        "rescue_possible": rescue_possible,
        "rescue_note": rescue_note,
        "adjustment_note": None,
        "decision": decision,
    })
    full["segment_flag"] = derive_segment_flag_fixed(full)
    full["segment_name"] = str(full.get("dimension_member") or "")
    full["check_unambiguous_meaning"] = "yes" if full.get("check_unambiguous", False) else "no"
    if not full.get("check_specific_number") and not _source_has_number(full.get("source_sentence")):
        full["confidence"] = "low"
        full["decision"] = "drop"
        full["rescue_possible"] = False
        full["rescue_note"] = "no quantitative value present in source"
    return full

def enrich_facts(lean_facts: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    return [enrich_fact(f, context) for f in lean_facts]
