import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import re
from difflib import SequenceMatcher

ILLEGAL_SCALE_FAMILIES = {
    "percentage",
    "ratio",
    "percentage_points",
    "duration",
    "time",
    "per_area",
    "per_unit",
    "rate",
    "energy",
    "volume",
    "weight",
}

_UNIT_FAMILY_RULES = [
    ("percentage_points", re.compile(r"\b(bps|bp|basis points?|pp|ppt|percentage points?)\b", re.I)),
    ("percentage", re.compile(r"%|\bpercent|\bpct\b", re.I)),
    ("time", re.compile(r"\b(minutes?|mins?|hours?|hrs?|hr|seconds?|sec|days?)\b", re.I)),
    ("energy", re.compile(r"\b(gj|mj|kj|kwh|mwh|megawatt[-\s]?hours?|kilowatt[-\s]?hours?|joules?)\b", re.I)),
    ("volume", re.compile(r"\b(kilolit(res?|ers?)|kl|lit(res?|ers?)|l|cubic meters?|m3|gallons?)\b", re.I)),
    ("weight", re.compile(r"\b(metric tons?|metric tonnes?|tons?|tonnes?|kg|kilograms?|grams?|g)\b", re.I)),
    ("per_area", re.compile(r"per\s*(sq|square)\s*(ft|foot|feet|m|meter)|/\s*sq", re.I)),
    ("per_unit", re.compile(r"\b(k?l|lit(re|er)s?)\s*/\s*ton|\bk?l\s*per\s*ton|\bper serving\b", re.I)),
    ("duration", re.compile(r"\b(year|yr|month|day|week|quarter|hour|hr)s?\b", re.I)),
    ("monetary", re.compile(r"\$|₹|\bUSD\b|\bEUR\b|\bGBP\b|\bINR\b|dollars?|euros?|pounds?|rupees?|crore|lakh", re.I)),
    ("ratio", re.compile(r"\b\d+(?:\.\d+)?x\b|\b(x|times|turns|ratio|factor|per|index)\b|×", re.I)),
    ("count", re.compile(r"\b(stores?|members?|markets?|customers?|users?|employees?|units?|transactions?|outlets?|lines?|facilities?|factories?|impressions?|products?|variants?|suppliers?|sites?|awards?)\b", re.I)),
]

_SCALE_TOKENS = [
    (1_000_000_000_000, re.compile(r"\btrillion\b|\btn\b", re.I)),
    (1_000_000_000, re.compile(r"\bbillion\b|\bbn\b", re.I)),
    (1_000_000, re.compile(r"\bmillion\b|\bmm\b", re.I)),
    (10_000_000, re.compile(r"\bcrore\b|\bcr\b", re.I)),
    (100_000, re.compile(r"\blakh\b|\blac\b", re.I)),
    (1_000, re.compile(r"\bthousand\b|\bk\b", re.I)),
]

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_GUIDANCE_RE = re.compile(r"\b(guidance|expect|expects|forecast|outlook|target|project(?:ed)?|anticipated?)\b", re.I)
_MOVEMENT_HINT_RE = re.compile(
    r"\b(improv|reduc|declin|rose|grew|increas|decreas|reached|stood at|operated at|reduced from|improved from)\b",
    re.I,
)


def unit_family_from_raw_unit(raw_unit, canonical_expected=None):
    text = (raw_unit or "").strip()
    for family, rx in _UNIT_FAMILY_RULES:
        if rx.search(text):
            return family
    if canonical_expected:
        return canonical_expected
    return "unknown"


_METRIC_CORE_HIGH_RISK_PREFIXES = (
    "improved",
    "increased",
    "decreased",
    "reached",
    "grew",
    "fell",
    "rose",
    "declined",
    "achieved",
    "reduced",
    "expanded",
    "contracted",
)

_METRIC_CORE_SAFE_ACRONYM_PREFIXES = {
    "co2",
    "ghg",
    "oee",
    "esg",
    "pm",
    "mtbf",
    "mttr",
    "kpi",
    "roi",
    "otif",
    "ota",
    "osa",
    "trir",
    "ltir",
    "iot",
    "ai",
    "vfd",
    "led",
}

_METRIC_CORE_STOPWORDS = {
    "of",
    "in",
    "to",
    "from",
    "the",
    "a",
    "an",
    "by",
    "with",
    "for",
    "on",
    "at",
    "is",
    "was",
    "are",
    "were",
}


