import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import calendar
import re
from datetime import date
from typing import Any

from pass1_lean_schema import DIMENSION_TYPE, FACT_TYPE, PERIOD_TYPE
from normalizer_guardrails import extract_primary_numeric
from pass1_validate_fixes import (
    check_unambiguous_fixed,
    derive_segment_flag_fixed,
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
_FY_EXPLICIT_RE = re.compile(r"\bFY\s*([12][90]\d{2})\b", re.IGNORECASE)
_FY_RANGE_RE = re.compile(r"\b(?:FY\s*)?([12][90]\d{2})\s*[-/]\s*(\d{2}|\d{4})\b", re.IGNORECASE)
_CY_EXPLICIT_RE = re.compile(r"\bCY\s*([12][90]\d{2})\b", re.IGNORECASE)
_AS_OF_YEAR_RE = re.compile(r"\bas of\b[^.:\n]{0,40}\b([12][90]\d{2})\b", re.IGNORECASE)
_TARGET_YEAR_RE = re.compile(r"\bby\s+([12][90]\d{2})\b", re.IGNORECASE)
_SINCE_YEAR_RE = re.compile(r"\bsince\s+([12][90]\d{2})\b", re.IGNORECASE)
_POINT_IN_TIME_RE = re.compile(r"\b(as of|as at|at year end|at the end of)\b", re.IGNORECASE)
_PARTIAL_RE = re.compile(
    r"\b(q[1-4]|quarter|half year|h1|h2|nine months|nine-month|month ended|months ended|ytd|year to date)\b",
    re.IGNORECASE,
)
_BASELINE_RE = re.compile(r"\bbaseline\b", re.IGNORECASE)
_BOOLEAN_RE = re.compile(r"\b(yes|no|achieved|not achieved|true|false|complied|non-complied|certified)\b", re.IGNORECASE)
_COUNT_HINT_RE = re.compile(
    r"\b(number of|count of|employees?|workers?|facilities?|factories?|plants?|sites?|stores?|outlets?|patents?|hours?)\b",
    re.IGNORECASE,
)

PERIOD_TYPE_ALIASES = {
    "annual": "full_year",
    "quarterly": "partial",
    "half_year": "partial",
    "ttm": "cumulative",
}

FACT_TYPE_ALIASES = {
    "actual": "measurement",
    "comparative_reference": "measurement",
    "guidance": "target",
    "estimate": "target",
    "delta": "measurement",
}

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


def _add_months(anchor: date, month_offset: int, *, end_of_month: bool = False) -> date:
    month_index = (anchor.month - 1) + month_offset
    year = anchor.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = calendar.monthrange(year, month)[1] if end_of_month else 1
    return date(year, month, day)

def _month_name_to_number(value: str) -> int | None:
    return _MONTHS.get(str(value or "").strip().lower())


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day is not None else None


def normalize_period_type(fact: dict[str, Any], context: dict[str, Any]) -> str:
    raw = str(fact.get("period_type") or "").strip().lower()
    raw = PERIOD_TYPE_ALIASES.get(raw, raw)
    if raw in PERIOD_TYPE:
        return raw

    combined = " ".join(
        str(fact.get(key) or "")
        for key in ("raw_period", "source_sentence", "baseline_year", "fact_type")
    )
    if _BASELINE_RE.search(combined) or str(fact.get("baseline_year") or "").strip():
        return "baseline"
    if str(fact.get("fact_type") or "").strip().lower() == "target" or _TARGET_YEAR_RE.search(combined):
        return "target"
    if _SINCE_YEAR_RE.search(combined):
        return "cumulative"
    if _POINT_IN_TIME_RE.search(combined):
        return "point_in_time"
    if _PARTIAL_RE.search(combined):
        return "partial"

    inferred_label = _normalize_period_token(
        str(fact.get("raw_period") or "") or str(fact.get("source_sentence") or ""),
        context,
    )
    if inferred_label:
        return "full_year"
    return "unknown"


def normalize_fact_type(fact: dict[str, Any]) -> str:
    raw = str(fact.get("fact_type") or "").strip().lower()
    raw = FACT_TYPE_ALIASES.get(raw, raw)
    if raw in FACT_TYPE:
        return raw

    combined = " ".join(
        str(fact.get(key) or "")
        for key in ("raw_name", "source_sentence", "raw_unit")
    )
    if _BASELINE_RE.search(combined) or str(fact.get("baseline_year") or "").strip():
        return "baseline"
    if _TARGET_YEAR_RE.search(combined) or re.search(r"\b(target|goal|aim|commit(?:ment)?|net zero by)\b", combined, re.IGNORECASE):
        return "target"
    if _BOOLEAN_RE.search(combined):
        return "boolean"
    if "%" in combined or re.search(r"\b(percent|percentage|ratio|share|rate|intensity)\b", combined, re.IGNORECASE):
        return "ratio"
    if _COUNT_HINT_RE.search(combined) or re.search(r"\b(count|counts|nos?|number)\b", combined, re.IGNORECASE):
        return "count"
    return "measurement"


def _quarter_bounds(label_text: str, fy_year: int, fye_month: int) -> tuple[date, date] | None:
    quarter_match = _QUARTER_RE.search(label_text)
    if not quarter_match:
        if re.search(r"\bh1\b|half year", label_text, re.IGNORECASE):
            quarter = "H1"
        elif re.search(r"\bh2\b", label_text, re.IGNORECASE):
            quarter = "H2"
        else:
            return None
    else:
        quarter = f"Q{quarter_match.group(1)}"

    fy_start, _ = _fy_bounds(fy_year, fye_month)
    if quarter == "Q1":
        start = fy_start
        end = _add_months(fy_start, 2, end_of_month=True)
        return start, end
    if quarter == "Q2":
        start = _add_months(fy_start, 3)
        end = _add_months(fy_start, 5, end_of_month=True)
        return start, end
    if quarter == "Q3":
        start = _add_months(fy_start, 6)
        end = _add_months(fy_start, 8, end_of_month=True)
        return start, end
    if quarter == "Q4":
        start = _add_months(fy_start, 9)
        _, fy_end = _fy_bounds(fy_year, fye_month)
        return start, fy_end
    if quarter == "H1":
        start = fy_start
        end = _add_months(fy_start, 5, end_of_month=True)
        return start, end
    if quarter == "H2":
        start = _add_months(fy_start, 6)
        _, fy_end = _fy_bounds(fy_year, fye_month)
        return start, fy_end
    return None


def resolve_period(fact: dict[str, Any], context: dict[str, Any]) -> tuple[str | None, str | None, str]:
    label = str(fact.get("period") or fact.get("raw_period") or "").strip()
    ptype = normalize_period_type(fact, context)
    fye_month = _fiscal_year_end_month(context)

    label_token = _normalize_period_token(label, context)
    if not label_token and ptype in {"full_year", "baseline"}:
        label_token = _normalize_period_token(str(context.get("primary_period") or ""), context)

    if ptype in {"full_year", "baseline"} and label_token:
        year = int(label_token[2:])
        if label_token.startswith("FY"):
            start, end = _fy_bounds(year, fye_month)
        else:
            start = date(year, 1, 1)
            end = date(year, 12, 31)
        return _iso(start), _iso(end), "resolved"

    if ptype == "target":
        target_match = _TARGET_YEAR_RE.search(" ".join([label, str(fact.get("source_sentence") or "")]))
        if target_match:
            year = int(target_match.group(1))
            return None, f"{year}-12-31", "resolved"
        return None, None, "unresolvable"

    if ptype == "cumulative":
        since_match = _SINCE_YEAR_RE.search(" ".join([label, str(fact.get("source_sentence") or "")]))
        end_label = _normalize_period_token(str(context.get("primary_period") or ""), context)
        end_date = None
        if end_label:
            year = int(end_label[2:])
            if end_label.startswith("FY"):
                _, end_obj = _fy_bounds(year, fye_month)
            else:
                end_obj = date(year, 12, 31)
            end_date = _iso(end_obj)
        if since_match:
            start_year = int(since_match.group(1))
            return f"{start_year}-01-01", end_date, "resolved"
        return None, end_date, "inferred" if end_date else "unresolvable"

    if ptype == "point_in_time":
        year_match = _AS_OF_YEAR_RE.search(label) or _AS_OF_YEAR_RE.search(str(fact.get("source_sentence") or ""))
        if year_match:
            year = int(year_match.group(1))
            month_match = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b", label + " " + str(fact.get("source_sentence") or ""), re.IGNORECASE)
            month = _month_name_to_number(month_match.group(1)) if month_match else 12
            day = calendar.monthrange(year, month)[1]
            point = date(year, month, day)
            return _iso(point), _iso(point), "resolved"
        return None, None, "unresolvable"

    if ptype == "partial":
        token = label_token or _normalize_period_token(str(fact.get("source_sentence") or ""), context)
        if token:
            year = int(token[2:])
            if token.startswith("FY"):
                bounds = _quarter_bounds(label + " " + str(fact.get("source_sentence") or ""), year, fye_month)
                if bounds:
                    return _iso(bounds[0]), _iso(bounds[1]), "resolved"
            if token.startswith("CY") and _QUARTER_RE.search(label + " " + str(fact.get("source_sentence") or "")):
                q = int(_QUARTER_RE.search(label + " " + str(fact.get("source_sentence") or "")).group(1))
                month_start = 1 + (q - 1) * 3
                start = date(year, month_start, 1)
                end_month = month_start + 2
                end = date(year, end_month, calendar.monthrange(year, end_month)[1])
                return _iso(start), _iso(end), "resolved"
        return None, None, "inferred"

    return None, None, "unresolvable"

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


def _normalize_period_token(text: str, context: dict[str, Any], *, default_kind: str | None = None) -> str | None:
    text = str(text or "").strip()
    if not text:
        return None

    match = _FY_EXPLICIT_RE.search(text)
    if match:
        return f"FY{match.group(1)}"

    match = _CY_EXPLICIT_RE.search(text)
    if match:
        return f"CY{match.group(1)}"

    match = _FY_RANGE_RE.search(text)
    if match:
        start_year = int(match.group(1))
        end_part = match.group(2)
        if len(end_part) == 4:
            end_year = int(end_part)
        else:
            end_year = (start_year // 100) * 100 + int(end_part)
            if end_year < start_year:
                end_year += 100
        kind = default_kind or ("FY" if str(context.get("primary_period") or "").upper().startswith("FY") else "CY")
        return f"{kind}{end_year}"

    match = _AS_OF_YEAR_RE.search(text)
    if match:
        kind = default_kind or ("FY" if str(context.get("primary_period") or "").upper().startswith("FY") else "CY")
        return f"{kind}{match.group(1)}"

    match = _YEAR_RE.search(text)
    if match:
        year = match.group(0)
        if re.search(r"\b(calendar year|calendar)\b", text, re.IGNORECASE):
            return f"CY{year}"
        kind = default_kind or ("FY" if str(context.get("primary_period") or "").upper().startswith("FY") else "CY")
        return f"{kind}{year}"

    return None


_NON_YEAR_PERIOD_STRINGS = frozenset({
    "current", "ongoing", "present", "now", "currently",
    "current year", "this year", "annual", "yearly",
    "as of date", "as at", "to date", "cumulative",
    "rolling", "continuous", "permanent", "indefinite",
    "open ended", "open-ended", "no fixed date", "not applicable",
    "year", "period", "reporting period", "reporting year",
})

_OPEN_ENDED_STRINGS = frozenset({
    "open ended", "open-ended", "no fixed date", "indefinite", "permanent",
})


def infer_period_label(fact: dict[str, Any], context: dict[str, Any]) -> tuple[str, str]:
    raw_period = str(fact.get("raw_period") or "").strip()
    source_sentence = str(fact.get("source_sentence") or "").strip()
    fact_type = str(fact.get("fact_type") or "").strip().lower()

    # Non-year strings should not trigger source_sentence year scanning.
    # e.g. raw_period="current" → source sentence may contain a regulatory year
    # (like "Rules 2016") which would be wrongly picked up as the period.
    raw_period_clean = raw_period.lower().strip(".,;: ")
    if raw_period_clean in _NON_YEAR_PERIOD_STRINGS:
        # Target facts with explicitly open-ended language
        if fact_type == "target" and raw_period_clean in _OPEN_ENDED_STRINGS:
            return "open_ended", "inferred"
        # Everything else: fall back to report year
        primary_period = str(
            context.get("fiscal_period")
            or context.get("primary_period")
            or context.get("period")
            or ""
        ).strip()
        inferred = _normalize_period_token(primary_period, context)
        if inferred:
            return inferred, "inferred"
        filing_year = context.get("filing_year")
        if filing_year:
            kind = "FY" if str(context.get("primary_period") or "").upper().startswith("FY") else "CY"
            return f"{kind}{filing_year}", "inferred"
        return "", "inferred"

    extracted = _normalize_period_token(raw_period, context)
    if extracted:
        return extracted, "extracted"

    extracted = _normalize_period_token(source_sentence, context)
    if extracted:
        return extracted, "extracted"

    primary_period = str(
        context.get("fiscal_period")
        or context.get("primary_period")
        or context.get("period")
        or ""
    ).strip()
    inferred = _normalize_period_token(primary_period, context)
    if inferred:
        return inferred, "inferred"

    filing_year = context.get("filing_year")
    if filing_year:
        kind = "FY" if str(context.get("primary_period") or "").upper().startswith("FY") else "CY"
        return f"{kind}{filing_year}", "inferred"
    return "", "inferred"


def run_checks(fact: dict[str, Any], resolution: str, prior_values: dict[str, float] | None = None) -> tuple[dict[str, bool], bool, bool]:
    raw_value = fact.get("raw_value")
    raw_unit = str(fact.get("raw_unit") or "").strip()
    fact_type = normalize_fact_type(fact)
    src = str(fact.get("source_sentence") or "")
    num = parse_number(raw_value)
    has_range = bool(_RANGE_HINT.search(str(raw_value or ""))) and "from" not in str(raw_value or "").lower()
    checks = {
        "check_specific_number": num is not None and not has_range,
        "check_unit_clear": _has_clear_unit(fact, raw_unit),
        "check_period_determinable": resolution in {"resolved", "inferred"},
        "check_is_actual": fact_type in FACT_TYPE,
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
    fact_type = normalize_fact_type(fact)
    period_type = normalize_period_type({**fact, "fact_type": fact_type}, context)
    fact["fact_type"] = fact_type
    fact["period_type"] = period_type
    period_label, _ = infer_period_label(fact, context)
    start, end, resolution = resolve_period({**fact, "period": period_label}, context)
    if start or end:
        explicit_range_in_text = bool(
            re.search(r"\bfrom\s+\d{4}\b.*\bto\s+\d{4}\b", str(fact.get("source_sentence") or ""), re.IGNORECASE)
            or re.search(r"\b(april|january).*\b(march|december)\b", str(fact.get("source_sentence") or ""), re.IGNORECASE)
        )
        period_confidence = "extracted" if explicit_range_in_text else "inferred"
    else:
        period_confidence = "inferred"
    checks, extreme, restatement = run_checks(fact, resolution, prior_values)
    # target, boolean, and count facts legitimately have no fixed period —
    # a future commitment, a yes/no compliance flag, or a current-state count
    # (e.g. "9 manufacturing locations") should not be dropped for unknown period.
    if fact_type in {"target", "boolean", "count"}:
        checks["check_period_determinable"] = True
    flags = derive_flags(fact)
    failed, rescue_possible, rescue_note, decision, confidence = decide(checks, resolution)
    full = dict(fact)
    full.update({
        "resolved_period_start": start,
        "resolved_period_end": end,
        "period_resolution": resolution,
        "period": period_label,
        "period_start": start,
        "period_end": end,
        "period_type": period_type,
        "period_confidence": period_confidence,
        "fact_type": fact_type,
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
