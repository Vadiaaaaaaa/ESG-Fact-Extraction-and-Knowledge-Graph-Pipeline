import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import argparse
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from definitions import set_registry as set_definition_registry, top_definition_matches
from gold_set import SCORE_FLOOR, SCORE_MARGIN, compute_match_score, compute_match_signals
from metric_registry_seed import REGISTRY as SEED_REGISTRY, canonical_definition_for_entry, build_alias_index as build_seed_alias_index
from models import PASS1_SCHEMA_VERSION
from normalizer_guardrails import (
    dimension_from_fact,
    fact_type_hint_from_pass1,
    match_is_compatible,
    metric_core_risk,
    unit_family_from_raw_unit,
)
from provisional_review import write_review_files
from review_memory import load_review_memory, lookup_review_decision
from semantic_registry import infer_fact_semantics_draft, semantic_alias_gate, semantic_typing_from_registry, unit_family_for_fact
from unit_normaliser import normalise_fact_value

try:
    from ontology_shortlist import shortlist_candidates as _shortlist_candidates
except ImportError:
    _shortlist_candidates = None


PASS2_SYSTEM_PROMPT = """You normalize Pass 1 financial facts into canonical metrics.

Context:
- Company: {company}
- Period: {document_period}
- Fiscal year end month: {fiscal_year_end_month}
- Filing type: {filing_type}
- Default currency: {default_currency}

Canonical registry:
{metric_registry}

Rules:
- Facts arrive in a compact input shape. Return one output object per input fact in the same order.
- If input decision is "drop", set normalization_decision="drop".
- Match raw_name to the best canonical metric using canonical_name, category, fact_type_hint, and candidate_shortlist when provided.
- Exact name match => mapping_confidence="high".
- Clear semantic match with consistent unit type => "medium".
- Ambiguous or unit-type-conflict match => "low".
- No credible match => mapping_confidence="no_match", is_new_metric=true, proposed_canonical_id=snake_case(raw_name), normalization_decision="new_metric".
- If raw_name indicates growth/change/increase/decline/vs/YoY/QoQ, prefer a *_growth_rate metric when one exists.
- If raw_name contains adjusted/underlying/normalised/reported/statutory/recurring/non-GAAP/pro forma, map to the base metric and set variant_flag=true plus variant_label.
- Segment facts map to the same canonical_id as consolidated facts. Do not invent segment-specific metrics.
- If input decision is "rescue", set normalization_decision="partial" even if mapping is otherwise strong.
- If fact_type_hint suggests a breakdown_fact, do not force a plain canonical metric unless the candidate_shortlist clearly supports it.

Unit rules:
- Use the pipeline unit normaliser output as the authoritative value layer.
- Preserve raw_value and raw_unit_string exactly as extracted.
- Populate normalised_value, normalised_unit_symbol, and normalisation_confidence on every row.
- If unit normalisation fails or needs context, keep normalised_value=null and mention that in mapping_note.

Decision rules:
- normalized: mapping_confidence is high or medium and input decision was "keep"
- partial: low/no_match, failed/needs_context unit normalisation, unknown currency, or input decision was "rescue"
- new_metric: is_new_metric=true and input decision was "keep"
- drop: input decision was "drop"

Return only a JSON array. No markdown.
Each output object must contain:
- fact_id
- canonical_id
- mapping_confidence
- variant_flag
- variant_label
- currency
- normalization_decision"""

CORROBORATION_THRESHOLD = 0.45

PASS2_USER_PROMPT = """Normalize these facts:
{pass1_facts_batch}"""


MODEL = "gpt-4.1-mini"
BATCH_SIZE = 20
TEST_BATCHES = 3
SAMPLE_FACTS = 200
API_TIMEOUT_SECONDS = 120
RETRY_WAIT_SECONDS = 5
RATE_LIMIT_RETRY_WAIT_SECONDS = 60
MAX_CONCURRENT_CALLS = 1
TIEBREAKER_LLM_CALL_COUNT = 0

CANDIDATE_BLACKLIST = {
    "total_assets": [
        "fair value of",
        "derivative asset",
        "short term investment",
        "prepayment",
        "current income tax",
        "right of use",
        "goodwill",
        "intangible",
        "deferred tax asset",
        "total current asset",
        "total non current asset",
        "financial asset",
        "employee benefit",
        "asset held for sale",
        "property plant and equipment",
        "other assets",
        "goodwill and intangible asset",
        "total liabilities and equity",
        "capital",
        "invested capital",
        "other financial assets",
        "face value",
        "environmental",
        "total derivatives",
        "total non current assets",
        "legal and indirect tax",
        "total unrecognized assets",
        "goodwill and intangible assets",
    ],
    "net_income": [
        "retranslation",
        "hedge",
        "remeasurement",
        "comprehensive income",
        "reclassified",
        "defined benefit",
    ],
    "depreciation_amortization": [
        "impairment",
    ],
    "customer_acquisition_cost": [
        "acquisition of",
        "business acquisition",
        "asset acquisition",
        "acquired company",
        "acquired business",
    ],
    "cdp_water_score": [
        "cdp climate",
        "climate score",
    ],
}

TOTAL_ASSETS_ALLOWED_NAMES = {
    "assets",
    "asset",
    "total assets",
    "total asset",
    "total current assets",
    "total current asset",
    "total non current assets",
    "total non current asset",
}

PASS2_DEFAULTS = {
    "canonical_id": None,
    "canonical_name": None,
    "canonical_category": "",
    "canonical_subcategory": None,
    "mapping_confidence": "no_match",
    "mapping_note": "",
    "variant_flag": False,
    "variant_label": "",
    "is_new_metric": False,
    "proposed_canonical_id": "",
    "currency": "",
    "normalised_value": None,
    "normalised_unit_symbol": None,
    "normalisation_confidence": "failed",
    "raw_unit_string": None,
    "range_low_normalized": None,
    "range_high_normalized": None,
    "unit_canonical": "",
    "unit_from_registry": None,
    "normalization_decision": "partial",
    "alias_resolved": False,
}

STALE_DEFINITION_THRESHOLD = 0.20


def _snake_case(value: str) -> str:
    cleaned = []
    previous_was_separator = False
    for char in (value or "").strip().lower():
        if char.isalnum():
            cleaned.append(char)
            previous_was_separator = False
        elif not previous_was_separator:
            cleaned.append("_")
            previous_was_separator = True
    return "".join(cleaned).strip("_")


def _metric_core_from_definition(metric_definition: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", str(metric_definition or "").lower())
    stopwords = {
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
        "to",
        "for",
        "in",
        "on",
        "by",
        "with",
        "within",
        "during",
        "that",
        "this",
        "is",
        "are",
        "be",
        "as",
        "at",
        "it",
        "its",
        "their",
        "metric",
        "measure",
        "measures",
        "amount",
        "rate",
        "share",
        "number",
        "total",
        "associated",
        "reported",
        "given",
        "specific",
    }
    tokens = [token for token in text.split() if token not in stopwords]
    return _snake_case(" ".join(tokens[:5]))


def _build_match_fact(fact: dict[str, Any]) -> dict[str, Any]:
    raw = fact.get("raw", {})
    raw_name = str(raw.get("raw_name") or fact.get("metric", "") or "")
    metric_definition = str(raw.get("metric_definition") or fact.get("metric_definition") or "")
    base_metric_core = str(
        raw.get("metric_core")
        or raw.get("parent_metric_hint")
        or raw.get("raw_name")
        or fact.get("metric", "")
        or ""
    )
    if metric_definition and metric_core_risk(base_metric_core, raw_name) == "high":
        definition_core = _metric_core_from_definition(metric_definition)
        metric_core = definition_core or base_metric_core
    else:
        metric_core = base_metric_core
    return {
        "raw_name": raw_name,
        "metric_core": metric_core,
        "metric_definition": metric_definition,
        "raw_unit": str(raw.get("raw_unit") or fact.get("unit", "") or ""),
        "fact_class": str(raw.get("fact_class") or "scalar_kpi"),
        "direction": str(raw.get("direction") or ""),
        "baseline_year": raw.get("baseline_year"),
        "source_sentence": str(raw.get("source_sentence") or fact.get("evidence", "") or ""),
        "scope_level": str(raw.get("scope_level") or raw.get("scope") or "unknown"),
        "parent_metric_hint": str(raw.get("parent_metric_hint") or ""),
    }


_SCOPE3_CATEGORY_NAMES = {
    "1": "Purchased Goods",
    "2": "Capital Goods",
    "3": "Fuel Activities",
    "4": "Upstream Transportation",
    "5": "Waste Generated",
    "6": "Business Travel",
    "7": "Employee Commuting",
    "8": "Upstream Leased Assets",
    "9": "Downstream Transportation",
    "10": "Processing of Sold Products",
    "11": "Use of Sold Products",
    "12": "End-of-Life Treatment",
    "13": "Downstream Leased Assets",
    "14": "Franchises",
    "15": "Investments",
}

_SCOPE3_CATEGORY_PATTERNS = {
    "1": re.compile(r"\bpurchased goods\b", re.I),
    "2": re.compile(r"\bcapital goods\b", re.I),
    "3": re.compile(r"\bfuel activit(?:y|ies)\b", re.I),
    "4": re.compile(r"\bupstream transportation\b", re.I),
    "5": re.compile(r"\bwaste generated\b", re.I),
    "6": re.compile(r"\bbusiness travel\b", re.I),
    "7": re.compile(r"\bemployee commuting\b", re.I),
    "8": re.compile(r"\bupstream leased assets\b", re.I),
    "9": re.compile(r"\bdownstream transportation\b", re.I),
    "10": re.compile(r"\bprocessing of sold products\b", re.I),
    "11": re.compile(r"\buse of sold products\b", re.I),
    "12": re.compile(r"\bend[- ]of[- ]life treatment\b", re.I),
    "13": re.compile(r"\bdownstream leased assets\b", re.I),
    "14": re.compile(r"\bfranchises\b", re.I),
    "15": re.compile(r"\binvestments?\b", re.I),
}


def _scope3_sub_category(match_fact: dict[str, Any]) -> str | None:
    text = " ".join(
        str(match_fact.get(key) or "")
        for key in ("raw_name", "metric_core", "metric_definition", "source_sentence")
    )
    lower_text = text.lower()
    has_scope3_context = bool(
        "scope 3" in lower_text
        or re.search(r"\b(?:ghg|emissions|tco2e|co2e)\b", lower_text)
    )
    if not has_scope3_context:
        return None

    category_match = re.search(r"\bcategory\s*(\d{1,2})\b", lower_text)
    if category_match and category_match.group(1) in _SCOPE3_CATEGORY_NAMES:
        number = category_match.group(1)
        return f"Category {number} {_SCOPE3_CATEGORY_NAMES[number]}"

    for number, pattern in _SCOPE3_CATEGORY_PATTERNS.items():
        if pattern.search(text):
            return f"Category {number} {_SCOPE3_CATEGORY_NAMES[number]}"
    return None


def _proposed_canonical_id_for_fact(fact: dict[str, Any]) -> str:
    raw_name = str(fact.get("raw_name") or "")
    metric_core = str(fact.get("metric_core") or "")
    parent_metric_hint = str(fact.get("parent_metric_hint") or "")
    risk = metric_core_risk(metric_core, raw_name)

    if metric_core and risk in {"low", "medium"}:
        source = metric_core
    elif parent_metric_hint:
        source = parent_metric_hint
    elif metric_core:
        source = metric_core
    else:
        source = raw_name
    return _snake_case(source)


def accept_match(
    best_candidate: dict[str, Any] | None,
    second_best_score: float,
    fact: dict[str, Any],
) -> tuple[str, str]:
    """
    Returns (decision, reason) where decision is one of:
      "accept"       â€” map to best_candidate["canonical_id"]
      "provisional"  â€” mint a new provisional canonical
      "quarantine"   â€” high-risk metric_core, do not mint into live registry
    """
    metric_core = str(fact.get("metric_core") or "")
    raw_name = str(fact.get("raw_name") or "")
    risk = metric_core_risk(metric_core, raw_name)

    if best_candidate is None or float(best_candidate.get("score", 0.0)) < SCORE_FLOOR:
        if risk == "high":
            return ("quarantine", "no match + high-risk metric_core")
        return ("provisional", "no match, mint from metric_core")
    if (float(best_candidate.get("score", 0.0)) - second_best_score) < SCORE_MARGIN:
        return ("provisional", "ambiguous match, margin too small")
    alias_score = float(best_candidate.get("alias_score") or 0.0)
    metric_core_score = float(best_candidate.get("metric_core_score") or 0.0)
    if max(alias_score, metric_core_score) < CORROBORATION_THRESHOLD:
        return ("provisional", "definition-only match, lacks raw/core corroboration")
    return ("accept", "score and margin passed")


def _candidate_passes_corroboration(candidate: dict[str, Any] | None) -> bool:
    if not candidate:
        return False
    alias_score = float(candidate.get("alias_score") or 0.0)
    metric_core_score = float(candidate.get("metric_core_score") or 0.0)
    return max(alias_score, metric_core_score) >= CORROBORATION_THRESHOLD


def _margin_tied_candidates(top_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not top_candidates:
        return []
    top_score = float(top_candidates[0].get("score") or 0.0)
    tied = [
        candidate
        for candidate in top_candidates
        if (top_score - float(candidate.get("score") or 0.0)) < SCORE_MARGIN
    ]
    return tied[:3]


def _source_text_for_tiebreaker(match_fact: dict[str, Any], fact: dict[str, Any] | None = None) -> str:
    raw = fact.get("raw", {}) if isinstance(fact, dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            match_fact.get("raw_name"),
            match_fact.get("metric_core"),
            match_fact.get("source_sentence"),
            raw.get("source_sentence"),
            fact.get("evidence") if isinstance(fact, dict) else "",
        )
    ).lower()


def _canonical_matches_disambiguator(canonical_id: str, token_key: str) -> bool:
    canonical_id = str(canonical_id or "").lower()
    if token_key == "scope_1_2":
        return "combined_scope_1_2" in canonical_id or "scope_1_2" in canonical_id
    if token_key == "scope_3":
        return canonical_id.startswith("scope_3_") or canonical_id == "scope_3_emissions"
    if token_key == "scope_1":
        return canonical_id == "scope_1_emissions"
    if token_key == "scope_2":
        return canonical_id == "scope_2_emissions"
    if token_key == "recycled_content":
        return canonical_id == "recycled_plastic_content_share"
    return False


def _layer1_token_tiebreaker(
    match_fact: dict[str, Any],
    tied_candidates: list[dict[str, Any]],
    fact: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    text = _source_text_for_tiebreaker(match_fact, fact)
    checks = [
        ("scope_1_2", "scope 1+2", re.compile(r"\bscope\s*1\s*(?:\+|&|and)\s*(?:scope\s*)?2\b", re.I)),
        ("scope_3", "scope 3", re.compile(r"\bscope\s*3\b", re.I)),
        ("scope_1", "scope 1", re.compile(r"\bscope\s*1\b", re.I)),
        ("scope_2", "scope 2", re.compile(r"\bscope\s*2\b", re.I)),
        ("recycled_content", "PCR", re.compile(r"\bpcr\b", re.I)),
        ("recycled_content", "post-consumer recycled", re.compile(r"\bpost[-\s]?consumer\s+recycled\b", re.I)),
        ("recycled_content", "recycled content", re.compile(r"\brecycled\s+content\b", re.I)),
    ]
    for token_key, token_label, pattern in checks:
        if not pattern.search(text):
            continue
        matches = [
            candidate
            for candidate in tied_candidates
            if _canonical_matches_disambiguator(str(candidate.get("canonical_id") or ""), token_key)
        ]
        if len(matches) == 1:
            return matches[0], token_label
    return None, None


def _layer1_baseline_reduction_tiebreaker(
    match_fact: dict[str, Any],
    tied_candidates: list[dict[str, Any]],
    fact: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    text = _source_text_for_tiebreaker(match_fact, fact)
    has_reduction = re.search(r"\b(reduction|reduced|decrease|decreased|lower|lowered|decline|declined)\b", text, re.I)
    has_baseline = re.search(r"\b(base\s+year|baseline|compared\s+to\s+(?:the\s+)?base|as\s+compared\s+to\s+(?:the\s+)?base)\b", text, re.I)
    if not (has_reduction and has_baseline):
        return None, None

    target_id = ""
    token_label = ""
    if re.search(r"\b(water|freshwater|groundwater)\b", text, re.I):
        target_id = "water_reduction_vs_baseline"
        token_label = "baseline water reduction"
    elif re.search(r"\b(energy|electricity|fuel|power)\b", text, re.I):
        target_id = "energy_reduction_vs_baseline"
        token_label = "baseline energy reduction"
    elif re.search(r"\b(ghg|greenhouse|emission|emissions|carbon|co2|transport)\b", text, re.I):
        target_id = "ghg_reduction_vs_baseline"
        token_label = "baseline ghg reduction"
    if not target_id:
        return None, None

    matches = [
        candidate
        for candidate in tied_candidates
        if str(candidate.get("canonical_id") or "") == target_id
    ]
    if len(matches) == 1:
        return matches[0], token_label
    return None, None


def _distribution_reach_tie_is_underspecified(
    match_fact: dict[str, Any],
    tied_candidates: list[dict[str, Any]],
    fact: dict[str, Any] | None = None,
) -> bool:
    tied_ids = {str(candidate.get("canonical_id") or "") for candidate in tied_candidates}
    if "distribution_reach" not in tied_ids:
        return False
    if not ({"direct_distribution_reach", "rural_distribution_reach"} & tied_ids):
        return False
    text = _source_text_for_tiebreaker(match_fact, fact)
    if re.search(r"\b(direct|directly|rural|village|villages|overall|total|company[-\s]?wide|entire)\b", text, re.I):
        return False
    return True


def _no_candidate_fit_guard(
    match_fact: dict[str, Any],
    tied_candidates: list[dict[str, Any]],
    fact: dict[str, Any] | None = None,
) -> str:
    tied_ids = {str(candidate.get("canonical_id") or "") for candidate in tied_candidates}
    text = _source_text_for_tiebreaker(match_fact, fact)
    if "market_share" in tied_ids and re.search(
        r"\b(business|portfolio|brands?)\b.{0,80}\bwinning\b.{0,80}\bmarket\s+shares?\b",
        text,
        re.I,
    ):
        return "Evidence describes share of business or portfolio winning market share, not an actual market-share figure."
    if "consumer_complaints" in tied_ids and re.search(
        r"\b(asci|advertis(?:e|ement|ing)|ad(?:s)?\s+complaints?|advertising\s+regulator)\b",
        text,
        re.I,
    ):
        return "Evidence describes advertising-regulator complaints, not consumer product or service complaints."
    return ""


_TIEBREAKER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "normalization_tiebreaker",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "choice": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["choice", "reason"],
            "additionalProperties": False,
        },
    },
}