def metric_core_risk(metric_core: str, raw_name: str = "") -> str:
    """Returns "low", "medium", or "high"."""
    text = str(metric_core or "").strip()
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9]+", lowered)
    original_tokens = re.findall(r"[A-Za-z0-9]+", text)
    first_token = original_tokens[0] if original_tokens else ""
    first_token_lower = first_token.lower()
    first_token_is_safe_acronym = first_token_lower in _METRIC_CORE_SAFE_ACRONYM_PREFIXES
    first_token_is_upper = bool(first_token) and first_token.isupper()
    numeric_chars = sum(char.isdigit() for char in lowered)
    total_chars = max(len(lowered), 1)
    verb_prefix_high_risk = (
        bool(first_token_lower)
        and not first_token_is_safe_acronym
        and not first_token_is_upper
        and first_token_lower in _METRIC_CORE_HIGH_RISK_PREFIXES
    )

    if (
        verb_prefix_high_risk
        or (any(char.isdigit() for char in lowered) and not first_token_is_safe_acronym)
        or len(tokens) > 6
        or (numeric_chars / total_chars) > 0.15
    ):
        return "high"

    raw_name_text = str(raw_name or "").strip().lower()
    if (
        any(token in _METRIC_CORE_STOPWORDS for token in tokens)
        or len(lowered) > 40
        or (
            raw_name_text
            and SequenceMatcher(None, lowered, raw_name_text).ratio() > 0.92
            and len(re.findall(r"[a-z0-9]+", raw_name_text)) > 5
        )
    ):
        return "medium"

    return "low"


def extract_primary_numeric(raw_value, source_sentence=""):
    raw_text = str(raw_value or "").strip()
    nums = _NUM_RE.findall(raw_text)
    if len(nums) == 1:
        return float(nums[0].replace(",", "")), "single_number"
    if len(nums) == 2:
        combined = f"{raw_text} {source_sentence or ''}".lower()
        if "from" in combined and "to" in combined and not _GUIDANCE_RE.search(combined):
            return float(nums[-1].replace(",", "")), "movement_second_number"
        if " to " in raw_text.lower() and _MOVEMENT_HINT_RE.search(source_sentence or "") and not _GUIDANCE_RE.search(combined):
            return float(nums[-1].replace(",", "")), "movement_second_number"
    return None, "no_single_number"


def parse_value_and_scale(raw_value, raw_unit, source_sentence=""):
    text = f"{raw_value or ''} {raw_unit or ''}"
    numeric, numeric_reason = extract_primary_numeric(raw_value, source_sentence)
    if numeric is None:
        return None, 1, numeric_reason
    for factor, rx in _SCALE_TOKENS:
        if rx.search(text):
            return numeric, factor, f"{numeric_reason}:scale_in_raw:{factor}"
    return numeric, 1, numeric_reason


def normalize_value_safe(fact, canonical_expected_family=None):
    raw_value = fact.get("raw_value")
    raw_unit = fact.get("raw_unit")
    source_sentence = fact.get("source_sentence", "")
    family = unit_family_from_raw_unit(raw_unit, canonical_expected_family)
    numeric, scale, scale_source = parse_value_and_scale(raw_value, raw_unit, source_sentence)

    out = {
        "unit_family": family,
        "raw_numeric": numeric,
        "applied_scale": 1,
        "normalized_value": numeric,
        "scale_source": scale_source,
        "rejected_reason": None,
    }
    if numeric is None:
        out["rejected_reason"] = "no_single_number"
        return out

    raw_unit_text = str(raw_unit or "").lower()
    if family == "percentage":
        if "%" in raw_unit_text or "percent" in raw_unit_text or "pct" in raw_unit_text:
            out["applied_scale"] = 0.01
            out["normalized_value"] = numeric * 0.01
        return out

    if scale > 1 and family in ILLEGAL_SCALE_FAMILIES:
        out["rejected_reason"] = f"illegal_scale_for_family:{family}"
        out["normalized_value"] = numeric
        return out

    out["applied_scale"] = scale
    out["normalized_value"] = numeric * scale
    return out


_PASS1_TO_PASS2_TYPE = {
    "financial_metric": "financial_metric",
    "operational_metric": "operational_metric",
    "breakdown_fact": "operational_metric",
    "mix_share_metric": "operational_metric",
    "contribution_metric": "contribution_metric",
    "specialized_note_metric": "operational_metric",
    "table_scaffold": "operational_metric",
}


def fact_type_hint_from_pass1(fact):
    graph_fact_type = (fact.get("graph_fact_type") or "").strip()
    return _PASS1_TO_PASS2_TYPE.get(graph_fact_type, "operational_metric")


def _dimension_text_from_fact(fact):
    return " ".join(
        str(fact.get(key) or "")
        for key in (
            "raw_name",
            "metric_core",
            "metric_definition",
            "source_sentence",
            "context",
        )
    )


