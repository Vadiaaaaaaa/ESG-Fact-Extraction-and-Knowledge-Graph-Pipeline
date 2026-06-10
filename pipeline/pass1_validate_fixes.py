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

_YEAR_RE = re.compile(r"(19|20)\d{2}")
_FY_RANGE_RE = re.compile(r"\b(?:FY\s*)?((?:19|20)\d{2})\s*[-/]\s*(\d{2})\b", re.IGNORECASE)
_QUARTER_RE = re.compile(r"\bQ([1-4])\b", re.IGNORECASE)
_H1_RE = re.compile(r"\b(first half|1h|h1|first six months)\b", re.IGNORECASE)
_H2_RE = re.compile(r"\b(second half|2h|h2|second six months)\b", re.IGNORECASE)
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}


def fiscal_year_end_month_from_context(context):
    raw = str(context.get("fiscal_year_end_month", "December")).strip().lower()
    if raw.isdigit():
        month = int(raw)
        return month if 1 <= month <= 12 else 12
    return _MONTHS.get(raw, 12)


def _add_months(d, n):
    m0 = d.month - 1 + n
    y = d.year + m0 // 12
    m = m0 % 12 + 1
    return date(y, m, 1)


def _fy_bounds(fy_year, fye_month):
    end = date(fy_year, fye_month, calendar.monthrange(fy_year, fye_month)[1])
    start = date(fy_year, 1, 1) if fye_month == 12 else date(fy_year - 1, fye_month + 1, 1)
    return start, end


def _extract_fiscal_year_end(text):
    text = str(text or "")
    range_match = _FY_RANGE_RE.search(text)
    if range_match:
        start_year = int(range_match.group(1))
        end_suffix = int(range_match.group(2))
        century = start_year // 100
        end_year = (century * 100) + end_suffix
        if end_year < start_year:
            end_year += 100
        return end_year
    year_match = _YEAR_RE.search(text)
    return int(year_match.group(0)) if year_match else None


def resolve_period_fixed(fact, context):
    raw = (fact.get("raw_period") or "").strip()
    ptype = (fact.get("period_type") or "").strip().lower()
    fye_month = fiscal_year_end_month_from_context(context)

    context_period = (
        context.get("fiscal_period")
        or context.get("primary_period")
        or context.get("period")
        or ""
    )
    year = _extract_fiscal_year_end(raw)
    inferred = year is None
    if year is None:
        year = _extract_fiscal_year_end(context_period)
    if year is None:
        return None, None, "unresolvable"
    fy_start, fy_end = _fy_bounds(year, fye_month)

    if ptype == "annual":
        return fy_start.isoformat(), fy_end.isoformat(), ("inferred" if inferred else "resolved")
    if ptype == "quarterly":
        quarter = _QUARTER_RE.search(raw)
        if not quarter:
            return None, None, "unresolvable"
        q_index = int(quarter.group(1))
        start = _add_months(fy_start, 3 * (q_index - 1))
        end_first = _add_months(start, 2)
        end = date(end_first.year, end_first.month, calendar.monthrange(end_first.year, end_first.month)[1])
        return start.isoformat(), end.isoformat(), "resolved"
    if ptype == "half_year":
        if _H2_RE.search(raw):
            start = _add_months(fy_start, 6)
            return start.isoformat(), fy_end.isoformat(), "resolved"
        end_first = _add_months(fy_start, 5)
        end = date(end_first.year, end_first.month, calendar.monthrange(end_first.year, end_first.month)[1])
        return fy_start.isoformat(), end.isoformat(), ("resolved" if _H1_RE.search(raw) else "inferred")
    if ptype == "ttm":
        quarter = _QUARTER_RE.search(raw)
        if quarter:
            q_index = int(quarter.group(1))
            q_start = _add_months(fy_start, 3 * (q_index - 1))
            end_first = _add_months(q_start, 2)
            end = date(end_first.year, end_first.month, calendar.monthrange(end_first.year, end_first.month)[1])
        else:
            end = fy_end
        start = _add_months(end, -11)
        return start.isoformat(), end.isoformat(), ("resolved" if quarter or not inferred else "inferred")
    if ptype == "point_in_time":
        return fy_end.isoformat(), fy_end.isoformat(), ("inferred" if inferred else "resolved")
    if ptype in {"", "unknown"} and context_period:
        return fy_start.isoformat(), fy_end.isoformat(), "inferred"
    return None, None, "unresolvable"


def derive_segment_flag_fixed(fact):
    scope = (fact.get("scope") or "").strip().lower()
    dimension_type = (fact.get("dimension_type") or "none").strip().lower()
    return scope == "sub_entity" or dimension_type in {
        "segment",
        "geography",
        "brand",
        "channel",
        "product_category",
    }


def check_unambiguous_fixed(fact):
    label_type = (fact.get("raw_label_type") or "").strip().lower()
    has_parent = bool(fact.get("parent_metric_hint"))
    if label_type in {"metric_label", "narrative_metric_phrase", "subtotal_label"}:
        return True
    if label_type == "dimension_member":
        return has_parent
    is_dimensioned = (fact.get("dimension_type") or "none") != "none"
    return not (is_dimensioned and not has_parent)