def _call_tiebreaker_llm(
    match_fact: dict[str, Any],
    fact: dict[str, Any],
    tied_candidates: list[dict[str, Any]],
    registry_lookup: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    global TIEBREAKER_LLM_CALL_COUNT
    TIEBREAKER_LLM_CALL_COUNT += 1
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from openai import OpenAI

    candidate_payload = []
    valid_ids = set()
    for candidate in tied_candidates:
        canonical_id = str(candidate.get("canonical_id") or "")
        valid_ids.add(canonical_id)
        registry_entry = registry_lookup.get(canonical_id, {})
        candidate_payload.append(
            {
                "canonical_id": canonical_id,
                "canonical_definition": str(registry_entry.get("canonical_definition") or ""),
            }
        )

    raw = fact.get("raw", {}) if isinstance(fact, dict) else {}
    fact_payload = {
        "raw_name": str(match_fact.get("raw_name") or ""),
        "metric_definition": str(match_fact.get("metric_definition") or ""),
        "evidence": str(match_fact.get("source_sentence") or raw.get("source_sentence") or fact.get("evidence") or ""),
        "value": str(raw.get("raw_value") or fact.get("value") or ""),
        "unit": str(match_fact.get("raw_unit") or raw.get("raw_unit") or fact.get("unit") or ""),
    }
    system_prompt = """You adjudicate a normalization tie between already-valid candidate metrics.
Before choosing, first decide whether the fact genuinely belongs to one of these canonicals at all.
If the evidence describes something meaningfully different from every candidate's definition, even if one is the closest, return AMBIGUOUS.
Only choose a canonical if the fact clearly and fully belongs to it. A close-but-not-right match must return AMBIGUOUS.
Choose a canonical ONLY if the fact clearly belongs to it.
If the candidates are genuinely indistinguishable for this fact, or the fact could reasonably belong to more than one, return AMBIGUOUS.
Do NOT guess. AMBIGUOUS is the correct and safe answer when unsure. Prefer AMBIGUOUS over a low-confidence pick.
Examples:
- Fact: "75% of business winning value and volume market shares"; candidate: market_share. Return AMBIGUOUS because this is a share of the business gaining market share, not an actual market-share figure.
- Fact: "complaints filed with ASCI about advertisements"; candidate: consumer_complaints. Return AMBIGUOUS because advertising-regulator complaints are not consumer product or service complaints.
You may only choose one of the provided canonical_id values or AMBIGUOUS."""
    user_prompt = json.dumps(
        {
            "fact": fact_payload,
            "candidates": candidate_payload,
            "response_schema": {"choice": "<canonical_id or AMBIGUOUS>", "reason": "one short sentence"},
        },
        ensure_ascii=False,
        indent=2,
    )
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=API_TIMEOUT_SECONDS, max_retries=1)
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format=_TIEBREAKER_RESPONSE_FORMAT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        timeout=API_TIMEOUT_SECONDS,
    )
    try:
        payload = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return "AMBIGUOUS", "Layer 2 returned malformed JSON."
    choice = str(payload.get("choice") or "").strip()
    reason = " ".join(str(payload.get("reason") or "").split()).strip() or "No reason returned."
    if choice in valid_ids or choice == "AMBIGUOUS":
        return choice, reason
    return "AMBIGUOUS", f"Layer 2 returned invalid candidate {choice!r}."


def _semantic_tiebreaker_conflict(
    candidate: dict[str, Any] | None,
    fact: dict[str, Any],
    registry_lookup: dict[str, dict[str, Any]],
) -> str | None:
    if not candidate:
        return None
    canonical_id = str(candidate.get("canonical_id") or "")
    registry_entry = registry_lookup.get(canonical_id)
    if not registry_entry:
        return None

    canonical_semantics = semantic_typing_from_registry(registry_entry)
    if not canonical_semantics.is_typed:
        return None

    fact_semantics = infer_fact_semantics_draft(fact)
    if not fact_semantics.is_typed:
        return None

    gate = semantic_alias_gate(
        fact_semantics=fact_semantics,
        canonical_semantics=canonical_semantics,
        fact_unit_family=unit_family_for_fact(fact),
        canonical_unit_family=str(registry_entry.get("unit_family") or registry_entry.get("unit") or "unknown"),
    )
    blocking_reasons = [
        reason
        for reason in gate.block_reasons
        if reason in {"subject_mismatch", "role_mismatch", "energy_source_mismatch"}
    ]
    if not blocking_reasons:
        return None
    return ", ".join(blocking_reasons)