def _infer_dimension_from_text(text):
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())
    normalized = " ".join(normalized.split())

    packaging_patterns = [
        (r"\bcategory 1\b.*\brigids?\b", "rigids"),
        (r"\brigids?\b.*\bcategory 1\b", "rigids"),
        (r"\bcategory 2\b.*\bflexibles?\b", "flexibles"),
        (r"\bflexibles?\b.*\bcategory 2\b", "flexibles"),
        (r"\bcategory 3\b.*\bmulti layered packaging\b", "multi-layered packaging"),
        (r"\bmulti layered packaging\b.*\bcategory 3\b", "multi-layered packaging"),
        (r"\bcategory 1 packaging\b", "category 1 packaging"),
        (r"\bcategory 2 packaging\b", "category 2 packaging"),
        (r"\bcategory 3 packaging\b", "category 3 packaging"),
    ]
    for pattern, member in packaging_patterns:
        if re.search(pattern, normalized):
            return {"dimension_type": "packaging_type", "dimension_member": member}

    if re.search(r"\bfemale\b|\bwomen\b", normalized):
        return {"dimension_type": "gender", "dimension_member": "female"}
    if re.search(r"\bmale\b|\bmen\b", normalized):
        return {"dimension_type": "gender", "dimension_member": "male"}

    countries = [
        ("outside the united states", "Outside United States"),
        ("outside united states", "Outside United States"),
        ("united states", "United States"),
        ("u s", "United States"),
        ("usa", "United States"),
        ("ukraine", "Ukraine"),
        ("russia", "Russia"),
        ("bangladesh", "Bangladesh"),
        ("vietnam", "Vietnam"),
        ("egypt", "Egypt"),
        ("india", "India"),
        ("indonesia", "Indonesia"),
        ("china", "China"),
        ("brazil", "Brazil"),
        ("mexico", "Mexico"),
        ("canada", "Canada"),
        ("united kingdom", "United Kingdom"),
        ("germany", "Germany"),
        ("france", "France"),
        ("australia", "Australia"),
    ]
    for token, label in countries:
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            return {"dimension_type": "geography", "dimension_member": label}
    return None


def dimension_from_fact(fact):
    dimension = fact.get("dimension")
    if isinstance(dimension, dict):
        dimension_type = dimension.get("dimension_type")
        dimension_member = dimension.get("dimension_member")
        if dimension_type and dimension_member:
            return {
                "dimension_type": str(dimension_type),
                "dimension_member": str(dimension_member),
            }

    dimension_type = (fact.get("dimension_type") or "none").strip()
    dimension_member = fact.get("dimension_member")
    if dimension_type != "none" and dimension_member:
        return {
            "dimension_type": dimension_type,
            "dimension_member": dimension_member,
        }
    return _infer_dimension_from_text(_dimension_text_from_fact(fact))


def _financial_or_operational(graph_fact_type):
    graph_fact_type = (graph_fact_type or "").strip()
    if graph_fact_type == "financial_metric":
        return "financial"
    if graph_fact_type in {"operational_metric", "mix_share_metric", "breakdown_fact"}:
        return "operational"
    return "unknown"


def are_unit_families_compatible(unit_family_fact, unit_family_canonical, fact_class=None):
    if unit_family_fact == "percentage_points" and unit_family_canonical == "percentage":
        return True
    if unit_family_fact == "percentage" and unit_family_canonical == "percentage_points":
        return True

    if fact_class in ("change", "transition") and unit_family_fact in ("percentage", "percentage_points"):
        return True

    if (
        unit_family_fact != "unknown"
        and unit_family_canonical != "unknown"
        and unit_family_fact != unit_family_canonical
    ):
        return False
    return True


def match_is_compatible(source_fact, candidate, fuzzy_score=None, auto_accept_threshold=0.90):
    source_family = unit_family_from_raw_unit(
        source_fact.get("raw_unit"),
        source_fact.get("expected_unit_family"),
    )
    candidate_family = candidate.get("unit_family", "unknown")
    allowed_unit_families = list(candidate.get("allowed_unit_families") or [])
    source_fact_class = str(source_fact.get("fact_class") or "").strip()

    if allowed_unit_families and any(
        are_unit_families_compatible(
            source_family,
            str(unit_family or "unknown"),
            fact_class=source_fact_class or None,
        )
        for unit_family in allowed_unit_families
    ):
        candidate_family = source_family

    if not are_unit_families_compatible(
        source_family,
        candidate_family,
        fact_class=source_fact_class or None,
    ):
        return False, f"unit_family_mismatch:{source_family}!={candidate_family}"

    source_class = _financial_or_operational(source_fact.get("graph_fact_type"))
    candidate_class = _financial_or_operational(candidate.get("graph_fact_type"))
    if (
        source_class != "unknown"
        and candidate_class != "unknown"
        and source_class != candidate_class
    ):
        return False, f"class_mismatch:{source_class}!={candidate_class}"

    allowed_fact_classes = list(candidate.get("allowed_fact_classes") or [])
    if allowed_fact_classes and source_fact_class and source_fact_class not in allowed_fact_classes:
        return False, f"fact_class_mismatch:{source_fact_class}"

    if fuzzy_score is not None and fuzzy_score < auto_accept_threshold:
        return False, f"fuzzy_below_threshold:{fuzzy_score:.2f}"

    return True, "compatible"