def _try_margin_tiebreaker(
    *,
    decision: str,
    reason: str,
    top_candidates: list[dict[str, Any]],
    match_fact: dict[str, Any],
    fact: dict[str, Any],
    registry_lookup: dict[str, dict[str, Any]],
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]]:
    best_candidate = top_candidates[0] if top_candidates else None
    top_id = str(best_candidate.get("canonical_id") or "") if best_candidate else ""
    top_score = float(best_candidate.get("score") or 0.0) if best_candidate else 0.0
    audit: dict[str, Any] = {"resolution_method": "provisional"}
    if (
        decision != "provisional"
        or reason != "ambiguous match, margin too small"
        or not best_candidate
        or float(best_candidate.get("score") or 0.0) < SCORE_FLOOR
        or not _candidate_passes_corroboration(best_candidate)
    ):
        return decision, reason, best_candidate, audit

    tied_candidates = _margin_tied_candidates(top_candidates)
    if len(tied_candidates) < 2:
        return decision, reason, best_candidate, audit

    layer1_choice, token = _layer1_token_tiebreaker(match_fact, tied_candidates, fact)
    if layer1_choice is None:
        layer1_choice, token = _layer1_baseline_reduction_tiebreaker(match_fact, tied_candidates, fact)
    if layer1_choice is not None:
        semantic_conflict = _semantic_tiebreaker_conflict(layer1_choice, fact, registry_lookup)
        if semantic_conflict:
            audit = {
                "resolution_method": "provisional",
                "tiebreaker_layer": "layer1",
                "tiebreaker_reason": (
                    f"Layer 1 token match declined due to semantic incompatibility: {semantic_conflict}."
                ),
                "tiebreaker_token": token,
            }
            return decision, reason, best_candidate, audit
        audit = {
            "resolution_method": "tiebreaker_layer1_token",
            "tiebreaker_layer": "layer1",
            "tiebreaker_reason": f"Exact disambiguator token {token!r} uniquely matched.",
            "tiebreaker_token": token,
        }
        return "accept", f"tiebreaker layer1 token: {token}", layer1_choice, audit

    if _distribution_reach_tie_is_underspecified(match_fact, tied_candidates, fact):
        audit = {
            "resolution_method": "provisional",
            "tiebreaker_layer": "layer1",
            "tiebreaker_reason": "Distribution reach tie is underspecified without total, direct, or rural wording.",
        }
        return decision, reason, best_candidate, audit

    no_candidate_reason = _no_candidate_fit_guard(match_fact, tied_candidates, fact)
    if no_candidate_reason:
        audit = {
            "resolution_method": "provisional",
            "tiebreaker_layer": "layer2",
            "tiebreaker_reason": no_candidate_reason,
            "tiebreaker_top_candidate": top_id,
            "tiebreaker_top_score": top_score,
            "tiebreaker_choice": "AMBIGUOUS",
            "tiebreaker_choice_matched_top": False,
        }
        return decision, reason, best_candidate, audit

    try:
        choice, llm_reason = _call_tiebreaker_llm(match_fact, fact, tied_candidates, registry_lookup)
    except Exception as exc:
        audit = {
            "resolution_method": "provisional",
            "tiebreaker_layer": "layer2",
            "tiebreaker_reason": f"Layer 2 declined due to error: {exc.__class__.__name__}",
            "tiebreaker_top_candidate": top_id,
            "tiebreaker_top_score": top_score,
            "tiebreaker_choice": "AMBIGUOUS",
            "tiebreaker_choice_matched_top": False,
        }
        return decision, reason, best_candidate, audit

    if choice == "AMBIGUOUS":
        audit = {
            "resolution_method": "provisional",
            "tiebreaker_layer": "layer2",
            "tiebreaker_reason": llm_reason,
            "tiebreaker_top_candidate": top_id,
            "tiebreaker_top_score": top_score,
            "tiebreaker_choice": choice,
            "tiebreaker_choice_matched_top": False,
        }
        return decision, reason, best_candidate, audit

    if choice != top_id:
        audit = {
            "resolution_method": "provisional",
            "tiebreaker_layer": "layer2",
            "tiebreaker_reason": (
                f"{llm_reason} Declined because Layer 2 chose lower-ranked candidate "
                f"{choice!r} instead of scorer top {top_id!r}."
            ),
            "tiebreaker_top_candidate": top_id,
            "tiebreaker_top_score": top_score,
            "tiebreaker_choice": choice,
            "tiebreaker_choice_matched_top": False,
        }
        return decision, reason, best_candidate, audit

    for candidate in tied_candidates:
        if str(candidate.get("canonical_id") or "") == choice:
            semantic_conflict = _semantic_tiebreaker_conflict(candidate, fact, registry_lookup)
            if semantic_conflict:
                audit = {
                    "resolution_method": "provisional",
                    "tiebreaker_layer": "layer2",
                    "tiebreaker_reason": (
                        f"{llm_reason} Declined due to semantic incompatibility: {semantic_conflict}."
                    ),
                    "tiebreaker_top_candidate": top_id,
                    "tiebreaker_top_score": top_score,
                    "tiebreaker_choice": choice,
                    "tiebreaker_choice_matched_top": False,
                }
                return decision, reason, best_candidate, audit
            audit = {
                "resolution_method": "tiebreaker_layer2_llm",
                "tiebreaker_layer": "layer2",
                "tiebreaker_reason": llm_reason,
                "tiebreaker_top_candidate": top_id,
                "tiebreaker_top_score": top_score,
                "tiebreaker_choice": choice,
                "tiebreaker_choice_matched_top": True,
            }
            return "accept", "tiebreaker layer2 llm", candidate, audit

    audit = {
        "resolution_method": "provisional",
        "tiebreaker_layer": "layer2",
        "tiebreaker_reason": f"Layer 2 returned invalid candidate {choice!r}.",
        "tiebreaker_top_candidate": top_id,
        "tiebreaker_top_score": top_score,
        "tiebreaker_choice": choice,
        "tiebreaker_choice_matched_top": False,
    }
    return decision, reason, best_candidate, audit


def _review_memory_reason(review_decision: dict[str, Any]) -> str:
    status = str(review_decision.get("review_status") or "").strip()
    action = str(review_decision.get("action") or "").strip()
    label = status or action or "reviewed decision"
    return f"review memory: {label}"


def _apply_review_decision_to_dry_run(
    results: dict[str, list[dict[str, Any]]],
    review_decision: dict[str, Any],
    match_fact: dict[str, Any],
    raw: dict[str, Any],
    fact: dict[str, Any],
    registry_lookup: dict[str, dict[str, Any]],
) -> bool:
    action = str(review_decision.get("action") or "").strip()
    canonical_id = str(review_decision.get("canonical_id") or "").strip()
    reason = _review_memory_reason(review_decision)
    base_entry = {
        "raw_name": str(match_fact.get("raw_name") or ""),
        "metric_core": str(match_fact.get("metric_core") or ""),
        "metric_definition": str(match_fact.get("metric_definition") or ""),
        "fact_class": str(match_fact.get("fact_class") or ""),
        "raw_unit": str(match_fact.get("raw_unit") or ""),
        "period": str(raw.get("raw_period") or fact.get("period", "") or ""),
        "reason": reason,
        "best_canonical_id": canonical_id or None,
        "best_score": 1.0 if action == "accept" and canonical_id in registry_lookup else None,
        "second_best_score": 0.0 if action == "accept" and canonical_id in registry_lookup else None,
        "review_action": action,
        "review_status": str(review_decision.get("review_status") or ""),
    }
    dimension = review_decision.get("dimension")
    if isinstance(dimension, dict) and dimension:
        base_entry["dimension"] = dimension

    if action == "accept" and canonical_id in registry_lookup:
        return False

    if action in {
        "route_financial",
        "keep_provisional",
        "do_not_auto_accept",
        "candidate_canonical",
    }:
        results["provisional"].append({**base_entry, "decision": "provisional"})
        return True

    return False


def _resolved_fact_from_review_decision(
    review_decision: dict[str, Any],
    fact: dict[str, Any],
    match_fact: dict[str, Any],
    registry_lookup: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
    default_currency: str,
) -> dict[str, Any] | None:
    action = str(review_decision.get("action") or "").strip()
    canonical_id = str(review_decision.get("canonical_id") or "").strip()
    reason = _review_memory_reason(review_decision)

    if action == "accept" and canonical_id in registry_lookup:
        return None

    if action in {
        "route_financial",
        "keep_provisional",
        "do_not_auto_accept",
        "candidate_canonical",
    }:
        resolved_fact = dict(fact)
        resolved_fact.update(PASS2_DEFAULTS)
        resolved_fact["canonical_id"] = None
        resolved_fact["mapping_confidence"] = "no_match"
        resolved_fact["normalization_decision"] = "partial"
        resolved_fact["mapping_note"] = reason
        resolved_fact["currency"] = default_currency
        resolved_fact["review_memory_applied"] = True
        resolved_fact["review_memory_action"] = action
        if canonical_id:
            resolved_fact["routed_canonical_id"] = canonical_id
        return _enrich_normalized_fact(resolved_fact, registry_lookup, metadata)

    return None


def _review_memory_candidate_id(
    review_decision: dict[str, Any] | None,
    registry_lookup: dict[str, dict[str, Any]],
) -> str | None:
    if not review_decision:
        return None
    if str(review_decision.get("action") or "").strip() != "accept":
        return None
    canonical_id = str(review_decision.get("canonical_id") or "").strip()
    if canonical_id and canonical_id in registry_lookup:
        return canonical_id
    return None


_FINANCIAL_KEYWORD_RE = re.compile(
    r"\b("
    r"revenue|turnover|net sales|ebitda|ebit|profit|pat|dividend|eps|"
    r"earnings per share|earnings|income|debt|"
    r"cash and cash|cash equivalent|operating cash|investing cash|financing cash|cash flow|"
    r"capex|capital expenditure|"
    r"operating profit margin|net profit margin|profit margin|gross margin|"
    r"return on equity|return on net worth|return on average equity|"
    r"return on capital employed|roce|return on investment|"
    r"working capital|inventory turnover|debtors turnover|current ratio|"
    r"revenue growth|sales growth|cagr|"
    r"shareholders fund|retained earnings|total comprehensive income|"
    r"tax expense|profit before tax|profit after tax"
    r")\b",
    re.IGNORECASE,
)

_GROWTH_RATE_RE = re.compile(
    r"\b(yoy|y-o-y|year.on.year|year over year|cagr|growth rate)\b",
    re.IGNORECASE,
)

_FINANCIAL_METRIC_NAMES = {
    "sales", "total revenue", "operating cash flow", "investing cash flow",
    "financing cash flow", "cash and cash equivalents", "earnings per share",
    "capital expenditure", "capex", "ebitda", "ebit", "net income",
    "gross profit", "operating profit", "profit after tax", "profit before tax",
    "shareholders fund", "retained earnings", "total comprehensive income",
    "depreciation and amortisation", "impairment loss",
}


def _is_financial_fact(fact: dict[str, Any], match_fact: dict[str, Any] | None = None) -> bool:
    raw = fact.get("raw", {}) if isinstance(fact, dict) else {}
    graph_fact_type = str(raw.get("graph_fact_type") or fact.get("graph_fact_type") or "").strip()
    if graph_fact_type == "financial_metric":
        return True

    # Check the input fact's own metric name before any registry matching
    fact_metric = str(fact.get("metric") or raw.get("raw_name") or "").lower().strip()
    if fact_metric in _FINANCIAL_METRIC_NAMES:
        return True
    if _FINANCIAL_KEYWORD_RE.search(fact_metric):
        return True
    # Growth-rate language on any metric → financial (growth rates of any metric are P&L territory)
    if _GROWTH_RATE_RE.search(fact_metric):
        return True

    if match_fact:
        text = " ".join(
            str(match_fact.get(key) or "")
            for key in ("raw_name", "metric_core")
        ).lower()
        if _FINANCIAL_KEYWORD_RE.search(text):
            return True

    return False


def _financial_dry_run_entry(
    match_fact: dict[str, Any],
    raw: dict[str, Any],
    fact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "raw_name": str(match_fact.get("raw_name") or ""),
        "metric_core": str(match_fact.get("metric_core") or ""),
        "metric_definition": str(match_fact.get("metric_definition") or ""),
        "fact_class": str(match_fact.get("fact_class") or ""),
        "raw_unit": str(match_fact.get("raw_unit") or ""),
        "period": str(raw.get("raw_period") or fact.get("period", "") or ""),
        "decision": "provisional",
        "reason": "out_of_scope_financial",
        "best_canonical_id": None,
        "best_score": None,
        "second_best_score": None,
        "triage_bucket": "out_of_operational_scope",
        "recommended_action": "route_to_financial_registry_or_ignore",
        "automation_status": "auto_route_financial",
        "proposed_canonical_id": _proposed_canonical_id_for_fact(match_fact),
    }


def _resolved_financial_fact(
    fact: dict[str, Any],
    match_fact: dict[str, Any],
    registry_lookup: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
    default_currency: str,
) -> dict[str, Any]:
    resolved_fact = dict(fact)
    resolved_fact.update(PASS2_DEFAULTS)
    resolved_fact["canonical_id"] = None
    resolved_fact["mapping_confidence"] = "no_match"
    resolved_fact["normalization_decision"] = "out_of_scope_financial"
    resolved_fact["mapping_note"] = "out_of_scope_financial"
    resolved_fact["currency"] = default_currency
    resolved_fact["proposed_canonical_id"] = _proposed_canonical_id_for_fact(match_fact)
    resolved_fact["proposed_canonical_definition"] = match_fact.get("metric_definition")
    resolved_fact["alias_resolved"] = False
    return _enrich_normalized_fact(resolved_fact, registry_lookup, metadata)


def _normalize_match_text(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def _infer_fact_type_hint(
    raw_name: str,
    section_title: str,
    raw_unit: str,
    raw_graph_fact_type: str = "",
) -> str:
    if raw_graph_fact_type:
        return fact_type_hint_from_pass1({"graph_fact_type": raw_graph_fact_type})
    normalized_name = _normalize_match_text(raw_name)
    normalized_section = _normalize_match_text(section_title)
    combined = f"{normalized_name} {normalized_section} {_normalize_match_text(raw_unit)}"

    geography_members = {
        "united states",
        "canada",
        "germany",
        "france",
        "mexico",
        "brazil",
        "china",
        "india",
        "europe",
        "latin america",
        "north america",
        "asia pacific",
    }
    if normalized_name in geography_members:
        return "breakdown_fact"
    if any(
        token in normalized_name
        for token in ["wholesale", "direct to consumer", "e commerce", "foodservice"]
    ):
        return "operational_metric"
    if any(
        token in combined
        for token in ["brand", "category", "market share", "traffic", "pricing", "volume", "mix", "organic"]
    ):
        return "operational_metric"
    if any(
        token in combined
        for token in ["geographic", "region", "market", "segment", "channel"]
    ):
        return "breakdown_fact"
    return "operational_metric"


def _shortlist_for_fact(
    fact: dict[str, Any],
    section_title: str,
    registry_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_name = str(fact.get("raw_name") or "")
    raw_unit = str(fact.get("raw_unit") or "")
    metric_definition = str(fact.get("metric_definition") or "")
    shortlisted_ids: list[str] = []

    for canonical_id, _score in top_definition_matches(metric_definition, k=8):
        if canonical_id in registry_lookup and canonical_id not in shortlisted_ids:
            shortlisted_ids.append(canonical_id)

    if _shortlist_candidates is not None:
        shortlist_payload = _shortlist_candidates(
            raw_name=raw_name,
            section_title=section_title,
            raw_unit=raw_unit,
            registry=list(registry_lookup.values()),
            top_n=6,
        )
        for candidate in shortlist_payload.get("top_candidates", []):
            canonical_id = str(candidate.get("canonical_id", ""))
            if canonical_id in registry_lookup and canonical_id not in shortlisted_ids:
                shortlisted_ids.append(canonical_id)

    return [registry_lookup[canonical_id] for canonical_id in shortlisted_ids]


def _singularize_normalized_text(value: str) -> str:
    tokens = []
    for token in (value or "").split():
        if len(token) > 4 and token.endswith("ies"):
            tokens.append(token[:-3] + "y")
        elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            tokens.append(token[:-1])
        else:
            tokens.append(token)
    return " ".join(tokens)


def _parse_numeric(value: Any, dash_as_zero: bool = False) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    if text in {"-", "â€”", "â€“"}:
        return 0.0 if dash_as_zero else None

    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").replace(" ", "")
    filtered = []
    decimal_seen = False
    for char in text:
        if char.isdigit():
            filtered.append(char)
        elif char == "." and not decimal_seen:
            filtered.append(char)
            decimal_seen = True
        elif char == "-" and not filtered:
            filtered.append(char)

    if not filtered or filtered == ["-"]:
        return None

    try:
        number = float("".join(filtered))
    except ValueError:
        return None

    return -number if negative and number > 0 else number


def _is_year_like_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text in {"-", "â€”", "â€“"}:
        return False

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        return False

    cleaned = text.replace(",", "").replace(" ", "")
    if not cleaned.isdigit() or len(cleaned) != 4:
        return False

    year = int(cleaned)
    return 2000 <= year <= 2030


def _looks_like_date_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if not any(char.isdigit() for char in text):
        return False

    month_names = {
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    }
    if any(month in text for month in month_names):
        return True
    return bool(re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text))


def _is_non_numeric_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text in {"-", "â€”", "â€“"}:
        return False
    return _parse_numeric(text) is None


def _looks_like_exchange_rate_name(raw_name: str) -> bool:
    text = _normalize_match_text(raw_name)
    if not re.match(r"^\d+\s+", text):
        return False

    currency_terms = [
        "dollar",
        "euro",
        "yuan",
        "renminbi",
        "franc",
        "pound",
        "sterling",
        "yen",
        "rupee",
        "peso",
        "real",
        "rand",
        "won",
        "dirham",
    ]
    return any(term in text for term in currency_terms)


def _unit_family_for_fact(
    canonical_id: str,
    unit_from_registry: str | None,
    currency: str,
    raw_name: str,
    raw_unit: str,
) -> str | None:
    canonical_id = (canonical_id or "").lower()
    raw_name_lower = (raw_name or "").lower()
    raw_unit_lower = (raw_unit or "").lower()
    unit_family = (unit_from_registry or "").lower().strip() or None

    if canonical_id == "headcount":
        return "count"
    if (
        canonical_id.endswith("_rate")
        or canonical_id.endswith("_margin")
        or canonical_id.endswith("_growth")
        or canonical_id.endswith("_growth_rate")
        or "%" in raw_unit_lower
        or "percent" in raw_unit_lower
    ):
        return "percentage"
    if "exchange rate" in raw_name_lower or _looks_like_exchange_rate_name(raw_name):
        return "ratio"
    if "per share" in raw_name_lower:
        return "per_share"
    if unit_family in {"monetary", "percentage", "count", "per_share", "days", "ratio"}:
        return unit_family
    if currency:
        return "monetary"
    return None


def _raw_unit_family(raw_name: str, raw_unit: str, raw_value: Any) -> str | None:
    raw_name_lower = (raw_name or "").lower()
    raw_unit_lower = (raw_unit or "").lower()
    numeric_value = _parse_numeric(raw_value)

    if "%" in raw_unit_lower or "percent" in raw_unit_lower:
        return "percentage"
    if any(token in raw_name_lower for token in ["margin", "rate", "growth", "yield", "return"]):
        return "percentage"
    if any(token in raw_name_lower for token in ["employees", "employee", "people", "headcount", "shares", "share count", "store count"]):
        return "count"
    if "per share" in raw_name_lower:
        return "per_share"
    if "days" in raw_name_lower:
        return "days"
    if numeric_value is not None and abs(numeric_value) > 100:
        return "monetary"
    return None


def _candidate_is_blacklisted(raw_name: str, canonical_id: str) -> bool:
    normalized_raw_name = _normalize_match_text(raw_name)
    raw_variants = {
        normalized_raw_name,
        _singularize_normalized_text(normalized_raw_name),
    }
    patterns = {
        _normalize_match_text(pattern)
        for pattern in CANDIDATE_BLACKLIST.get((canonical_id or "").lower(), [])
    }
    pattern_variants = set()
    for pattern in patterns:
        pattern_variants.add(pattern)
        pattern_variants.add(_singularize_normalized_text(pattern))

    return any(
        pattern in raw_variant
        for raw_variant in raw_variants
        for pattern in pattern_variants
        if pattern
    )


def _candidate_has_unit_mismatch(
    raw_name: str,
    raw_unit: str,
    raw_value: Any,
    canonical_id: str,
    registry_entry: dict[str, Any],
) -> bool:
    candidate_family = _unit_family_for_fact(
        canonical_id=canonical_id,
        unit_from_registry=str(registry_entry.get("unit") or ""),
        currency="",
        raw_name=raw_name,
        raw_unit=raw_unit,
    )
    raw_family = _raw_unit_family(raw_name, raw_unit, raw_value)

    if raw_family in {"percentage", "ratio"} and candidate_family == "monetary":
        return True
    if raw_family == "count" and candidate_family == "monetary":
        return True
    if raw_family == "monetary" and candidate_family in {"percentage", "ratio"}:
        return True
    return False


def _candidate_is_valid(
    raw_name: str,
    raw_unit: str,
    raw_value: Any,
    raw_graph_fact_type: str,
    raw_fact_class: str,
    canonical_id: str,
    registry_lookup: dict[str, dict[str, Any]],
) -> bool:
    if not canonical_id:
        return False

    registry_entry = registry_lookup.get(canonical_id, {})
    normalized_raw_name = _normalize_match_text(raw_name)
    if canonical_id.lower() == "total_assets" and normalized_raw_name not in TOTAL_ASSETS_ALLOWED_NAMES:
        return False
    if _candidate_is_blacklisted(raw_name, canonical_id):
        return False
    if _candidate_has_unit_mismatch(
        raw_name=raw_name,
        raw_unit=raw_unit,
        raw_value=raw_value,
        canonical_id=canonical_id,
        registry_entry=registry_entry,
    ):
        return False
    compatible, _ = match_is_compatible(
        {
            "raw_unit": raw_unit,
            "graph_fact_type": raw_graph_fact_type,
            "fact_class": raw_fact_class,
        },
        {
            "unit_family": registry_entry.get("unit_family") or registry_entry.get("unit"),
            "graph_fact_type": registry_entry.get("graph_fact_type", ""),
            "allowed_fact_classes": registry_entry.get("allowed_fact_classes", []),
        },
    )
    if not compatible:
        return False
    return True


def _infer_unit_canonical(
    canonical_id: str,
    canonical_category: str,
    currency: str,
) -> str:
    canonical_id = (canonical_id or "").lower()
    canonical_category = (canonical_category or "").lower()

    if any(
        token in canonical_id
        for token in ["margin", "growth_rate", "rate", "yield", "return"]
    ):
        return "ratio"
    if canonical_id == "inventory_days":
        return "days"
    if canonical_id in {
        "headcount",
        "store_count",
        "loyalty_members",
        "diluted_shares",
    }:
        return "count"
    if canonical_id in {"eps_basic", "eps_diluted"}:
        return currency or ""
    if canonical_category in {"income_statement", "cash_flow", "balance_sheet"}:
        return currency or ""
    if canonical_category == "per_share":
        return currency or ""
    return ""


def _enrich_normalized_fact(
    fact: dict[str, Any],
    registry_lookup: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(fact)
    normalization_decision = str(enriched.get("normalization_decision", "")).lower()
    canonical_id_value = enriched.get("canonical_id")
    canonical_id = str(canonical_id_value or "")
    registry_entry = registry_lookup.get(canonical_id, {})
    raw = enriched.get("raw", {})
    fact_id = str(enriched.get("fact_id", "") or "")
    raw_name = str(raw.get("raw_name") or enriched.get("metric", "") or "")
    raw_unit = str(raw.get("raw_unit") or enriched.get("unit", "") or "")
    raw_value = raw.get("raw_value", enriched.get("value"))
    enriched["raw_value"] = raw_value
    enriched["raw_unit"] = raw_unit
    enriched["period_label"] = str(enriched.get("period") or raw.get("period") or "")
    source_sentence = str(raw.get("source_sentence") or enriched.get("evidence", "") or "")
    section_title = str(enriched.get("section_title", "") or "")
    chunk_type = str(enriched.get("chunk_type", "") or "")

    canonical_name = registry_entry.get("canonical_name") or registry_entry.get("display_name") or ""
    canonical_category = registry_entry.get("category", "") or ""
    canonical_definition = registry_entry.get("canonical_definition") or None
    unit_from_registry = registry_entry.get("unit")
    is_new_metric = normalization_decision == "new_metric"
    is_unmapped = normalization_decision in {"new_metric", "quarantine"}

    if is_unmapped:
        enriched["canonical_id"] = None
        enriched["canonical_name"] = None
        canonical_id = ""
        canonical_name = None
        unit_from_registry = None
    else:
        enriched["canonical_name"] = canonical_name

    enriched["canonical_category"] = canonical_category
    enriched["canonical_definition"] = canonical_definition
    enriched["canonical_subcategory"] = None
    enriched["is_new_metric"] = is_new_metric
    proposed_canonical_id = str(enriched.get("proposed_canonical_id") or "")
    if is_unmapped:
        enriched["proposed_canonical_id"] = proposed_canonical_id or _proposed_canonical_id_for_fact(
            {
                "raw_name": raw_name,
                "metric_core": raw.get("metric_core", ""),
                "parent_metric_hint": raw.get("parent_metric_hint", ""),
            }
        )
        enriched["proposed_canonical_definition"] = (
            str(enriched.get("proposed_canonical_definition") or raw.get("metric_definition") or "").strip() or None
        )
    else:
        enriched["proposed_canonical_id"] = ""
        enriched["proposed_canonical_definition"] = None
    enriched["mapping_note"] = str(enriched.get("mapping_note", "") or "")
    enriched["range_low_normalized"] = None
    enriched["range_high_normalized"] = None
    enriched["unit_from_registry"] = unit_from_registry

    unit_family = _unit_family_for_fact(
        canonical_id=canonical_id,
        unit_from_registry=str(unit_from_registry or ""),
        currency=str(enriched.get("currency", "") or ""),
        raw_name=raw_name,
        raw_unit=raw_unit,
    )
    enriched["unit_canonical"] = _infer_unit_canonical(
        canonical_id=canonical_id,
        canonical_category=canonical_category,
        currency=str(enriched.get("currency", "") or ""),
    )
    enriched["graph_fact_type"] = str(raw.get("graph_fact_type") or enriched.get("graph_fact_type") or "")
    enriched["dimension_type"] = enriched.get("dimension_type") or raw.get("dimension_type")
    enriched["dimension_member"] = enriched.get("dimension_member") or raw.get("dimension_member")
    existing_dimension = enriched.get("dimension")
    dimension_payload = existing_dimension if isinstance(existing_dimension, dict) else None
    if not dimension_payload:
        dimension_payload = dimension_from_fact(raw) or dimension_from_fact(enriched)
    if dimension_payload and registry_entry and registry_entry.get("dimension_capable") is False:
        dimension_payload = None
    enriched["dimension"] = dimension_payload
    enriched["fact_type_hint"] = str(
        enriched.get("fact_type_hint")
        or _infer_fact_type_hint(
            raw_name=raw_name,
            section_title=section_title,
            raw_unit=raw_unit,
            raw_graph_fact_type=str(raw.get("graph_fact_type") or ""),
        )
    )

    unit_norm = normalise_fact_value(enriched)
    enriched["raw_unit_string"] = str(unit_norm.get("raw_unit") or raw_unit or "")
    enriched["normalised_value"] = unit_norm.get("normalised_value")
    enriched["normalised_unit_symbol"] = unit_norm.get("normalised_unit_symbol")
    enriched["unit_canonical"] = enriched.get("normalised_unit_symbol") or enriched.get("unit_canonical") or ""
    enriched["normalization_status"] = normalization_decision
    enriched["similarity_score"] = float(
        enriched.get("best_score")
        if enriched.get("best_score") is not None
        else (1.0 if enriched.get("alias_resolved") else 0.0)
    )
    resolution_method = str(enriched.get("resolution_method") or "scorer")
    enriched["tiebreaker_used"] = resolution_method in {"tiebreaker_layer1_token", "tiebreaker_layer2_llm"}
    if enriched["tiebreaker_used"]:
        enriched["tiebreaker_result"] = "accept" if normalization_decision in {"normalized", "partial"} else "reject"
    elif str(enriched.get("tiebreaker_layer") or ""):
        enriched["tiebreaker_result"] = "reject"
    else:
        enriched["tiebreaker_result"] = None
    enriched["normalisation_confidence"] = str(
        unit_norm.get("normalisation_confidence")
        or "failed"
    )

    gate_result = "not_applicable"
    # Determine which registry entry to run the gate against.
    # For mapped facts use their own canonical_id.
    # For new_metric / unmapped facts, use the nearest_canonical candidate when
    # similarity_score >= 0.75 so the tiebreaker band is properly evaluated.
    gate_canonical_id = canonical_id
    gate_registry_entry = registry_entry
    if not gate_canonical_id:
        nearest_canonical_id = str(enriched.get("nearest_canonical") or "")
        best_score_val = float(enriched.get("best_score") or 0.0)
        if nearest_canonical_id and best_score_val >= 0.75:
            gate_canonical_id = nearest_canonical_id
            gate_registry_entry = registry_lookup.get(nearest_canonical_id, {})
            enriched["nearest_canonical"] = nearest_canonical_id
    if gate_canonical_id and gate_registry_entry:
        fact_semantics = infer_fact_semantics_draft({"raw": raw, **enriched})
        canonical_semantics = semantic_typing_from_registry(gate_registry_entry)
        gate = semantic_alias_gate(
            fact_semantics=fact_semantics,
            canonical_semantics=canonical_semantics,
            fact_unit_family=unit_family_from_raw_unit(raw_unit) or unit_family_for_fact({"raw": raw, **enriched}),
            canonical_unit_family=str(gate_registry_entry.get("unit_family") or ""),
        )
        enriched["gate_block_reasons"] = list(gate.block_reasons)
        substantive_failures = [
            reason for reason in gate.block_reasons if reason not in {"canonical_untyped", "fact_untyped"}
        ]
        if gate.eligible:
            gate_result = "pass"
        elif substantive_failures:
            gate_result = "fail"
    enriched["gate_result"] = gate_result

    similarity_score = float(enriched.get("similarity_score") or 0.0)
    if normalization_decision == "normalized":
        enriched["final_confidence"] = similarity_score
    elif normalization_decision == "partial" and enriched["tiebreaker_used"] and enriched.get("tiebreaker_result") == "accept":
        enriched["final_confidence"] = similarity_score * 0.85
    elif str(enriched.get("tiebreaker_result") or "") == "reject":
        enriched["final_confidence"] = 0.5
    elif normalization_decision == "new_metric":
        enriched["final_confidence"] = 0.0
    else:
        enriched["final_confidence"] = similarity_score
    return enriched


def _resolve_batch_by_alias(
    input_batch: list[dict[str, Any]],
    aliases_lookup: dict[str, str],
    registry_lookup: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    resolved_by_fact_id: dict[str, dict[str, Any]] = {}
    unresolved_facts: list[dict[str, Any]] = []
    default_currency = str(metadata.get("currency", "") or "")

    for fact in input_batch:
        raw = fact.get("raw", {})
        fact_id = str(fact.get("fact_id", ""))
        raw_name = str(raw.get("raw_name") or fact.get("metric", "") or "")
        alias_key = raw_name.lower().strip()
        canonical_id = aliases_lookup.get(alias_key)

        if not canonical_id:
            unresolved_facts.append(fact)
            continue
        if not _candidate_is_valid(
            raw_name=raw_name,
            raw_unit=str(raw.get("raw_unit") or fact.get("unit", "") or ""),
            raw_value=raw.get("raw_value", fact.get("value")),
            raw_graph_fact_type=str(raw.get("graph_fact_type") or ""),
            raw_fact_class=str(raw.get("fact_class") or "scalar_kpi"),
            canonical_id=canonical_id,
            registry_lookup=registry_lookup,
        ):
            unresolved_facts.append(fact)
            continue

        resolved_fact = dict(fact)
        resolved_fact.update(PASS2_DEFAULTS)
        resolved_fact["canonical_id"] = canonical_id
        resolved_fact["mapping_confidence"] = "high"
        resolved_fact["variant_flag"] = False
        resolved_fact["variant_label"] = ""
        resolved_fact["currency"] = default_currency
        resolved_fact["best_score"] = 1.0
        resolved_fact["second_best_score"] = 0.0
        resolved_fact["resolution_method"] = "scorer"
        resolved_fact["normalization_decision"] = (
            "partial"
            if str(fact.get("decision", "")).lower() == "rescue"
            else "normalized"
        )
        resolved_fact["alias_resolved"] = True
        resolved_by_fact_id[fact_id] = _enrich_normalized_fact(
            resolved_fact,
            registry_lookup,
            metadata,
        )

    return resolved_by_fact_id, unresolved_facts


def _top_fuzzy_registry_matches(
    fact: dict[str, Any],
    registry_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not str(fact.get("raw_name") or "").strip() and not str(fact.get("metric_definition") or "").strip():
        return []

    candidates: list[dict[str, Any]] = []
    raw_name = str(fact.get("raw_name") or "")
    for canonical_id, registry_entry in registry_lookup.items():
        if _candidate_is_blacklisted(raw_name, canonical_id):
            continue
        score = compute_match_score(fact, registry_entry)
        if score <= 0.0:
            continue
        signals = compute_match_signals(fact, registry_entry)
        candidates.append(
            {
                "canonical_id": canonical_id,
                "score": score,
                "definition_score": float(signals["definition_score"]),
                "metric_core_score": float(signals["metric_core_score"]),
                "alias_score": float(signals["alias_score"]),
                "definition_drifted": bool(signals["definition_drifted"]),
            }
        )

    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:5]


def _resolve_batch_by_fuzzy_match(
    input_batch: list[dict[str, Any]],
    registry_lookup: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    set_definition_registry(list(registry_lookup.values()))
    review_memory = load_review_memory()
    resolved_by_fact_id: dict[str, dict[str, Any]] = {}
    unresolved_facts: list[dict[str, Any]] = []
    default_currency = str(metadata.get("currency", "") or "")

    for fact in input_batch:
        raw = fact.get("raw", {})
        fact_id = str(fact.get("fact_id", ""))
        raw_name = str(raw.get("raw_name") or fact.get("metric", "") or "")
        raw_unit = str(raw.get("raw_unit") or fact.get("unit", "") or "")
        raw_value = raw.get("raw_value", fact.get("value"))
        section_title = str(fact.get("section_title", "") or "")
        match_fact = _build_match_fact(fact)
        if _is_financial_fact(fact, match_fact):
            resolved_by_fact_id[fact_id] = _resolved_financial_fact(
                fact=fact,
                match_fact=match_fact,
                registry_lookup=registry_lookup,
                metadata=metadata,
                default_currency=default_currency,
            )
            continue
        review_decision = lookup_review_decision(
            review_memory,
            raw_name=str(match_fact.get("raw_name") or ""),
            metric_core=str(match_fact.get("metric_core") or ""),
        )
        if review_decision:
            reviewed_fact = _resolved_fact_from_review_decision(
                review_decision=review_decision,
                fact=fact,
                match_fact=match_fact,
                registry_lookup=registry_lookup,
                metadata=metadata,
                default_currency=default_currency,
            )
            if reviewed_fact is not None:
                resolved_by_fact_id[fact_id] = reviewed_fact
                continue

        scope3_sub_category = _scope3_sub_category(match_fact)
        if scope3_sub_category and "scope_3_emissions" in registry_lookup:
            resolved_fact = dict(fact)
            resolved_fact.update(PASS2_DEFAULTS)
            resolved_fact["canonical_id"] = "scope_3_emissions"
            resolved_fact["sub_category"] = scope3_sub_category
            resolved_fact["mapping_confidence"] = "high"
            resolved_fact["variant_flag"] = False
            resolved_fact["variant_label"] = ""
            resolved_fact["currency"] = default_currency
            resolved_fact["normalization_decision"] = (
                "partial" if str(fact.get("decision", "")).lower() == "rescue" else "normalized"
            )
            resolved_fact["mapping_note"] = "scope 3 category breakdown mapped to scope_3_emissions"
            resolved_fact["alias_resolved"] = False
            resolved_by_fact_id[fact_id] = _enrich_normalized_fact(
                resolved_fact,
                registry_lookup,
                metadata,
            )
            continue
        shortlisted_candidates = _shortlist_for_fact(
            fact=match_fact,
            section_title=section_title,
            registry_lookup=registry_lookup,
        )
        if shortlisted_candidates:
            shortlist_lookup = {
                str(candidate.get("canonical_id", "")): registry_lookup[str(candidate.get("canonical_id", ""))]
                for candidate in shortlisted_candidates
                if str(candidate.get("canonical_id", "")) in registry_lookup
            }
        else:
            shortlist_lookup = registry_lookup
        memory_candidate_id = _review_memory_candidate_id(review_decision, registry_lookup)
        if memory_candidate_id:
            shortlist_lookup[memory_candidate_id] = registry_lookup[memory_candidate_id]

        top_candidates = _top_fuzzy_registry_matches(
            match_fact,
            shortlist_lookup,
        )
        best_candidate = top_candidates[0] if top_candidates else None
        second_best_score = top_candidates[1]["score"] if len(top_candidates) > 1 else 0.0
        decision, reason = accept_match(best_candidate, second_best_score, match_fact)
        decision, reason, best_candidate, tiebreaker_audit = _try_margin_tiebreaker(
            decision=decision,
            reason=reason,
            top_candidates=top_candidates,
            match_fact=match_fact,
            fact=fact,
            registry_lookup=registry_lookup,
        )

        if decision == "provisional":
            resolved_fact = dict(fact)
            resolved_fact.update(PASS2_DEFAULTS)
            resolved_fact["mapping_confidence"] = "no_match"
            resolved_fact["normalization_decision"] = "new_metric"
            resolved_fact["proposed_canonical_id"] = _proposed_canonical_id_for_fact(match_fact)
            resolved_fact["proposed_canonical_definition"] = match_fact.get("metric_definition")
            resolved_fact["mapping_note"] = reason
            resolved_fact["currency"] = default_currency
            resolved_fact["alias_resolved"] = False
            resolved_fact["best_score"] = (
                float(best_candidate.get("score", 0.0))
                if best_candidate
                else 0.0
            )
            resolved_fact["second_best_score"] = float(second_best_score)
            # Store nearest canonical so _enrich_normalized_fact can run the semantic
            # gate even for new_metric facts (needed when similarity_score >= 0.75)
            if best_candidate:
                resolved_fact["nearest_canonical"] = str(best_candidate.get("canonical_id") or "")
            resolved_fact.update(tiebreaker_audit)
            resolved_by_fact_id[fact_id] = _enrich_normalized_fact(
                resolved_fact,
                registry_lookup,
                metadata,
            )
            continue

        if decision == "quarantine":
            resolved_fact = dict(fact)
            resolved_fact.update(PASS2_DEFAULTS)
            resolved_fact["mapping_confidence"] = "no_match"
            resolved_fact["normalization_decision"] = "quarantine"
            resolved_fact["proposed_canonical_id"] = _snake_case(match_fact.get("metric_core", ""))
            resolved_fact["proposed_canonical_definition"] = match_fact.get("metric_definition")
            resolved_fact["mapping_note"] = reason
            resolved_fact["quarantine_reason"] = reason
            resolved_fact["currency"] = default_currency
            resolved_fact["alias_resolved"] = False
            resolved_fact["best_score"] = (
                float(best_candidate.get("score", 0.0))
                if best_candidate
                else 0.0
            )
            resolved_fact["second_best_score"] = float(second_best_score)
            resolved_by_fact_id[fact_id] = _enrich_normalized_fact(
                resolved_fact,
                registry_lookup,
                metadata,
            )
            continue

        resolved_fact = dict(fact)
        resolved_fact.update(PASS2_DEFAULTS)
        resolved_fact["canonical_id"] = str(best_candidate.get("canonical_id") or "")
        resolved_fact["mapping_confidence"] = (
            "high" if float(best_candidate.get("score", 0.0)) >= 0.90 else "medium"
        )
        resolved_fact["variant_flag"] = False
        resolved_fact["variant_label"] = ""
        resolved_fact["currency"] = default_currency
        resolved_fact["best_score"] = float(best_candidate.get("score", 0.0))
        resolved_fact["second_best_score"] = float(second_best_score)
        if str(fact.get("decision", "")).lower() == "rescue":
            resolved_fact["normalization_decision"] = "partial"
        else:
            resolved_fact["normalization_decision"] = (
                "normalized" if float(best_candidate.get("score", 0.0)) >= 0.90 else "partial"
            )
        resolved_fact["mapping_note"] = reason
        resolved_fact["alias_resolved"] = False
        resolved_fact.update(
            tiebreaker_audit
            if tiebreaker_audit.get("resolution_method") != "provisional"
            else {"resolution_method": "scorer"}
        )
        resolved_by_fact_id[fact_id] = _enrich_normalized_fact(
            resolved_fact,
            registry_lookup,
            metadata,
        )

    return resolved_by_fact_id, unresolved_facts


def _load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_pass1_facts_and_metadata(
    payload: Any,
    *,
    source_path: str | Path | None = None,
    enforce_guardrail: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_label = str(source_path or "<memory>")
    schema_version = None

    if isinstance(payload, dict):
        schema_version = payload.get("schema_version")
        facts = payload.get("facts", [])
    else:
        facts = payload

    if not isinstance(facts, list):
        raise ValueError(f"Input JSON must be a list of facts or a Pass 1 payload object: {source_label}")
    if not facts:
        raise ValueError(f"Input JSON contains no facts: {source_label}")

    missing_definition_count = 0
    for fact in facts:
        raw = fact.get("raw", {}) if isinstance(fact, dict) else {}
        metric_definition = raw.get("metric_definition") if isinstance(raw, dict) else None
        if metric_definition is None:
            metric_definition = fact.get("metric_definition") if isinstance(fact, dict) else None
        if not str(metric_definition or "").strip():
            missing_definition_count += 1

    if schema_version != PASS1_SCHEMA_VERSION:
        version_label = schema_version if schema_version is not None else "missing"
        print(
            "WARNING: input file schema_version is "
            f"{version_label}; expected {PASS1_SCHEMA_VERSION}.",
            flush=True,
        )

    missing_ratio = missing_definition_count / len(facts)
    if enforce_guardrail and missing_ratio > STALE_DEFINITION_THRESHOLD:
        raise SystemExit(
            "ERROR: input file appears to predate the Define step.\n"
            f"{missing_definition_count} of {len(facts)} facts have no metric_definition. "
            "The matcher scores definition similarity as the primary signal, so this "
            "file will score near-zero on everything. Regenerate this file with the "
            "current extractor before normalizing."
        )

    return facts, {
        "schema_version": schema_version,
        "missing_metric_definition_count": missing_definition_count,
        "total_facts": len(facts),
    }


def _seed_registry_entries() -> list[dict[str, Any]]:
    return [dict(entry) for entry in SEED_REGISTRY]


def _metric_registry_with_seed() -> list[dict[str, Any]]:
    base_registry = _load_json(_metric_registry_path())
    merged_by_id: dict[str, dict[str, Any]] = {
        str(metric.get("canonical_id", "")): dict(metric)
        for metric in base_registry
        if str(metric.get("canonical_id", ""))
    }
    for seed_entry in _seed_registry_entries():
        canonical_id = str(seed_entry.get("canonical_id", ""))
        if canonical_id in merged_by_id:
            existing = merged_by_id[canonical_id]
            existing.setdefault("graph_fact_type", seed_entry.get("graph_fact_type"))
            existing.setdefault("dimension_capable", seed_entry.get("dimension_capable"))
            existing.setdefault("unit", seed_entry.get("unit"))
            existing.setdefault("unit_family", seed_entry.get("unit_family"))
            existing.setdefault("allowed_unit_families", seed_entry.get("allowed_unit_families"))
            existing.setdefault("allowed_fact_classes", seed_entry.get("allowed_fact_classes"))
            existing.setdefault("scope_level", seed_entry.get("scope_level"))
            existing.setdefault("canonical_definition", seed_entry.get("canonical_definition"))
            aliases = list(existing.get("aliases", []) or [])
            alias_set = {str(alias).lower() for alias in aliases}
            for alias in seed_entry.get("aliases", []):
                if str(alias).lower() not in alias_set:
                    aliases.append(alias)
            existing["aliases"] = aliases
        else:
            merged_by_id[canonical_id] = seed_entry
    for canonical_id, existing in merged_by_id.items():
        existing.setdefault(
            "canonical_definition",
            canonical_definition_for_entry(canonical_id, existing),
        )
    return list(merged_by_id.values())


def _aliases_with_seed() -> dict[str, str]:
    aliases_lookup = {
        str(key).lower().strip(): str(value)
        for key, value in _load_json(_ROOT / "registry" / "registry_aliases.json").items()
    }
    for key, value in build_seed_alias_index().items():
        aliases_lookup.setdefault(str(key).lower().strip(), str(value))
    return aliases_lookup


def _metric_registry_path() -> Path:
    preferred = _ROOT / "registry" / "consumer_master_registry_v1.json"
    if preferred.exists():
        return preferred
    return _ROOT / "registry" / "metric_registry.json"


def _write_json(path: str | Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _load_checkpoint_facts(path: str | Path) -> list[dict[str, Any]]:
    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return []
    return _load_json(checkpoint_path)


def _metadata_path_for_input(pass1_path: str | Path) -> Path | None:
    pass1_path = Path(pass1_path)
    name = pass1_path.name
    if name.endswith("_pass1.json"):
        metadata_name = name[: -len("_pass1.json")] + "_metadata.json"
    else:
        metadata_name = pass1_path.stem + "_metadata.json"

    derived_path = pass1_path.with_name(metadata_name)
    if derived_path.exists():
        return derived_path

    matches = sorted(pass1_path.parent.glob("*_metadata.json"))
    if matches:
        return matches[0]

    return None


def _ensure_filing_metadata(pass1_path: str | Path) -> dict[str, Any]:
    metadata_path = _metadata_path_for_input(pass1_path)
    if metadata_path is None:
        raise FileNotFoundError(
            "No metadata file found â€” run filing_metadata.py first"
        )
    return _load_json(metadata_path)


def _condense_metric_registry(metric_registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    condensed = []
    for metric in metric_registry:
        metric_copy = {
            "canonical_id": metric.get("canonical_id", ""),
            "canonical_name": metric.get("canonical_name") or metric.get("display_name", ""),
            "category": metric.get("category", ""),
        }
        condensed.append(metric_copy)
    return condensed


def _batched(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [
        items[index:index + batch_size]
        for index in range(0, len(items), batch_size)
    ]


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    cleaned = _strip_code_fences(text)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, list):
        raise ValueError("Expected JSON array response")
    return parsed


def _fallback_fact(fact: dict[str, Any], mapping_note: str) -> dict[str, Any]:
    fallback = dict(fact)
    fallback.update(PASS2_DEFAULTS)
    fallback["mapping_note"] = mapping_note
    fallback["normalization_decision"] = "partial"
    return fallback


def _dropped_fact_passthrough(fact: dict[str, Any]) -> dict[str, Any]:
    dropped = dict(fact)
    dropped.update(PASS2_DEFAULTS)
    dropped["normalization_decision"] = "drop"
    dropped["mapping_note"] = ""
    dropped["mapping_confidence"] = "no_match"
    return dropped


def _normalize_batch_shape(
    input_batch: list[dict[str, Any]],
    output_batch: list[dict[str, Any]],
    registry_lookup: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized = []
    for original, returned in zip(input_batch, output_batch):
        merged = dict(original)
        if isinstance(returned, dict):
            merged.update(returned)

        for key, default in PASS2_DEFAULTS.items():
            merged.setdefault(key, default)

        candidate_id = str(merged.get("canonical_id") or "")
        if candidate_id and not _candidate_is_valid(
            raw_name=str(
                original.get("raw", {}).get("raw_name")
                or original.get("metric", "")
                or ""
            ),
            raw_unit=str(
                original.get("raw", {}).get("raw_unit")
                or original.get("unit", "")
                or ""
            ),
            raw_value=original.get("raw", {}).get("raw_value", original.get("value")),
            raw_graph_fact_type=str(original.get("raw", {}).get("graph_fact_type") or ""),
            raw_fact_class=str(original.get("raw", {}).get("fact_class") or "scalar_kpi"),
            canonical_id=candidate_id,
            registry_lookup=registry_lookup,
        ):
            merged["mapping_confidence"] = "low"
            merged["normalization_decision"] = "partial"
            merged["mapping_note"] = (
                "API candidate rejected by blacklist/unit-family check"
            )

        normalized.append(_enrich_normalized_fact(merged, registry_lookup, metadata))
    return normalized


def _build_pass2_input_batch(
    pass1_facts_batch: list[dict[str, Any]],
    registry_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    compact_batch = []
    for fact in pass1_facts_batch:
        raw = fact.get("raw", {})
        raw_name = str(raw.get("raw_name") or fact.get("metric", "") or "")
        raw_unit = str(raw.get("raw_unit") or fact.get("unit", "") or "")
        section_title = str(fact.get("section_title", "") or "")
        compact_batch.append(
            {
                "fact_id": fact.get("fact_id", ""),
                "raw_name": raw_name,
                "raw_value": raw.get("raw_value", fact.get("value")),
                "raw_unit": raw_unit,
                "raw_period": raw.get("raw_period") or fact.get("period", ""),
                "period_type": raw.get("period_type", ""),
                "fact_type": raw.get("fact_type", ""),
                "fact_type_hint": _infer_fact_type_hint(
                    raw_name=raw_name,
                    section_title=section_title,
                    raw_unit=raw_unit,
                    raw_graph_fact_type=str(raw.get("graph_fact_type") or ""),
                ),
                "scope": raw.get("scope", ""),
                "segment_name": raw.get("segment_name") or fact.get("segment", ""),
                "section_title": section_title,
                "source_sentence": raw.get("source_sentence") or fact.get("evidence", ""),
                "decision": raw.get("decision") or fact.get("decision", ""),
                "candidate_shortlist": _shortlist_for_fact(
                    raw_name=raw_name,
                    section_title=section_title,
                    raw_unit=raw_unit,
                    registry_lookup=registry_lookup,
                ),
            }
        )
    return compact_batch


def _preflight_check(pass1_path: str | Path) -> list[dict[str, Any]]:
    input_path = Path(pass1_path)
    registry_path = _metric_registry_path()
    aliases_path = _ROOT / "registry" / "registry_aliases.json"

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if not registry_path.exists():
        raise FileNotFoundError(f"Required file not found: {registry_path}")
    if not aliases_path.exists():
        raise FileNotFoundError(f"Required file not found: {aliases_path}")

    try:
        payload = _load_json(input_path)
    except json.JSONDecodeError as error:
        raise ValueError(f"Input file is not valid JSON: {input_path}") from error

    pass1_facts, payload_meta = _extract_pass1_facts_and_metadata(payload, source_path=input_path)

    print("Pre-execution check", flush=True)
    print(f"- input file: {input_path} (valid JSON)", flush=True)
    print(f"- facts found: {len(pass1_facts)}", flush=True)
    print(f"- schema_version: {payload_meta.get('schema_version') or 'missing'}", flush=True)
    print(
        "- facts with missing metric_definition: "
        f"{payload_meta.get('missing_metric_definition_count', 0)}",
        flush=True,
    )
    print(f"- metric registry: {registry_path} (found)", flush=True)
    print(f"- registry aliases: {aliases_path} (found)", flush=True)
    print(f"- batch_size: {BATCH_SIZE}", flush=True)
    print(f"- max_workers: {MAX_CONCURRENT_CALLS}", flush=True)
    print(f"- model: {MODEL}", flush=True)

    if sys.stdin.isatty():
        try:
            confirmation = input(
                f"Ready to normalize {len(pass1_facts)} facts. Proceed? (y/n) "
            ).strip().lower()
        except EOFError:
            confirmation = "y"
            print("No interactive response available; proceeding automatically.", flush=True)
        if confirmation != "y":
            raise SystemExit("Aborted by user.")
    else:
        print("Non-interactive stdin detected; proceeding automatically.", flush=True)

    return pass1_facts


def _build_messages(
    metadata: dict[str, Any],
    metric_registry: list[dict[str, Any]],
    registry_lookup: dict[str, dict[str, Any]],
    pass1_facts_batch: list[dict[str, Any]],
) -> list[dict[str, str]]:
    system_prompt = PASS2_SYSTEM_PROMPT.format(
        company=metadata.get("company_name", ""),
        document_period=metadata.get("primary_period", ""),
        fiscal_year_end_month=metadata.get("fiscal_year_end_month", ""),
        filing_type=metadata.get("filing_type", ""),
        default_currency=metadata.get("currency", "USD"),
        metric_registry=json.dumps(
            metric_registry,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        base_metric_id="base_metric_id",
    )
    user_prompt = PASS2_USER_PROMPT.format(
        pass1_facts_batch=json.dumps(
            _build_pass2_input_batch(pass1_facts_batch, registry_lookup),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        base_metric_id="base_metric_id",
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _call_openai(messages: list[dict[str, str]]) -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=API_TIMEOUT_SECONDS,
        max_retries=1,
    )
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=messages,
        timeout=API_TIMEOUT_SECONDS,
    )
    return response.choices[0].message.content or "[]"


def _retry_wait_seconds(error: Exception) -> int:
    if error.__class__.__name__ == "RateLimitError":
        return RATE_LIMIT_RETRY_WAIT_SECONDS
    return RETRY_WAIT_SECONDS


def _normalize_batch(
    batch_index: int,
    input_batch: list[dict[str, Any]],
    metadata: dict[str, Any],
    metric_registry: list[dict[str, Any]],
    registry_lookup: dict[str, dict[str, Any]],
    aliases_lookup: dict[str, str],
) -> list[dict[str, Any]]:
    alias_resolved_by_fact_id, alias_unresolved_facts = _resolve_batch_by_alias(
        input_batch=input_batch,
        aliases_lookup=aliases_lookup,
        registry_lookup=registry_lookup,
        metadata=metadata,
    )
    fuzzy_resolved_by_fact_id, unresolved_facts = _resolve_batch_by_fuzzy_match(
        input_batch=alias_unresolved_facts,
        registry_lookup=registry_lookup,
        metadata=metadata,
    )
    print(
        f"Batch {batch_index}: {len(alias_resolved_by_fact_id)} alias, {len(fuzzy_resolved_by_fact_id)} fuzzy, {len(unresolved_facts)} sent to API",
        flush=True,
    )

    if not unresolved_facts:
        merged_by_fact_id = {}
        merged_by_fact_id.update(alias_resolved_by_fact_id)
        merged_by_fact_id.update(fuzzy_resolved_by_fact_id)
        return [
            merged_by_fact_id[str(fact.get("fact_id", ""))]
            for fact in input_batch
        ]

    messages = _build_messages(
        metadata,
        metric_registry,
        registry_lookup,
        unresolved_facts,
    )
    print(
        f"Normalizing batch {batch_index} ({len(unresolved_facts)} facts)...",
        flush=True,
    )

    try:
        print(
            f"Calling API: {len(unresolved_facts)} facts, model={MODEL}, timeout={API_TIMEOUT_SECONDS}",
            flush=True,
        )
        print(f"Sending batch {batch_index} to API...", flush=True)
        start_time = time.monotonic()
        content = _call_openai(messages)
        elapsed = time.monotonic() - start_time
        print(f"Batch {batch_index} returned in {elapsed:.1f}s", flush=True)
    except Exception as first_error:
        print(f"Batch {batch_index} failed: {first_error!r}", flush=True)
        retry_wait = _retry_wait_seconds(first_error)
        print(
            f"Batch {batch_index} API error, retrying in {retry_wait}s: {first_error!r}",
            flush=True,
        )
        time.sleep(retry_wait)
        try:
            print(
                f"Calling API: {len(unresolved_facts)} facts, model={MODEL}, timeout={API_TIMEOUT_SECONDS}",
                flush=True,
            )
            print(f"Sending batch {batch_index} to API...", flush=True)
            start_time = time.monotonic()
            content = _call_openai(messages)
            elapsed = time.monotonic() - start_time
            print(
                f"Batch {batch_index} returned in {elapsed:.1f}s",
                flush=True,
            )
        except Exception as second_error:
            print(f"Batch {batch_index} failed: {second_error!r}", flush=True)
            print(
                f"Batch {batch_index} failed after retry: {second_error!r}",
                flush=True,
            )
            api_results = [
                _fallback_fact(fact, "batch parse error")
                for fact in unresolved_facts
            ]
            merged_api_results = _normalize_batch_shape(
                unresolved_facts,
                api_results,
                registry_lookup,
                metadata,
            )
            merged_by_fact_id = {
                str(fact.get("fact_id", "")): fact
                for fact in merged_api_results
            }
            merged_by_fact_id.update(alias_resolved_by_fact_id)
            merged_by_fact_id.update(fuzzy_resolved_by_fact_id)
            return [
                merged_by_fact_id[str(fact.get("fact_id", ""))]
                for fact in input_batch
            ]

    try:
        parsed = _parse_json_array(content)
    except Exception as parse_error:
        print(
            f"Batch {batch_index} parse error: {parse_error!r}",
            flush=True,
        )
        api_results = [
            _fallback_fact(fact, "batch parse error")
            for fact in unresolved_facts
        ]
        merged_api_results = _normalize_batch_shape(
            unresolved_facts,
            api_results,
            registry_lookup,
            metadata,
        )
        merged_by_fact_id = {
            str(fact.get("fact_id", "")): fact
            for fact in merged_api_results
        }
        merged_by_fact_id.update(alias_resolved_by_fact_id)
        merged_by_fact_id.update(fuzzy_resolved_by_fact_id)
        return [
            merged_by_fact_id[str(fact.get("fact_id", ""))]
            for fact in input_batch
        ]

    if len(parsed) != len(unresolved_facts):
        print(
            f"Batch {batch_index} length mismatch: input={len(unresolved_facts)} output={len(parsed)}",
            flush=True,
        )
        api_results = [
            _fallback_fact(fact, "batch parse error")
            for fact in unresolved_facts
        ]
        merged_api_results = _normalize_batch_shape(
            unresolved_facts,
            api_results,
            registry_lookup,
            metadata,
        )
        merged_by_fact_id = {
            str(fact.get("fact_id", "")): fact
            for fact in merged_api_results
        }
        merged_by_fact_id.update(alias_resolved_by_fact_id)
        merged_by_fact_id.update(fuzzy_resolved_by_fact_id)
        return [
            merged_by_fact_id[str(fact.get("fact_id", ""))]
            for fact in input_batch
        ]

    normalized_unresolved = _normalize_batch_shape(
        unresolved_facts,
        parsed,
        registry_lookup,
        metadata,
    )
    merged_by_fact_id = {
        str(fact.get("fact_id", "")): fact
        for fact in normalized_unresolved
    }
    merged_by_fact_id.update(alias_resolved_by_fact_id)
    merged_by_fact_id.update(fuzzy_resolved_by_fact_id)
    return [
        merged_by_fact_id[str(fact.get("fact_id", ""))]
        for fact in input_batch
    ]


def summarize_pass2(facts: list[dict[str, Any]]) -> None:
    decision_counts = {
        "normalized": 0,
        "partial": 0,
        "new_metric": 0,
        "quarantine": 0,
        "drop": 0,
    }
    confidence_counts = {
        "high": 0,
        "medium": 0,
        "low": 0,
        "no_match": 0,
    }

    for fact in facts:
        decision = str(fact.get("normalization_decision", "")).lower()
        confidence = str(fact.get("mapping_confidence", "")).lower()
        if decision in decision_counts:
            decision_counts[decision] += 1
        if confidence in confidence_counts:
            confidence_counts[confidence] += 1

    print(f"Total facts: {len(facts)}", flush=True)
    print(f"normalized count: {decision_counts['normalized']}", flush=True)
    print(f"partial count: {decision_counts['partial']}", flush=True)
    print(f"new_metric count: {decision_counts['new_metric']}", flush=True)
    print(f"quarantine count: {decision_counts['quarantine']}", flush=True)
    print(f"drop count: {decision_counts['drop']}", flush=True)
    print(
        "confidence breakdown: "
        f"high={confidence_counts['high']} | "
        f"medium={confidence_counts['medium']} | "
        f"low={confidence_counts['low']} | "
        f"no_match={confidence_counts['no_match']}",
        flush=True,
    )


def dry_run(pass1_output: list[dict]) -> dict:
    metric_registry = _metric_registry_with_seed()
    set_definition_registry(metric_registry)
    registry_lookup = {
        str(metric.get("canonical_id", "")): metric
        for metric in metric_registry
        if str(metric.get("canonical_id", ""))
    }
    review_memory = load_review_memory()
    debug_enabled = str(os.getenv("DRY_RUN_DEBUG", "")).strip() == "1"
    results = {
        "accept": [],
        "provisional": [],
        "quarantine": [],
    }

    for fact in pass1_output:
        match_fact = _build_match_fact(fact)
        raw = fact.get("raw", {})
        raw_name = str(match_fact.get("raw_name") or "")
        raw_unit = str(match_fact.get("raw_unit") or "")
        section_title = str(fact.get("section_title", "") or "")
        scope3_sub_category = _scope3_sub_category(match_fact)
        if _is_financial_fact(fact, match_fact):
            results["provisional"].append(_financial_dry_run_entry(match_fact, raw, fact))
            continue
        review_decision = lookup_review_decision(
            review_memory,
            raw_name=raw_name,
            metric_core=str(match_fact.get("metric_core") or ""),
        )
        if review_decision and _apply_review_decision_to_dry_run(
            results=results,
            review_decision=review_decision,
            match_fact=match_fact,
            raw=raw,
            fact=fact,
            registry_lookup=registry_lookup,
        ):
            continue

        if scope3_sub_category and "scope_3_emissions" in registry_lookup:
            results["accept"].append(
            {
                "raw_name": raw_name,
                "metric_core": str(match_fact.get("metric_core") or ""),
                "fact_class": str(match_fact.get("fact_class") or ""),
                "raw_unit": raw_unit,
                "period": str(raw.get("raw_period") or fact.get("period", "") or ""),
                "decision": "accept",
                "reason": "scope 3 category breakdown mapped to scope_3_emissions",
                "resolution_method": "scorer",
                "best_canonical_id": "scope_3_emissions",
                    "best_score": 1.0,
                    "second_best_score": 0.0,
                    "sub_category": scope3_sub_category,
                    "metric_definition": str(match_fact.get("metric_definition") or ""),
                }
            )
            continue

        shortlisted_candidates = _shortlist_for_fact(
            fact=match_fact,
            section_title=section_title,
            registry_lookup=registry_lookup,
        )
        if shortlisted_candidates:
            shortlist_lookup = {
                str(candidate.get("canonical_id", "")): registry_lookup[str(candidate.get("canonical_id", ""))]
                for candidate in shortlisted_candidates
                if str(candidate.get("canonical_id", "")) in registry_lookup
            }
        else:
            shortlist_lookup = registry_lookup
        memory_candidate_id = _review_memory_candidate_id(review_decision, registry_lookup)
        if memory_candidate_id:
            shortlist_lookup[memory_candidate_id] = registry_lookup[memory_candidate_id]

        top_candidates = _top_fuzzy_registry_matches(match_fact, shortlist_lookup)
        best_candidate = top_candidates[0] if top_candidates else None
        second_best_score = top_candidates[1]["score"] if len(top_candidates) > 1 else 0.0
        decision, reason = accept_match(best_candidate, second_best_score, match_fact)
        decision, reason, best_candidate, tiebreaker_audit = _try_margin_tiebreaker(
            decision=decision,
            reason=reason,
            top_candidates=top_candidates,
            match_fact=match_fact,
            fact=fact,
            registry_lookup=registry_lookup,
        )

        if (
            debug_enabled
            and decision == "provisional"
            and reason == "no match, mint from metric_core"
        ):
            print(
                f"[DEBUG] {raw_name} | shortlist candidates: {list(shortlist_lookup.keys())}",
                flush=True,
            )
            fact_unit_family = unit_family_from_raw_unit(match_fact.get("raw_unit"))
            fact_class = str(match_fact.get("fact_class") or "")
            for canonical_id, candidate in shortlist_lookup.items():
                candidate_unit_family = str(
                    candidate.get("unit_family") or candidate.get("unit") or "unknown"
                )
                allowed_fact_classes = list(candidate.get("allowed_fact_classes") or [])
                unit_gate = (
                    "pass"
                    if (
                        fact_unit_family == "unknown"
                        or candidate_unit_family in {"", "unknown"}
                        or fact_unit_family == candidate_unit_family
                    )
                    else "fail"
                )
                factclass_gate = (
                    "pass"
                    if (
                        not allowed_fact_classes
                        or not fact_class
                        or fact_class in allowed_fact_classes
                    )
                    else "fail"
                )
                print(
                    "[DEBUG-GATES] "
                    f"{raw_name} | candidate: {canonical_id} "
                    f"| unit_family_fact: {fact_unit_family} "
                    f"| unit_family_canonical: {candidate_unit_family} "
                    f"| fact_class: {fact_class} "
                    f"| allowed_fact_classes: {allowed_fact_classes} "
                    f"| unit_gate: {unit_gate} | factclass_gate: {factclass_gate}",
                    flush=True,
                )

        results[decision].append(
            {
                "raw_name": raw_name,
                "metric_core": str(match_fact.get("metric_core") or ""),
                "metric_definition": str(match_fact.get("metric_definition") or ""),
                "fact_class": str(match_fact.get("fact_class") or ""),
                "raw_unit": raw_unit,
                "period": str(raw.get("raw_period") or fact.get("period", "") or ""),
                "decision": decision,
                "reason": reason,
                "best_canonical_id": (
                    str(best_candidate.get("canonical_id") or "")
                    if best_candidate
                    else None
                ),
                "best_score": (
                    float(best_candidate.get("score", 0.0))
                    if best_candidate
                    else None
                ),
                "second_best_score": (
                    float(second_best_score)
                    if top_candidates
                    else None
                ),
                **(
                    tiebreaker_audit
                    if tiebreaker_audit.get("tiebreaker_layer")
                    else {"resolution_method": "provisional"}
                ),
            }
        )

    return results


def print_dry_run_summary(results: dict) -> None:
    accept_entries = list(results.get("accept", []) or [])
    provisional_entries = list(results.get("provisional", []) or [])
    quarantine_entries = list(results.get("quarantine", []) or [])
    total = len(accept_entries) + len(provisional_entries) + len(quarantine_entries)

    print(f"Total fact count: {total}", flush=True)
    for bucket_name, entries in (
        ("accept", accept_entries),
        ("provisional", provisional_entries),
        ("quarantine", quarantine_entries),
    ):
        percentage = ((len(entries) / total) * 100.0) if total else 0.0
        print(f"{bucket_name}: {len(entries)} ({percentage:.1f}%)", flush=True)

    print("Accept bucket:", flush=True)
    for entry in accept_entries:
        score = entry["best_score"]
        score_text = f"{score:.3f}" if isinstance(score, float) else "None"
        print(
            f"- {entry['raw_name']} -> {entry['best_canonical_id']}, {score_text}",
            flush=True,
        )

    tiebreaker_entries = [
        entry
        for entry in accept_entries
        if str(entry.get("resolution_method") or "") in {"tiebreaker_layer1_token", "tiebreaker_layer2_llm"}
    ]
    if tiebreaker_entries:
        print("Tiebreaker-resolved accepts:", flush=True)
        for entry in tiebreaker_entries:
            reason = str(entry.get("tiebreaker_reason") or entry.get("reason") or "")
            print(
                f"- {entry['raw_name']} -> {entry['best_canonical_id']} "
                f"| {entry.get('resolution_method')} | {reason}",
                flush=True,
            )

    layer2_entries = [
        entry
        for entry in (accept_entries + provisional_entries)
        if str(entry.get("tiebreaker_layer") or "") == "layer2"
    ]
    if layer2_entries:
        print("Layer 2 call list:", flush=True)
        for entry in layer2_entries:
            top_score = entry.get("tiebreaker_top_score")
            top_score_text = f"{top_score:.3f}" if isinstance(top_score, float) else str(top_score)
            choice = str(entry.get("tiebreaker_choice") or "")
            if not choice:
                choice = str(entry.get("best_canonical_id") or "AMBIGUOUS")
            chosen = choice if choice != "AMBIGUOUS" else "AMBIGUOUS"
            matched_top = bool(entry.get("tiebreaker_choice_matched_top"))
            print(
                f"- {entry['raw_name']} | top={entry.get('tiebreaker_top_candidate')} "
                f"({top_score_text}) | result={chosen} | matched_top={matched_top} "
                f"| {entry.get('tiebreaker_reason')}",
                flush=True,
            )

    print("Provisional bucket:", flush=True)
    for entry in provisional_entries:
        print(
            f"- {entry['raw_name']}, {entry['metric_core']}, {entry['reason']}",
            flush=True,
        )

    print("Quarantine bucket:", flush=True)
    for entry in quarantine_entries:
        print(
            f"- {entry['raw_name']}, {entry['metric_core']}, {entry['reason']}",
            flush=True,
        )
    print(f"Layer 2 LLM calls: {TIEBREAKER_LLM_CALL_COUNT}", flush=True)


def _scope3_magnitude_guard(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quarantine Scope 3 facts whose value is implausibly small vs Scope 1."""
    scope1_vals = [
        f.get("normalised_value")
        for f in facts
        if f.get("canonical_id") == "scope_1_emissions_absolute"
        and f.get("normalised_value") is not None
    ]
    if not scope1_vals:
        return facts
    scope1_max = max(scope1_vals)
    quarantined = 0
    for f in facts:
        if f.get("canonical_id") == "scope_3_emissions_absolute":
            val = f.get("normalised_value")
            if val is not None and scope1_max > 0 and val < 0.01 * scope1_max:
                f["normalization_decision"] = "quarantine"
                f["normalization_status"] = "quarantine"
                f["quarantine_reason"] = "scope3_magnitude_implausible"
                quarantined += 1
    if quarantined:
        print(f"Scope 3 magnitude guard: quarantined {quarantined} implausible facts (scope1_max={scope1_max:.0f})", flush=True)
    return facts


def _dedup_by_canonical(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove cross-chunk duplicates where the same canonical_id+period+value appears multiple times.

    Keeps the best fact per group (normalized > partial, then earliest fact_id).
    Records the removed chunk_ids on the surviving fact's duplicate_chunk_ids field.
    """
    from collections import defaultdict
    LOAD_DECISIONS = {"normalized", "partial"}
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for f in facts:
        cid = str(f.get("canonical_id") or "").strip()
        dec = str(f.get("normalization_decision") or "").lower()
        nv = f.get("normalised_value")
        if cid and dec in LOAD_DECISIONS and nv is not None:
            key = (cid, str(f.get("period_label") or f.get("period") or ""), str(nv))
            groups[key].append(f)

    decision_rank = {"normalized": 0, "partial": 1}
    to_remove: set[str] = set()
    for group in groups.values():
        if len(group) <= 1:
            continue
        best = sorted(
            group,
            key=lambda f: (
                decision_rank.get(str(f.get("normalization_decision") or ""), 2),
                str(f.get("fact_id") or ""),
            ),
        )[0]
        for f in group:
            if f is not best:
                to_remove.add(str(f.get("fact_id") or ""))
                dups = best.setdefault("duplicate_chunk_ids", [])
                dup_cid = str(f.get("chunk_id") or "")
                if dup_cid and dup_cid not in dups:
                    dups.append(dup_cid)

    if to_remove:
        print(f"Canonical dedup: removed {len(to_remove)} cross-chunk duplicate facts", flush=True)
    return [f for f in facts if str(f.get("fact_id") or "") not in to_remove]


def run_pass2(
    pass1_path: str | Path = "pass1_output.json",
    output_path: str | Path = "pass2_output.json",
    test_mode: bool = False,
    sample_mode: bool = False,
    debug_mode: bool = False,
) -> list[dict[str, Any]]:
    pass1_facts = _preflight_check(pass1_path)
    metric_registry = _metric_registry_with_seed()
    registry_lookup = {
        str(metric.get("canonical_id", "")): metric
        for metric in metric_registry
        if str(metric.get("canonical_id", ""))
    }
    aliases_lookup = _aliases_with_seed()
    filing_metadata = _ensure_filing_metadata(pass1_path)
    condensed_registry = _condense_metric_registry(metric_registry)
    if sample_mode:
        checkpoint_by_fact_id = {}
    else:
        checkpoint_facts = _load_checkpoint_facts(output_path)
        checkpoint_by_fact_id = {
            str(fact.get("fact_id", "")): fact
            for fact in checkpoint_facts
            if (
                str(fact.get("fact_id", ""))
                and (
                    fact.get("canonical_id") is not None
                    or str(fact.get("normalization_decision", "")).lower() in {"new_metric", "quarantine"}
                )
                and str(fact.get("mapping_note", "")).strip().lower() != "batch parse error"
            )
        }

    if test_mode:
        pass1_facts = pass1_facts[:BATCH_SIZE * TEST_BATCHES]

    if sample_mode:
        pass1_facts = [
            fact for fact in pass1_facts
            if str(fact.get("decision", "")).lower() != "drop"
        ][:SAMPLE_FACTS]

    dropped_facts_by_id = {
        str(fact.get("fact_id", "")): _dropped_fact_passthrough(fact)
        for fact in pass1_facts
        if str(fact.get("decision", "")).lower() == "drop"
    }
    print(
        f"Skipping {len(dropped_facts_by_id)} dropped facts from Pass 1",
        flush=True,
    )

    pending_facts = [
        fact for fact in pass1_facts
        if str(fact.get("fact_id", "")) not in checkpoint_by_fact_id
        and str(fact.get("fact_id", "")) not in dropped_facts_by_id
    ]
    checkpoint_skipped_count = sum(
        1
        for fact in pass1_facts
        if str(fact.get("fact_id", "")) in checkpoint_by_fact_id
    )
    print(f"Skipped due to checkpoint: {checkpoint_skipped_count}", flush=True)

    # Filter financial facts out before batching so alias resolution cannot bypass the classifier.
    default_currency = str(filing_metadata.get("currency", "") or "")
    financial_by_fact_id: dict[str, dict[str, Any]] = {}
    non_financial_pending: list[dict[str, Any]] = []
    for fact in pending_facts:
        match_fact = _build_match_fact(fact)
        if _is_financial_fact(fact, match_fact):
            financial_by_fact_id[str(fact.get("fact_id", ""))] = _resolved_financial_fact(
                fact=fact,
                match_fact=match_fact,
                registry_lookup=registry_lookup,
                metadata=filing_metadata,
                default_currency=default_currency,
            )
        else:
            non_financial_pending.append(fact)
    pending_facts = non_financial_pending

    batches = _batched(pending_facts, BATCH_SIZE)

    if debug_mode:
        first_batch = batches[0] if batches else []
        messages = _build_messages(
            filing_metadata,
            condensed_registry,
            registry_lookup,
            first_batch,
        )
        debug_preview = "\n\n".join(
            f"{message['role'].upper()}:\n{message['content']}"
            for message in messages
        )
        print(f"Prompt character length: {len(debug_preview)}", flush=True)
        print("Prompt preview:", flush=True)
        print(debug_preview[:500], flush=True)
        print(
            f"Estimated tokens: {len(debug_preview) / 4:.0f}",
            flush=True,
        )
        return []

    batch_results: dict[int, list[dict[str, Any]]] = {}

    facts_normalized_so_far = 0
    total_batches = len(batches)
    for batch_index, batch in enumerate(batches, start=1):
        batch_results[batch_index] = _normalize_batch(
            batch_index=batch_index,
            input_batch=batch,
            metadata=filing_metadata,
            metric_registry=condensed_registry,
            registry_lookup=registry_lookup,
            aliases_lookup=aliases_lookup,
        )
        facts_normalized_so_far += len(batch_results[batch_index])
        print(
            f"Progress: {batch_index}/{total_batches} batches complete ({facts_normalized_so_far} facts normalized so far)",
            flush=True,
        )
        time.sleep(3)

    normalized_by_fact_id: dict[str, dict[str, Any]] = {}
    normalized_by_fact_id.update(financial_by_fact_id)
    for batch_index in sorted(batch_results):
        for fact in batch_results[batch_index]:
            fact_id = str(fact.get("fact_id", ""))
            if fact_id:
                normalized_by_fact_id[fact_id] = fact

    normalized_facts: list[dict[str, Any]] = []
    for fact in pass1_facts:
        fact_id = str(fact.get("fact_id", ""))
        if fact_id in normalized_by_fact_id:
            normalized_facts.append(normalized_by_fact_id[fact_id])
        elif fact_id in dropped_facts_by_id:
            normalized_facts.append(dropped_facts_by_id[fact_id])
        elif fact_id in checkpoint_by_fact_id:
            normalized_facts.append(checkpoint_by_fact_id[fact_id])
        else:
            normalized_facts.append(fact)

    normalized_facts = _scope3_magnitude_guard(normalized_facts)
    normalized_facts = _dedup_by_canonical(normalized_facts)
    _write_json(output_path, normalized_facts)
    summarize_pass2(normalized_facts)
    return normalized_facts


if __name__ == "__main__":
    if len(sys.argv) == 2 and not sys.argv[1].startswith("--"):
        path = sys.argv[1]
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        facts, _ = _extract_pass1_facts_and_metadata(payload, source_path=path)
        results = dry_run(facts)
        print_dry_run_summary(results)
        report = write_review_files(
            results,
            f"{Path(path).with_suffix('').name}_provisional_review",
        )
        print(
            "Provisional review queue: "
            f"{report['csv_path'].resolve()} | "
            f"{report['action_csv_path'].resolve()} | "
            f"{report['markdown_path'].resolve()}",
            flush=True,
        )
        raise SystemExit(0)

    parser = argparse.ArgumentParser(description="Run Pass 2 metric normalization")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--review-output",
        metavar="PATH",
        help="Output prefix for dry-run provisional review .csv and .md files",
    )
    parser.add_argument(
        "--input",
        default="pass1_output.json",
        metavar="PATH",
        help="Path to Pass 1 output JSON (default: pass1_output.json)",
    )
    parser.add_argument(
        "--output",
        default="pass2_output.json",
        metavar="PATH",
        help="Path to Pass 2 output JSON (default: pass2_output.json)",
    )
    parser.add_argument(
        "--summary",
        metavar="PATH",
        help="Print summary only for an existing pass2 output file",
    )
    args = parser.parse_args()

    if args.summary:
        summarize_pass2(_load_json(args.summary))
        raise SystemExit(0)

    if args.dry_run:
        payload = _load_json(args.input)
        facts, _ = _extract_pass1_facts_and_metadata(payload, source_path=args.input)
        results = dry_run(facts)
        print_dry_run_summary(results)
        output_prefix = args.review_output or f"{Path(args.input).with_suffix('').name}_provisional_review"
        report = write_review_files(results, output_prefix)
        print(
            "Provisional review queue: "
            f"{report['csv_path'].resolve()} | "
            f"{report['action_csv_path'].resolve()} | "
            f"{report['markdown_path'].resolve()}",
            flush=True,
        )
        raise SystemExit(0)

    run_pass2(
        pass1_path=args.input,
        output_path=args.output,
        test_mode=args.test,
        sample_mode=args.sample,
        debug_mode=args.debug,
    )
