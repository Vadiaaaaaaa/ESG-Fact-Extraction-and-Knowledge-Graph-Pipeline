import argparse
import json
import os
import sys
import time
import traceback
from difflib import SequenceMatcher
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
from typing import Any

from models import PASS1_SCHEMA_VERSION, Chunk, ExtractedFact
from pass1_lean_schema import PASS1_LEAN_RESPONSE_FORMAT
from pass1_prompt_balanced import PASS1_BALANCED_PROMPT_TEMPLATE
from pass1_prompt_lean import LEAN_FIELDS, PASS1_LEAN_PROMPT_TEMPLATE
from pass1_twostage import (
    PASS1A_RECALL_PROMPT_TEMPLATE,
    PASS1A_RESPONSE_FORMAT,
    PASS1B_RESPONSE_FORMAT,
    PASS1B_TYPING_PROMPT_TEMPLATE,
)
from pass1_validate import enrich_facts
from metric_registry_seed import REGISTRY as CANONICAL_REGISTRY, build_alias_index as build_canonical_alias_index

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

if "--summary" not in sys.argv:
    print("starting...", flush=True)

MODEL = "gpt-4o-mini"
MAX_CONCURRENT_CALLS = 2
API_TIMEOUT_SECONDS = 300
RETRY_WAIT_SECONDS = 10
METADATA_CONTEXT: dict[str, Any] = {}
FAST_PARAGRAPH_MODE = False
TWO_STAGE_PASS1 = True
TABLE_EXTRACTION_PREFIX = (
    "IMPORTANT: This is a financial table with multiple rows and multiple years. "
    "You MUST extract EVERY row as a SEPARATE fact object for EACH year column.\n"
    "A table with 20 rows and 3 years = 60 separate fact objects minimum. "
    "Do not summarize. Do not skip rows. Extract every single row-year combination.\n"
    "Return a JSON object with a facts array containing ALL facts.\n\n"
)
SKIP_CHUNK_ID_PATTERNS = (
    "exchange_rate",
    "exchange_rates",
    "principal_exchange",
    "companies_of_the",
    "list_of_companies",
)

PASS1_PROMPT_TEMPLATE = PASS1_LEAN_PROMPT_TEMPLATE

FAST_PASS1_PROMPT_TEMPLATE = PASS1_BALANCED_PROMPT_TEMPLATE
_CANONICAL_ALIAS_INDEX = build_canonical_alias_index()
_CANONICAL_DEFINITION_BY_ID = {
    str(entry.get("canonical_id") or ""): str(entry.get("canonical_definition") or "")
    for entry in CANONICAL_REGISTRY
    if str(entry.get("canonical_id") or "")
}
_CANONICAL_ALIAS_PAIRS = []
for _entry in CANONICAL_REGISTRY:
    _canonical_id = str(_entry.get("canonical_id") or "")
    if not _canonical_id:
        continue
    for _alias in [*_entry.get("aliases", []), _canonical_id.replace("_", " ")]:
        _alias_text = str(_alias or "").strip().lower()
        if _alias_text:
            _CANONICAL_ALIAS_PAIRS.append((_alias_text, _canonical_id))

DEFINE_PROMPT_TEMPLATE = """You are defining metric families for already extracted business facts.

For each fact below, write exactly one complete sentence describing what the metric measures in general terms.

Rules:
- Describe the METRIC FAMILY, not the specific fact instance.
- Do NOT mention numbers, percentages, counts, periods, dates, years, or company names.
- Do NOT restate the source sentence.
- Use the source sentence and fact fields to infer the metric meaning.
- For change, transition, range, or ratio facts, define the UNDERLYING METRIC being measured, not the movement.
- Do NOT use movement framing such as improvement, increase, decrease, reduction, growth, decline, target, versus, compared to, basis points, or prior year.
- The definition must describe the metric named IN THE FACT ITSELF, using the fact's own subject.
- If raw_name includes a value or movement phrase, identify the metric subject inside it and define that subject.
- Do NOT substitute a related, more technical, or more specific concept.
- Do NOT pull in taxonomy or framework terms such as Scope 1, Scope 2, Scope 3, purchased electricity, or value-chain emissions unless those exact words appear in the fact.
- The definition's subject must match the fact's subject. If the fact says CO2 emissions reduction, define CO2 emissions reduction, not a specific emissions scope or source category.
- The output must be a definition, not a label. Do not return only the raw_name, metric_core, or a short noun phrase.
- A good definition usually has 12-30 words and uses a verb such as "measures", "represents", "tracks", or "counts".
- Prefer a stable metric-family description such as equipment effectiveness, water consumption per unit, workplace injury rate, production line count, or packaging material reduction.
- Examples:
  raw_name: "manufacturing productivity" -> "Manufacturing productivity measures the efficiency with which production operations convert labor, materials, and equipment capacity into finished output."
  raw_name: "finished goods movement" -> "Finished goods movement tracks the volume of completed products handled or transported through the distribution network."
  raw_name: "warehouse dispatch efficiency" -> "Warehouse dispatch efficiency measures how effectively warehouse operations prepare and send goods for distribution or customer delivery."
- If the metric meaning is unclear from context, return metric_definition as null and definition_confidence as "low".
- If the metric meaning is clear, return definition_confidence as "high".
- Output one definition object per fact_id and preserve fact_id exactly.
"""

DEFINE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "metric_family_definitions",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "definitions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact_id": {"type": "string"},
                            "metric_definition": {"type": ["string", "null"]},
                            "definition_confidence": {"type": "string"},
                        },
                        "required": ["fact_id", "metric_definition", "definition_confidence"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["definitions"],
            "additionalProperties": False,
        },
    },
}


def _metadata_path_for_input(input_path: str | Path) -> Path:
    input_path = Path(input_path)
    name = input_path.name
    if name.endswith("_chunks.json"):
        metadata_name = name[: -len("_chunks.json")] + "_metadata.json"
    else:
        metadata_name = input_path.stem + "_metadata.json"
    return input_path.with_name(metadata_name)


def _load_metadata_for_input(input_path: str | Path) -> dict[str, Any]:
    metadata_path = _metadata_path_for_input(input_path)
    if not metadata_path.exists():
        raise FileNotFoundError(
            "No metadata file found for input — run filing_metadata.py first"
        )

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    return {
        "company_name": str(metadata.get("company_name", "")),
        "filing_type": str(metadata.get("filing_type", "")),
        "has_segments": bool(metadata.get("has_segments", False)),
        "fiscal_year_end_month": str(metadata.get("fiscal_year_end_month", "")),
        "primary_period": str(metadata.get("primary_period", "")),
    }


def _metadata_value(*keys: str, default: Any = "") -> Any:
    for key in keys:
        value = METADATA_CONTEXT.get(key)
        if value not in (None, ""):
            return value
    return default


def _primary_period_for_chunk(chunk: Chunk) -> str:
    return str(
        _metadata_value(
            "primary_period",
            "fiscal_period",
            "period",
            default=getattr(chunk.temporal_context, "primary_period", ""),
        )
    )


def _validation_context_for_chunk(chunk: Chunk) -> dict[str, Any]:
    return {
        "company": _metadata_value("company_name", "company", default=""),
        "fiscal_period": _primary_period_for_chunk(chunk),
        "primary_period": _primary_period_for_chunk(chunk),
        "fiscal_year_end_month": _metadata_value(
            "fiscal_year_end_month",
            default=getattr(chunk.temporal_context, "fiscal_year_end", ""),
        ),
        "filing_type": _metadata_value("filing_type", default=""),
        "section": chunk.section_title,
        "has_disclosed_segments": _metadata_value("has_segments", "has_disclosed_segments", default=False),
    }


def is_financial_table(chunk: dict[str, Any]) -> bool:
    content = str(chunk.get("content", ""))
    return any(
        indicator in content
        for indicator in ["CHF", "USD", "EUR", "GBP", "%"]
    )


def _is_excluded_table_chunk(chunk: dict[str, Any]) -> bool:
    return (
        chunk.get("chunk_type") == "table"
        and any(
            pattern in str(chunk.get("chunk_id", "")).lower()
            for pattern in SKIP_CHUNK_ID_PATTERNS
        )
    )


def _render_system_prompt(chunk: Chunk) -> str:
    filing_year = chunk.temporal_context.filing_year
    historical_reprint_context = ""
    if chunk.temporal_context.is_historical_reprint:
        historical_reprint_context = f"""

IMPORTANT: This is a REPRINTED HISTORICAL DOCUMENT. The filing year is {filing_year} but this content is from a past year.

Detect the actual year from the content (look for explicit year references like "in 1997", "fiscal year ended December 31, 1997").

Assign ALL facts to the year found in the content, NOT to {filing_year}.

Set fact_type = "historical_reprint" for all facts extracted from this section.
"""

    replacements = {
        "company": _metadata_value("company_name", "company", default=""),
        "fiscal_period": _primary_period_for_chunk(chunk),
        "fiscal_year_end_month": _metadata_value(
            "fiscal_year_end_month",
            default=getattr(chunk.temporal_context, "fiscal_year_end", ""),
        ),
        "filing_type": _metadata_value("filing_type", default=""),
        "section": chunk.section_title,
        "has_disclosed_segments": str(
            _metadata_value("has_segments", "has_disclosed_segments", default=False)
        ).lower(),
        "historical_reprint_context": historical_reprint_context,
    }

    prompt = FAST_PASS1_PROMPT_TEMPLATE if FAST_PARAGRAPH_MODE else PASS1_PROMPT_TEMPLATE
    for key, value in replacements.items():
        prompt = prompt.replace("{" + key + "}", str(value))
    prompt = prompt.replace("{section_text}", chunk.content)
    return prompt


def _prompt_replacements(chunk: Chunk) -> dict[str, str]:
    filing_year = chunk.temporal_context.filing_year
    historical_reprint_context = ""
    if chunk.temporal_context.is_historical_reprint:
        historical_reprint_context = f"""

IMPORTANT: This is a REPRINTED HISTORICAL DOCUMENT. The filing year is {filing_year} but this content is from a past year.

Detect the actual year from the content (look for explicit year references like "in 1997", "fiscal year ended December 31, 1997").

Assign ALL facts to the year found in the content, NOT to {filing_year}.

Set fact_type = "historical_reprint" for all facts extracted from this section.
"""
    return {
        "company": str(_metadata_value("company_name", "company", default="")),
        "fiscal_period": _primary_period_for_chunk(chunk),
        "fiscal_year_end_month": str(
            _metadata_value(
                "fiscal_year_end_month",
                default=getattr(chunk.temporal_context, "fiscal_year_end", ""),
            )
        ),
        "filing_type": str(_metadata_value("filing_type", default="")),
        "section": str(chunk.section_title),
        "has_disclosed_segments": str(
            _metadata_value("has_segments", "has_disclosed_segments", default=False)
        ).lower(),
        "historical_reprint_context": historical_reprint_context,
    }


def _render_prompt_template(
    template: str,
    chunk: Chunk,
    *,
    section_text: str | None = None,
    candidates_json: str | None = None,
) -> str:
    prompt = template
    for key, value in _prompt_replacements(chunk).items():
        prompt = prompt.replace("{" + key + "}", value)
    prompt = prompt.replace("{section_text}", section_text if section_text is not None else chunk.content)
    if candidates_json is not None:
        prompt = prompt.replace("{candidates_json}", candidates_json)
    return prompt


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _looks_like_markdown_separator(cells: list[str]) -> bool:
    return all(cell.replace("-", "").replace(":", "").strip() == "" for cell in cells)


def _is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _clone_chunk_with_content(chunk: Chunk, chunk_id: str, content: str) -> Chunk:
    return Chunk(
        doc_id=chunk.doc_id,
        section_id=chunk.section_id,
        chunk_id=chunk_id,
        section_title=chunk.section_title,
        parent_section=chunk.parent_section,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        chunk_type=chunk.chunk_type,
        content=content,
        char_count=len(content),
        token_estimate=max(1, (len(content) + 3) // 4) if content else 0,
        is_historical_reprint=chunk.is_historical_reprint,
        temporal_context=chunk.temporal_context,
    )


def _split_large_table_chunk(chunk: Chunk) -> list[Chunk]:
    if chunk.chunk_type != "table" or chunk.token_estimate <= 400:
        return [chunk]

    lines = chunk.content.splitlines()
    separator_index = next(
        (
            index
            for index, line in enumerate(lines)
            if _is_markdown_table_line(line)
            and _looks_like_markdown_separator(_split_markdown_row(line))
        ),
        None,
    )
    if separator_index is None or separator_index == 0:
        return [chunk]

    header_index = separator_index - 1
    header_line = lines[header_index].rstrip()
    separator_line = lines[separator_index].rstrip()
    preamble_lines = lines[:header_index]

    last_table_row_index = None
    for index in range(len(lines) - 1, separator_index, -1):
        if _is_markdown_table_line(lines[index]):
            last_table_row_index = index
            break

    if last_table_row_index is None or last_table_row_index <= separator_index:
        return [chunk]

    data_rows = [
        lines[index].rstrip()
        for index in range(separator_index + 1, last_table_row_index + 1)
        if _is_markdown_table_line(lines[index])
    ]
    if len(data_rows) <= 20:
        return [chunk]

    footer_lines = lines[last_table_row_index + 1 :]
    sub_chunks: list[Chunk] = []
    for sub_index, start in enumerate(range(0, len(data_rows), 20), start=1):
        row_group = data_rows[start : start + 20]
        content_parts: list[str] = []
        if preamble_lines:
            content_parts.append("\n".join(preamble_lines).strip())
        content_parts.append(header_line)
        content_parts.append(separator_line)
        content_parts.append("\n".join(row_group))
        if footer_lines:
            content_parts.append("\n".join(footer_lines).strip())

        sub_content = "\n".join(part for part in content_parts if part)
        sub_chunks.append(
            _clone_chunk_with_content(
                chunk,
                f"{chunk.chunk_id}_part_{sub_index}",
                sub_content,
            )
        )

    if len(sub_chunks) > 1:
        print(
            f"Splitting large table: {chunk.chunk_id} into {len(sub_chunks)} sub-chunks",
            flush=True,
        )
        return sub_chunks

    return [chunk]


def _extract_markdown_table_facts(chunk: Chunk) -> dict[str, list[dict[str, Any]]]:
    rows = [
        _split_markdown_row(line)
        for line in chunk.content.splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    ]
    if len(rows) < 2:
        return {"facts": []}

    header = rows[0]
    facts: list[dict[str, Any]] = []
    data_rows = rows[2:] if _looks_like_markdown_separator(rows[1]) else rows[1:]

    for row in data_rows:
        if len(row) < 2:
            continue

        metric = row[0].strip()
        values = row[1:]
        if not metric or not any(value.strip() for value in values):
            continue

        for column_name, raw_value in zip(header[1:], values):
            raw_value = raw_value.strip()
            period = column_name.strip()
            if not raw_value or raw_value == "-":
                continue

            facts.append(
                {
                    "raw_name": metric,
                    "raw_label_type": "metric_label",
                    "raw_value": raw_value,
                    "raw_unit": "millions",
                    "raw_period": period,
                    "resolved_period_start": f"{period}-01-01" if period.isdigit() else None,
                    "resolved_period_end": f"{period}-12-31" if period.isdigit() else None,
                    "period_type": "annual" if period.isdigit() else "unknown",
                    "period_resolution": "inferred" if period.isdigit() else "unresolvable",
                    "fact_type": (
                        "historical_reprint"
                        if chunk.temporal_context.is_historical_reprint
                        else (
                            "actual"
                            if period == str(chunk.temporal_context.filing_year)
                            else "comparative_reference"
                        )
                    ),
                    "scope": "consolidated",
                    "dimension_type": "none",
                    "dimension_member": None,
                    "graph_fact_type": "financial_metric",
                    "breakdown_flag": False,
                    "driver_flag": False,
                    "driver_phrase": None,
                    "parent_metric_hint": None,
                    "component_flag": False,
                    "contribution_flag": False,
                    "source_sentence": f"{chunk.section_title} table row: {metric}; {period}: {raw_value}",
                    "check_specific_number": True,
                    "check_unit_clear": True,
                    "check_period_determinable": True if period.isdigit() else False,
                    "check_is_actual": True,
                    "check_unambiguous": True,
                    "confidence": "high" if period.isdigit() else "low",
                    "failed_checks": [] if period.isdigit() else ["check_period_determinable"],
                    "restatement_flag": False,
                    "rescue_possible": False,
                    "rescue_note": None,
                    "adjustment_note": "Extracted by deterministic markdown-table fallback after API timeout.",
                    "decision": "keep" if period.isdigit() else "drop",
                }
            )

    print(
        f"Markdown table fallback extracted {len(facts)} facts for {chunk.chunk_id}",
        flush=True,
    )
    return {"facts": facts}


def _apply_local_fact_defaults(raw_fact: dict[str, Any]) -> dict[str, Any]:
    fact = dict(raw_fact)
    defaults = {
        "raw_label_type": "metric_label",
        "period_resolution": "inferred",
        "dimension_type": "none",
        "dimension_member": None,
        "graph_fact_type": "financial_metric",
        "breakdown_flag": False,
        "driver_flag": False,
        "driver_phrase": None,
        "parent_metric_hint": None,
        "component_flag": False,
        "contribution_flag": False,
        "check_specific_number": True,
        "check_unit_clear": True,
        "check_period_determinable": True,
        "check_is_actual": True,
        "check_unambiguous": True,
        "failed_checks": [],
        "restatement_flag": False,
        "rescue_possible": False,
        "rescue_note": None,
        "adjustment_note": "",
        "confidence": "high",
        "decision": "keep",
        "metric_definition": None,
        "definition_confidence": "low",
        "low_confidence": False,
        "baseline_year": None,
    }
    for key, value in defaults.items():
        fact.setdefault(key, value)

    if "check_unambiguous_meaning" not in fact:
        fact["check_unambiguous_meaning"] = "yes" if fact.get("check_unambiguous", True) else "no"
    if "segment_flag" not in fact:
        fact["segment_flag"] = fact.get("scope") == "segment"
    if "segment_name" not in fact:
        fact["segment_name"] = ""

    return fact


def _call_structured_completion(
    client: Any,
    *,
    system_prompt: str,
    user_content: str,
    response_format: dict[str, Any],
) -> tuple[Any, dict[str, Any], str]:
    response = client.chat.completions.create(
        model=MODEL,
        response_format=response_format,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        timeout=API_TIMEOUT_SECONDS,
    )
    raw_content = response.choices[0].message.content or "{}"
    response_json = json.loads(raw_content)
    return response, response_json, raw_content


def _attach_metric_definitions(
    client: Any,
    chunk: Chunk,
    facts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not facts:
        return facts, []

    definition_telemetry: list[dict[str, Any]] = []
    fact_batches = _batched(facts, 25)
    for batch_index, fact_batch in enumerate(fact_batches, start=1):
        payload = {
            "facts": [
                {
                    "fact_id": str(fact.get("fact_id") or f"{chunk.chunk_id}_fact_{index}"),
                    "raw_name": str(fact.get("raw_name") or ""),
                    "raw_value": str(fact.get("raw_value") or ""),
                    "raw_unit": str(fact.get("raw_unit") or ""),
                    "fact_class": str(fact.get("fact_class") or ""),
                    "metric_core": str(fact.get("metric_core") or ""),
                    "parent_metric_hint": str(fact.get("parent_metric_hint") or ""),
                    "source_sentence": str(fact.get("source_sentence") or ""),
                }
                for index, fact in enumerate(fact_batch, start=1)
            ]
        }
        batch_start = time.monotonic()
        try:
            response, response_json, raw_response = _call_structured_completion(
                client,
                system_prompt=DEFINE_PROMPT_TEMPLATE,
                user_content=json.dumps(payload, ensure_ascii=False, indent=2),
                response_format=DEFINE_RESPONSE_FORMAT,
            )
        except Exception as exc:
            for fact in fact_batch:
                fact["metric_definition"] = None
                fact["definition_confidence"] = "low"
                fact["low_confidence"] = True
                fact["confidence"] = "low"
            definition_telemetry.append(
                {
                    "batch_index": batch_index,
                    "fact_count": len(fact_batch),
                    "timing_seconds": time.monotonic() - batch_start,
                    "error": repr(exc),
                }
            )
            continue

        definition_map = {
            str(item.get("fact_id") or ""): item
            for item in (response_json.get("definitions", []) if isinstance(response_json, dict) else [])
            if isinstance(item, dict)
        }
        for fact in fact_batch:
            fact_id = str(fact.get("fact_id") or "")
            definition_record = definition_map.get(fact_id, {})
            metric_definition = _sanitize_metric_definition(
                fact,
                definition_record.get("metric_definition"),
            )
            definition_confidence = str(definition_record.get("definition_confidence") or "low").lower()
            fact["metric_definition"] = metric_definition
            fact["definition_confidence"] = definition_confidence
            fact["low_confidence"] = metric_definition is None or definition_confidence == "low"
            if metric_definition is None:
                fact["confidence"] = "low"

        batch_usage = None
        if getattr(response, "usage", None) is not None:
            batch_usage = (
                response.usage.model_dump()
                if hasattr(response.usage, "model_dump")
                else dict(response.usage)
            )
        definition_telemetry.append(
            {
                "batch_index": batch_index,
                "fact_count": len(fact_batch),
                "timing_seconds": time.monotonic() - batch_start,
                "usage": batch_usage,
                "raw_preview": raw_response[:300],
            }
        )

    return facts, definition_telemetry


_DEFINITION_MOVEMENT_RE = re.compile(
    r"\b(improvement|improved|increase|increased|decrease|decreased|reduction|reduced|growth|grew|decline|declined|target|versus|compared|comparison|basis points?|bps|percentage points?)\b",
    re.IGNORECASE,
)

_DEFINITION_TAXONOMY_RE = re.compile(
    r"\b(scope 1|scope 2|scope 3|purchased electricity|purchased energy|steam|heating|cooling|"
    r"indirect greenhouse gas|direct greenhouse gas|value chain emissions?)\b",
    re.IGNORECASE,
)


def _definition_template_from_fact(fact: dict[str, Any]) -> str:
    original_metric_label = _clean_text_value(
        fact.get("parent_metric_hint")
        or fact.get("metric_core")
        or fact.get("raw_name")
    )
    metric_label = original_metric_label
    metric_label = metric_label.replace("_", " ")
    exact_metric_label = re.sub(r"\s+", " ", metric_label).strip(" ,.-")
    stripped_metric_label = re.sub(_DEFINITION_MOVEMENT_RE, " ", metric_label)
    stripped_metric_label = re.sub(r"\s+", " ", stripped_metric_label).strip(" ,.-")
    if not exact_metric_label and not stripped_metric_label:
        return ""

    candidate_variants: list[str] = []
    for label in (exact_metric_label, stripped_metric_label):
        if not label:
            continue
        candidate_variants.extend(
            [
                label,
                label.lower(),
                label.replace("-", " "),
                label.lower().replace("-", " "),
            ]
        )
    seen_candidates: set[str] = set()
    candidates = []
    for candidate in candidate_variants:
        normalized = candidate.strip()
        if normalized and normalized.lower() not in seen_candidates:
            seen_candidates.add(normalized.lower())
            candidates.append(normalized)

    for candidate in candidates:
        canonical_id = _CANONICAL_ALIAS_INDEX.get(candidate.lower())
        if canonical_id:
            canonical_definition = _CANONICAL_DEFINITION_BY_ID.get(canonical_id, "")
            if canonical_definition:
                return canonical_definition
    best_match_score = 0.0
    best_match_id = ""
    for candidate in candidates:
        normalized_candidate = candidate.lower().strip()
        if not normalized_candidate:
            continue
        for alias_text, canonical_id in _CANONICAL_ALIAS_PAIRS:
            score = SequenceMatcher(None, normalized_candidate, alias_text).ratio()
            if score > best_match_score:
                best_match_score = score
                best_match_id = canonical_id
    if best_match_score >= 0.58 and best_match_id:
        canonical_definition = _CANONICAL_DEFINITION_BY_ID.get(best_match_id, "")
        if canonical_definition:
            return canonical_definition

    raw_unit = _clean_text_value(fact.get("raw_unit"))
    unit_lower = raw_unit.lower()
    metric_label = stripped_metric_label or exact_metric_label
    if any(token in unit_lower for token in ["%", "percent", "percentage", "bps", "basis points"]):
        return f"The rate, share, or level of {metric_label.lower()}."
    if any(token in unit_lower for token in ["hour", "minute", "day", "month", "year"]):
        return f"The amount of time associated with {metric_label.lower()}."
    if any(token in unit_lower for token in ["ton", "tonne", "kg", "gram", "lit", "kl", "gallon"]):
        return f"The quantity or intensity of {metric_label.lower()}."
    if any(token in unit_lower for token in ["inr", "usd", "eur", "gbp", "crore", "lakh", "currency"]):
        return f"The monetary amount associated with {metric_label.lower()}."
    return f"The business metric measuring {metric_label.lower()}."


def _definition_introduces_unanchored_taxonomy(fact: dict[str, Any], definition: str) -> bool:
    definition_text = str(definition or "").lower()
    if not definition_text:
        return False
    definition_terms = {match.group(0).lower() for match in _DEFINITION_TAXONOMY_RE.finditer(definition_text)}
    if not definition_terms:
        return False

    fact_text = " ".join(
        str(
            fact.get(key) or ""
        )
        for key in ("raw_name", "metric_core", "parent_metric_hint", "source_sentence")
    ).lower()
    return any(term not in fact_text for term in definition_terms)


def _sanitize_metric_definition(fact: dict[str, Any], metric_definition: Any) -> str | None:
    fallback = _definition_template_from_fact(fact)
    if not isinstance(metric_definition, str):
        return fallback or None
    definition = " ".join(metric_definition.split()).strip()
    if not definition:
        return fallback or None
    if _DEFINITION_MOVEMENT_RE.search(definition):
        return fallback or definition
    if _definition_introduces_unanchored_taxonomy(fact, definition):
        return fallback or definition
    return definition


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        key = (
            str(candidate.get("source_sentence") or "").strip(),
            str(candidate.get("raw_value_candidate") or "").strip(),
            str(candidate.get("value_unit_raw") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    for index, candidate in enumerate(deduped, start=1):
        candidate["candidate_id"] = f"c{index:03d}"
    return deduped


_NUMBER_WORD_RE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|hundred|thousand|million|billion|lakh|crore|"
    r"double|triple|threefold|fourfold|fivefold)\b",
    re.IGNORECASE,
)
_DIGIT_RE = re.compile(r"\d")
_JUNK_VALUE_RE = re.compile(r"^(?:unknown|n/?a|na|nil|none|percentage|percent|days?|years?|months?|quarters?)$", re.IGNORECASE)
_DOC_MECHANICAL_RE = re.compile(
    r"\b(?:page|pages|section|annexure|appendix|exhibit|rule|regulation|clause)\b",
    re.IGNORECASE,
)
_CHANGE_WORD_RE = re.compile(r"\b(increas(?:e|ed|ing)|decreas(?:e|ed|ing)|improv(?:e|ed|ing)|reduc(?:e|ed|tion)|surg(?:e|ed)|rose|grew|declin(?:e|ed)|up|down)\b", re.IGNORECASE)
_RANGE_CONTEXT_RE = re.compile(r"\b(pack size|pack sizes|range|ranging|between|capable of producing)\b", re.IGNORECASE)
_PAIR_PATTERN_RE = re.compile(r"\bfrom\b|\bversus\b|\bvs\.?\b|\bcompared with\b|\bcompared to\b", re.IGNORECASE)
_CHANGE_COMPONENT_RE = re.compile(
    r"\b(?:by|of)\s+("
    r"(?:~\s*)?\d[\d,]*\.?\d*\s*(?:%|bps|basis points|percentage points|points|days?|months?|years?)"
    r")",
    re.IGNORECASE,
)
_DECREASE_DIRECTION_RE = re.compile(
    r"\b(reduc(?:e|ed|tion)|decreas(?:e|ed|ing)|declin(?:e|ed|ing)|fell|fall|"
    r"down|lower|lesser|drop(?:ped)?|reduction)\b",
    re.IGNORECASE,
)
_INCREASE_DIRECTION_RE = re.compile(
    r"\b(improv(?:e|ed|ement|ing)|increas(?:e|ed|ing)|grew|growth|rose|rise|"
    r"up|higher|expanded?|gain(?:ed)?)\b",
    re.IGNORECASE,
)
_UNCHANGED_DIRECTION_RE = re.compile(r"\b(unchanged|flat|stable|steady)\b", re.IGNORECASE)
_REACHED_DIRECTION_RE = re.compile(
    r"\b(reached|achieved|stood at|total(?:ed|led)?|amounted to)\b",
    re.IGNORECASE,
)
_BASELINE_YEAR_TOKEN = r"(?:FY\s*\d{2}|(?:19|20)\d{2})"
_BASELINE_YEAR_RE = re.compile(
    rf"\b(?:vs\.?|versus|against|since|from|compared to|compared with|relative to)\s+"
    rf"(?:the\s+)?(?:baseline\s+year\s+|base\s+year\s+)?({_BASELINE_YEAR_TOKEN})\s*"
    rf"(?:baseline|base year|base)?\b"
    rf"|\b(?:baseline\s+year|base\s+year|baseline)\s+(?:of\s+)?({_BASELINE_YEAR_TOKEN})\b"
    rf"|\b({_BASELINE_YEAR_TOKEN})\s*(?:baseline|base year)\b",
    re.IGNORECASE,
)
_CHANGE_LABEL_RE = re.compile(
    r"\b(growth|increase|decrease|improvement|reduction|decline|gain|surge|rise|fall|drop|upturn|downturn)\b",
    re.IGNORECASE,
)
_DELTA_UNIT_RE = re.compile(
    r"\b(%|percent|percentage|bps|basis points|percentage points|points|days?|months?|years?)\b",
    re.IGNORECASE,
)
_GENERIC_ENTITY_METRIC_RE = re.compile(
    r"^(productivity|efficiency|capacity|output|throughput|pack sizes?|packs?|production|growth|utilization)$",
    re.IGNORECASE,
)
_ENTITY_HINT_RE = re.compile(
    r"\b(line|plant|facility|factory|office|warehouse|agent|farm|hair oil|solar power plant|bottle line|pet line)\b",
    re.IGNORECASE,
)
_SENTENCE_METRIC_HINT_RE = re.compile(
    r"\b(productivity|efficiency|capacity|output|pack size|sales|growth|share|investment|capex|emissions|reduction)\b",
    re.IGNORECASE,
)
_NUMERIC_SPAN_RE = re.compile(
    r"(?:INR\s*)?(?:~\s*)?(?:more than\s+|over\s+|approximately\s+|approx\.?\s+)?"
    r"\d[\d,]*\.?\d*\s*(?:%|bps|basis points|crore|lakh|million|billion|"
    r"MW|TPH|ml|mL|l|L|kg|g|kL/Ton|kL|tonnes?|cases/person|packs|years?|months?|days?|hours?|units?|setups?|Agents?|Warehouses?|Farms?)?",
    re.IGNORECASE,
)
_LEADING_VALUE_LABEL_RE = re.compile(
    r"^[\*\-\u2022]?\s*(?:INR\s*)?(?:~\s*)?(?:more than\s+|over\s+|approximately\s+|approx\.?\s+)?"
    r"(?P<value>\d[\d,]*\.?\d*\s*(?:%|bps|basis points|crore|lakh|million|billion|"
    r"MW(?:\s*DC)?|TPH|ml|mL|l|L|kg|g|kL/Ton|kL|tonnes?|cases/person|packs|years?|months?|days?|hours?)?)"
    r"\s+(?P<label>[A-Za-z][A-Za-z&/\-\(\) ]{2,})$",
    re.IGNORECASE,
)
_TRAILING_VALUE_LABEL_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z&/\-\(\) ]{2,}?)\s+(?P<value>\d[\d,]*\.?\d*)\s*$",
    re.IGNORECASE,
)


def _clean_text_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = " ".join(text.split())
    return text


def _title_like_phrase(text: str) -> str:
    text = _clean_text_value(text)
    if not text:
        return ""
    text = re.sub(r"^[\*\-\u2022]+\s*", "", text)
    return text.strip(" .,:;|-")


def _looks_numericish(value: str) -> bool:
    if not value:
        return False
    return bool(_DIGIT_RE.search(value) or _NUMBER_WORD_RE.search(value))


def _sanitize_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for candidate in candidates:
        source_sentence = _clean_text_value(candidate.get("source_sentence"))
        raw_value_candidate = _clean_text_value(candidate.get("raw_value_candidate"))
        prior_value = _clean_text_value(candidate.get("prior_value"))
        value_unit_raw = _clean_text_value(candidate.get("value_unit_raw"))
        raw_name_hint = _clean_text_value(candidate.get("raw_name_hint"))
        extraction_note = _clean_text_value(candidate.get("extraction_note"))

        if not source_sentence:
            dropped.append({"candidate": candidate, "reason": "missing_source_sentence"})
            continue
        if not raw_value_candidate:
            dropped.append({"candidate": candidate, "reason": "missing_raw_value_candidate"})
            continue
        if _JUNK_VALUE_RE.fullmatch(raw_value_candidate):
            dropped.append({"candidate": candidate, "reason": "junk_raw_value_candidate"})
            continue
        if not _looks_numericish(raw_value_candidate):
            dropped.append({"candidate": candidate, "reason": "non_numeric_raw_value_candidate"})
            continue
        if _DOC_MECHANICAL_RE.search(source_sentence) and not _looks_numericish(raw_value_candidate):
            dropped.append({"candidate": candidate, "reason": "doc_mechanical_candidate"})
            continue

        cleaned = dict(candidate)
        cleaned["source_sentence"] = source_sentence
        cleaned["raw_value_candidate"] = raw_value_candidate
        cleaned["prior_value"] = prior_value or None
        cleaned["value_unit_raw"] = value_unit_raw or None
        cleaned["raw_name_hint"] = raw_name_hint or None
        cleaned["extraction_note"] = extraction_note or None
        kept.append(cleaned)
    return kept, dropped


def _batched(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def _normalize_dedup_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u00a0", " ")
        .replace("?", " ")
    )
    text = " ".join(text.split())
    return text


_GENERIC_METRIC_TOKENS = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "in",
    "to",
    "for",
    "your",
    "company",
    "its",
    "our",
    "their",
    "this",
    "that",
    "metric",
    "value",
    "launch",
    "launched",
    "achieved",
    "reached",
    "decrease",
    "decreased",
    "increase",
    "increased",
    "reduction",
    "reduced",
}

_GENERIC_UNITS = {"million", "billion", "crore", "lakh", "%", "percentage", "percent", "year", "years", "count"}
_DISPLAY_NAME_BAD_PHRASES = {
    "percentage points",
    "basis points",
    "point",
    "points",
    "of total revenue",
    "of revenue",
    "of sales",
}


def _normalize_unit_for_dedup(value: Any) -> str:
    unit = _normalize_dedup_text(value)
    replacements = {
        "percentage": "%",
        "percent": "%",
        "year": "years",
        "million": "million",
    }
    return replacements.get(unit, unit)


def _normalize_numeric_for_dedup(value: Any) -> str:
    text = _normalize_dedup_text(value)
    if not text:
        return ""
    text = text.replace("~", "").replace("approximately", "").replace("approx", "").replace("`", "")
    text = text.strip()
    match = re.search(r"-?\d[\d,]*\.?\d*", text)
    if not match:
        return text
    numeric = match.group(0).replace(",", "")
    try:
        number = float(numeric)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _normalize_metric_for_dedup(value: Any) -> str:
    text = _normalize_dedup_text(value)
    if not text:
        return ""
    text = re.sub(r"-?\d[\d,]*\.?\d*", " ", text)
    text = re.sub(r"[^a-z% ]+", " ", text)
    tokens = []
    for token in text.split():
        if token in _GENERIC_METRIC_TOKENS:
            continue
        if token.endswith("s") and len(token) > 4:
            token = token[:-1]
        tokens.append(token)
    return " ".join(sorted(dict.fromkeys(tokens)))


def _looks_like_bare_metric_name(raw_name: str, raw_value: str | None = None) -> bool:
    raw_name = _clean_text_value(raw_name)
    raw_value = _clean_text_value(raw_value)
    if not raw_name:
        return True
    if raw_value and _normalize_dedup_text(raw_name) == _normalize_dedup_text(raw_value):
        return True
    if re.fullmatch(r"[\d\s,\.%~`$-]+", raw_name):
        return True
    normalized = _normalize_metric_for_dedup(raw_name)
    if not normalized:
        return True
    return False


def _humanize_metric_core(metric_core: str) -> str:
    metric_core = _clean_text_value(metric_core)
    if not metric_core:
        return ""
    if metric_core.isupper() and len(metric_core) <= 8:
        return metric_core
    words = []
    for token in metric_core.replace("/", " ").split("_"):
        token = token.strip()
        if not token:
            continue
        if token.isupper() and len(token) <= 8:
            words.append(token)
        elif token.lower() in {"yoy", "qoq", "ghg", "oee", "pet", "uht", "csd", "aho", "vho"}:
            words.append(token.upper())
        else:
            words.append(token.lower())
    return " ".join(words).strip()


def _should_fallback_to_metric_core(
    raw_name: str,
    raw_value: str,
    raw_unit: str,
    metric_core: str,
) -> bool:
    raw_name = _clean_text_value(raw_name)
    raw_value = _clean_text_value(raw_value)
    raw_unit = _clean_text_value(raw_unit)
    metric_core = _clean_text_value(metric_core)
    if not metric_core:
        return False
    if _looks_like_bare_metric_name(raw_name, raw_value):
        return True

    lowered = raw_name.lower()
    if lowered in _DISPLAY_NAME_BAD_PHRASES:
        return True
    if lowered.startswith(("of ", "to ", "from ", "by ", "up ", "down ")):
        return True

    normalized_raw_name = _normalize_metric_for_dedup(raw_name)
    normalized_metric_core = _normalize_metric_for_dedup(metric_core.replace("_", " "))
    if not normalized_raw_name and normalized_metric_core:
        return True

    if raw_unit and lowered == raw_unit.lower():
        return True

    if normalized_raw_name in {"percentage point", "basis point", "point"}:
        return True

    return False


def _derive_metric_name_from_context(
    raw_name: str,
    raw_value: str,
    raw_unit: str,
    source_sentence: str,
    parent_hint: str,
    metric_core: str = "",
) -> str:
    raw_name = _clean_text_value(raw_name)
    raw_value = _clean_text_value(raw_value)
    raw_unit = _clean_text_value(raw_unit)
    source_sentence = _clean_text_value(source_sentence)
    parent_hint = _clean_text_value(parent_hint)

    if raw_name and not _should_fallback_to_metric_core(raw_name, raw_value, raw_unit, metric_core):
        return raw_name
    if parent_hint:
        return parent_hint
    if metric_core:
        humanized = _humanize_metric_core(metric_core)
        if humanized:
            return humanized

    if source_sentence:
        sentence = re.sub(r"\s+", " ", source_sentence)
        if raw_value:
            match = re.search(
                rf"{re.escape(raw_value)}\s+(?P<label>[A-Za-z][A-Za-z&/\-\(\) ]{{2,}}?)(?:$|[,.])",
                sentence,
                re.IGNORECASE,
            )
            if match:
                return _title_like_phrase(match.group("label"))
        lead_match = _LEADING_VALUE_LABEL_RE.match(sentence)
        if lead_match:
            return _title_like_phrase(lead_match.group("label"))
        trail_match = _TRAILING_VALUE_LABEL_RE.search(sentence)
        if trail_match and raw_value and trail_match.group("value") == raw_value:
            return _title_like_phrase(trail_match.group("label"))

    if raw_unit and raw_unit.lower() not in {"inr", "usd", "eur", "gbp", "%", "count", "million", "billion", "crore", "lakh"}:
        return raw_unit
    return raw_name


def _numeric_count_in_text(value: Any) -> int:
    text = str(value or "")
    return len(re.findall(r"-?\d[\d,]*\.?\d*", text))


def _fact_dedup_key(fact: ExtractedFact) -> tuple[str, str, str, str]:
    raw = fact.raw or {}
    source_sentence = _normalize_dedup_text(raw.get("source_sentence"))
    raw_value = _normalize_dedup_text(raw.get("raw_value", fact.value))
    raw_unit = _normalize_dedup_text(raw.get("raw_unit", fact.unit))
    metric = _normalize_dedup_text(raw.get("raw_name", fact.metric))
    return (source_sentence, raw_value, raw_unit, metric)


def _fact_same_sentence_key(fact: ExtractedFact) -> tuple[str, str, str]:
    raw = fact.raw or {}
    return (
        _normalize_dedup_text(raw.get("source_sentence")),
        _normalize_numeric_for_dedup(raw.get("raw_value", fact.value)),
        _normalize_unit_for_dedup(raw.get("raw_unit", fact.unit)),
    )


def _fact_semantic_key(fact: ExtractedFact) -> tuple[str, str, str, str, str]:
    raw = fact.raw or {}
    return (
        _normalize_metric_for_dedup(raw.get("raw_name", fact.metric)),
        _normalize_numeric_for_dedup(raw.get("raw_value", fact.value)),
        _normalize_unit_for_dedup(raw.get("raw_unit", fact.unit)),
        _normalize_dedup_text(raw.get("dimension_member")),
        _normalize_dedup_text(raw.get("parent_metric_hint")),
    )


def _metric_quality(fact: ExtractedFact) -> int:
    raw_name = str((fact.raw or {}).get("raw_name", fact.metric) or "").strip()
    if not raw_name:
        return 0
    score = 0
    if re.search(r"[A-Za-z]", raw_name):
        score += 3
    if not re.match(r"^\s*\d", raw_name):
        score += 2
    normalized = _normalize_metric_for_dedup(raw_name)
    score += len([t for t in normalized.split() if t])
    if re.fullmatch(r"[\d\s,\.%~`-]+", raw_name):
        score -= 4
    return score


def _unit_quality(fact: ExtractedFact) -> int:
    raw_unit = str((fact.raw or {}).get("raw_unit", fact.unit) or "").strip()
    unit = _normalize_unit_for_dedup(raw_unit)
    if not unit:
        return 0
    if unit in _GENERIC_UNITS:
        return 1
    return 3


def _has_specific_entity_binding(fact: ExtractedFact) -> bool:
    raw = fact.raw or {}
    if _clean_text_value(raw.get("dimension_member")) or _clean_text_value(raw.get("parent_metric_hint")):
        return True
    raw_name = _clean_text_value(raw.get("raw_name", fact.metric))
    return bool(raw_name and not _GENERIC_ENTITY_METRIC_RE.fullmatch(raw_name))


def _is_generic_metric_name(fact: ExtractedFact) -> bool:
    raw_name = _clean_text_value((fact.raw or {}).get("raw_name", fact.metric)).lower()
    return bool(raw_name) and bool(_GENERIC_ENTITY_METRIC_RE.fullmatch(raw_name))


def _fact_anchor_family(fact: ExtractedFact) -> str:
    raw = fact.raw or {}
    parent_hint = _clean_text_value(raw.get("parent_metric_hint"))
    if parent_hint:
        return _normalize_metric_for_dedup(parent_hint)
    raw_name = _clean_text_value(raw.get("raw_name", fact.metric))
    return _normalize_metric_for_dedup(raw_name)


def _fact_anchor_key(fact: ExtractedFact) -> tuple[str, str, str, str, str, str, str]:
    raw = fact.raw or {}
    fact_class = _normalize_dedup_text(raw.get("fact_class"))
    family = _fact_anchor_family(fact)
    unit = _normalize_unit_for_dedup(raw.get("raw_unit", fact.unit))
    old_value = _normalize_numeric_for_dedup(raw.get("old_value") or raw.get("prior_value"))
    new_value = _normalize_numeric_for_dedup(raw.get("new_value") or raw.get("raw_value", fact.value))
    change_value = _normalize_numeric_for_dedup(raw.get("change_value"))
    range_value = "|".join(
        [
            _normalize_numeric_for_dedup(raw.get("range_min")),
            _normalize_numeric_for_dedup(raw.get("range_max")),
        ]
    )
    if fact_class == "transition":
        return (fact_class, family, old_value, new_value, change_value, unit, "")
    if fact_class == "change":
        return (fact_class, family, "", "", change_value or new_value, unit, "")
    if fact_class == "ratio_change":
        return (fact_class, family, "", "", change_value or new_value, unit, "")
    if fact_class == "range":
        return (fact_class, family, "", "", range_value, unit, "")
    return (fact_class, family, "", new_value, "", unit, "")


def _consolidate_fact_anchors(
    facts: list[ExtractedFact],
) -> tuple[list[ExtractedFact], list[dict[str, Any]]]:
    removed: list[dict[str, Any]] = []

    def score(fact: ExtractedFact) -> tuple[int, int, int, int, int]:
        decision_rank = {"keep": 3, "rescue": 2, "drop": 1}.get(str(fact.decision).lower(), 0)
        confidence_rank = {"high": 3, "medium": 2, "low": 1}.get(str(fact.raw.get("confidence", "")).lower(), 0)
        specificity_rank = 2 if _has_specific_entity_binding(fact) else 0
        metric_rank = _metric_quality(fact)
        unit_rank = _unit_quality(fact)
        return (decision_rank, confidence_rank, specificity_rank, metric_rank, unit_rank)

    grouped: dict[tuple[str, str, str, str, str, str, str], list[ExtractedFact]] = {}
    for fact in facts:
        key = _fact_anchor_key(fact)
        if not key[1]:
            continue
        grouped.setdefault(key, []).append(fact)

    to_remove: set[str] = set()
    for key, group in grouped.items():
        if len(group) < 2:
            continue

        specifics = [fact for fact in group if _has_specific_entity_binding(fact)]
        generics = [fact for fact in group if _is_generic_metric_name(fact)]
        if specifics and generics:
            keep_fact = max(specifics, key=score)
            for drop_fact in generics:
                if drop_fact.fact_id == keep_fact.fact_id:
                    continue
                to_remove.add(drop_fact.fact_id)
                removed.append(
                    {
                        "removed_fact_id": drop_fact.fact_id,
                        "kept_fact_id": keep_fact.fact_id,
                        "reason": "anchor_generic_replaced_by_specific",
                        "key": list(key),
                    }
                )
            continue

        best = max(group, key=score)
        for drop_fact in group:
            if drop_fact.fact_id == best.fact_id:
                continue
            if _fact_dedup_key(drop_fact) == _fact_dedup_key(best):
                continue
            to_remove.add(drop_fact.fact_id)
            removed.append(
                {
                    "removed_fact_id": drop_fact.fact_id,
                    "kept_fact_id": best.fact_id,
                    "reason": "anchor_consolidated_variant",
                    "key": list(key),
                }
            )

    consolidated = [fact for fact in facts if fact.fact_id not in to_remove]
    return consolidated, removed


def _dedup_extracted_facts(facts: list[ExtractedFact]) -> tuple[list[ExtractedFact], list[dict[str, Any]]]:
    removed: list[dict[str, Any]] = []

    def score(fact: ExtractedFact) -> tuple[int, int, int]:
        decision_rank = {"keep": 3, "rescue": 2, "drop": 1}.get(str(fact.decision).lower(), 0)
        confidence_rank = {"high": 3, "medium": 2, "low": 1}.get(str(fact.raw.get("confidence", "")).lower(), 0)
        metric_rank = _metric_quality(fact)
        unit_rank = _unit_quality(fact)
        evidence_len = len(str(fact.evidence or fact.raw.get("source_sentence") or ""))
        return (decision_rank, confidence_rank, metric_rank, unit_rank, -evidence_len)

    def reduce_by_key(
        current_facts: list[ExtractedFact],
        key_fn: Any,
        reason: str,
        allow_blank_metric: bool = True,
    ) -> list[ExtractedFact]:
        best_by_key: dict[Any, ExtractedFact] = {}
        for fact in current_facts:
            key = key_fn(fact)
            if not allow_blank_metric and isinstance(key, tuple) and key and not key[0]:
                key = ("__skip__", fact.fact_id)
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = fact
                continue
            if score(fact) > score(existing):
                removed.append(
                    {
                        "removed_fact_id": existing.fact_id,
                        "kept_fact_id": fact.fact_id,
                        "reason": reason,
                        "key": list(key) if isinstance(key, tuple) else key,
                    }
                )
                best_by_key[key] = fact
            else:
                removed.append(
                    {
                        "removed_fact_id": fact.fact_id,
                        "kept_fact_id": existing.fact_id,
                        "reason": reason,
                        "key": list(key) if isinstance(key, tuple) else key,
                    }
                )
        return list(best_by_key.values())

    def reduce_same_sentence_single_number(current_facts: list[ExtractedFact]) -> list[ExtractedFact]:
        best_by_key: dict[tuple[str, str], ExtractedFact] = {}
        passthrough: list[ExtractedFact] = []
        for fact in current_facts:
            raw = fact.raw or {}
            sentence = _normalize_dedup_text(raw.get("source_sentence"))
            if _numeric_count_in_text(sentence) != 1:
                passthrough.append(fact)
                continue
            key = (sentence, _normalize_numeric_for_dedup(raw.get("raw_value", fact.value)))
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = fact
                continue
            if score(fact) > score(existing):
                removed.append(
                    {
                        "removed_fact_id": existing.fact_id,
                        "kept_fact_id": fact.fact_id,
                        "reason": "duplicate_same_sentence_single_number",
                        "key": list(key),
                    }
                )
                best_by_key[key] = fact
            else:
                removed.append(
                    {
                        "removed_fact_id": fact.fact_id,
                        "kept_fact_id": existing.fact_id,
                        "reason": "duplicate_same_sentence_single_number",
                        "key": list(key),
                    }
                )
        return passthrough + list(best_by_key.values())

    def reduce_contained_sentence_variants(current_facts: list[ExtractedFact]) -> list[ExtractedFact]:
        grouped: dict[tuple[str, str, str, str, str], list[ExtractedFact]] = {}
        for fact in current_facts:
            grouped.setdefault(_fact_semantic_key(fact), []).append(fact)

        kept: list[ExtractedFact] = []
        for key, group in grouped.items():
            survivors = list(group)
            changed = True
            while changed and len(survivors) > 1:
                changed = False
                for i in range(len(survivors)):
                    if changed:
                        break
                    for j in range(i + 1, len(survivors)):
                        a = survivors[i]
                        b = survivors[j]
                        sa = _normalize_dedup_text((a.raw or {}).get("source_sentence"))
                        sb = _normalize_dedup_text((b.raw or {}).get("source_sentence"))
                        if not sa or not sb:
                            continue
                        if sa in sb or sb in sa:
                            if score(a) >= score(b):
                                keep_fact, drop_fact = a, b
                            else:
                                keep_fact, drop_fact = b, a
                            removed.append(
                                {
                                    "removed_fact_id": drop_fact.fact_id,
                                    "kept_fact_id": keep_fact.fact_id,
                                    "reason": "duplicate_contained_sentence_variant",
                                    "key": list(key),
                                }
                            )
                            survivors.remove(drop_fact)
                            changed = True
                            break
            kept.extend(survivors)
        return kept

    def reduce_entity_bound_variants(current_facts: list[ExtractedFact]) -> list[ExtractedFact]:
        grouped: dict[tuple[str, str, str, str], list[ExtractedFact]] = {}
        for fact in current_facts:
            raw = fact.raw or {}
            fact_class = _normalize_dedup_text(raw.get("fact_class"))
            old_value = _normalize_numeric_for_dedup(raw.get("old_value") or raw.get("prior_value"))
            new_value = _normalize_numeric_for_dedup(raw.get("new_value") or raw.get("raw_value", fact.value))
            unit = _normalize_unit_for_dedup(raw.get("raw_unit", fact.unit))
            grouped.setdefault((fact_class, old_value, new_value, unit), []).append(fact)

        kept: list[ExtractedFact] = []
        for key, group in grouped.items():
            if len(group) < 2:
                kept.extend(group)
                continue

            specific = [fact for fact in group if _has_specific_entity_binding(fact)]
            generic = [fact for fact in group if _is_generic_metric_name(fact) and not _has_specific_entity_binding(fact)]

            if specific and generic:
                survivors = [fact for fact in group if fact not in generic]
                for drop_fact in generic:
                    keep_fact = max(specific, key=score)
                    removed.append(
                        {
                            "removed_fact_id": drop_fact.fact_id,
                            "kept_fact_id": keep_fact.fact_id,
                            "reason": "duplicate_generic_entity_variant",
                            "key": list(key),
                        }
                    )
                kept.extend(survivors)
            else:
                kept.extend(group)
        return kept

    def reduce_orphan_year_targets(current_facts: list[ExtractedFact]) -> list[ExtractedFact]:
        grouped: dict[str, list[ExtractedFact]] = {}
        for fact in current_facts:
            sentence = _normalize_dedup_text((fact.raw or {}).get("source_sentence"))
            grouped.setdefault(sentence, []).append(fact)

        kept: list[ExtractedFact] = []
        for sentence, group in grouped.items():
            if len(group) < 2:
                kept.extend(group)
                continue

            year_facts = []
            non_year_facts = []
            for fact in group:
                raw = fact.raw or {}
                metric_core = _normalize_dedup_text(raw.get("metric_core"))
                raw_unit = _normalize_unit_for_dedup(raw.get("raw_unit", fact.unit))
                raw_value = _normalize_dedup_text(raw.get("raw_value", fact.value))
                if (
                    metric_core in {"target year", "year target"}
                    or raw_unit == "years"
                    or re.fullmatch(r"(?:19|20)\d{2}", raw_value)
                ):
                    year_facts.append(fact)
                else:
                    non_year_facts.append(fact)

            if year_facts and non_year_facts:
                for drop_fact in year_facts:
                    keep_fact = max(non_year_facts, key=score)
                    removed.append(
                        {
                            "removed_fact_id": drop_fact.fact_id,
                            "kept_fact_id": keep_fact.fact_id,
                            "reason": "duplicate_orphan_target_year",
                            "key": sentence,
                        }
                    )
                kept.extend(non_year_facts)
            else:
                kept.extend(group)
        return kept

    deduped = reduce_by_key(facts, _fact_dedup_key, "duplicate_overlap_exact")
    deduped = reduce_by_key(deduped, _fact_same_sentence_key, "duplicate_same_sentence_alt_label")
    deduped = reduce_same_sentence_single_number(deduped)
    deduped = reduce_by_key(deduped, _fact_semantic_key, "duplicate_semantic_metric", allow_blank_metric=False)
    deduped = reduce_contained_sentence_variants(deduped)
    deduped = reduce_entity_bound_variants(deduped)
    deduped = reduce_orphan_year_targets(deduped)
    deduped.sort(key=lambda fact: (fact.chunk_id, fact.fact_id))
    return deduped, removed


def _adapt_pass1b_keep_record(raw_fact: dict[str, Any]) -> dict[str, Any]:
    dimension_type = str(raw_fact.get("dimension_type") or "none")
    dimension_member = raw_fact.get("dimension_member")
    raw_name = _clean_text_value(raw_fact.get("raw_name"))
    raw_value = _clean_text_value(raw_fact.get("raw_value"))
    raw_unit = _clean_text_value(raw_fact.get("value_unit_raw"))
    metric_core = _clean_text_value(raw_fact.get("metric_core"))
    if raw_unit.lower() in {"percentage", "percent"}:
        raw_unit = "%"
    source_sentence = _clean_text_value(raw_fact.get("source_sentence"))
    parent_metric_hint = _clean_text_value(raw_fact.get("parent_metric_hint"))
    raw_name = _derive_metric_name_from_context(
        raw_name=raw_name,
        raw_value=raw_value,
        raw_unit=raw_unit,
        source_sentence=source_sentence,
        parent_hint=parent_metric_hint,
        metric_core=metric_core,
    )
    return {
        "candidate_id": raw_fact.get("candidate_id"),
        "raw_name": raw_name,
        "raw_label_type": str(raw_fact.get("raw_label_type") or "metric_label"),
        "raw_value": raw_value,
        "raw_unit": raw_unit,
        "raw_period": "",
        "source_sentence": source_sentence,
        "period_type": str(raw_fact.get("period_type") or "unknown"),
        "fact_type": str(raw_fact.get("fact_type") or "actual"),
        "scope": "sub_entity" if dimension_type not in {"", "none"} and dimension_member else "consolidated",
        "dimension_type": dimension_type if dimension_type else "none",
        "dimension_member": dimension_member,
        "graph_fact_type": str(raw_fact.get("graph_fact_type") or "financial_metric"),
        "parent_metric_hint": parent_metric_hint or None,
        "driver_phrase": None,
        "prior_value": raw_fact.get("prior_value"),
        "direction": raw_fact.get("direction"),
        "filter_action": raw_fact.get("filter_action"),
        "filter_reason": raw_fact.get("filter_reason"),
        "fact_class": raw_fact.get("fact_class"),
        "metric_core": metric_core,
        "old_value": raw_fact.get("old_value"),
        "new_value": raw_fact.get("new_value"),
        "change_value": raw_fact.get("change_value"),
        "change_unit": raw_fact.get("change_unit"),
        "range_min": raw_fact.get("range_min"),
        "range_max": raw_fact.get("range_max"),
        "range_unit": raw_fact.get("range_unit"),
    }


def _extract_numeric_spans(text: str) -> list[str]:
    if not text:
        return []
    spans = [match.group(0).strip(" .,;:") for match in _NUMERIC_SPAN_RE.finditer(text)]
    cleaned: list[str] = []
    for span in spans:
        span = _clean_text_value(span)
        if span and span not in cleaned:
            cleaned.append(span)
    return cleaned


def _metric_core_from_name(raw_name: str) -> str:
    normalized = _normalize_metric_for_dedup(raw_name)
    if normalized:
        return normalized
    fallback = _clean_text_value(raw_name).lower()
    return fallback


def _normalize_value_string(value: Any) -> str | None:
    text = _clean_text_value(value)
    return text or None


def _is_numeric_comparison_value(value: str | None) -> bool:
    if not value:
        return False
    return _looks_numericish(value)


def _extract_change_component(source_sentence: str, *, exclude: set[str] | None = None) -> str | None:
    exclude = exclude or set()
    for match in _CHANGE_COMPONENT_RE.finditer(source_sentence or ""):
        candidate = _clean_text_value(match.group(1))
        if candidate and candidate not in exclude:
            return candidate
    return None


def _pair_links_to_prior(source_sentence: str, prior_value: str | None) -> bool:
    prior_value = _clean_text_value(prior_value)
    if not source_sentence or not prior_value:
        return False
    escaped = re.escape(prior_value)
    patterns = [
        rf"\bfrom\b[^.:\n]{{0,120}}?{escaped}",
        rf"\bup from\b[^.:\n]{{0,120}}?{escaped}",
        rf"\bdown from\b[^.:\n]{{0,120}}?{escaped}",
        rf"\bversus\b[^.:\n]{{0,120}}?{escaped}",
        rf"\bvs\.?\b[^.:\n]{{0,120}}?{escaped}",
        rf"\bcompared (?:with|to)\b[^.:\n]{{0,120}}?{escaped}",
    ]
    return any(re.search(pattern, source_sentence, re.IGNORECASE) for pattern in patterns)


def _extract_bps_change(numeric_spans: list[str], prior_value: str | None) -> str | None:
    for span in numeric_spans:
        if re.search(r"\b(?:bps|basis points)\b", span, re.IGNORECASE):
            return span
    if prior_value and re.search(r"\b(?:bps|basis points)\b", prior_value, re.IGNORECASE):
        match = re.search(r"\d[\d,]*\.?\d*\s*(?:bps|basis points)", prior_value, re.IGNORECASE)
        if match:
            return _clean_text_value(match.group(0))
    return None


def _looks_like_change_measure(raw_name: str, raw_value: str | None, raw_unit: str) -> bool:
    if _CHANGE_LABEL_RE.search(raw_name or ""):
        return True
    if raw_value and (raw_value.startswith("+") or raw_value.startswith("-")):
        return True
    if raw_value and _DELTA_UNIT_RE.search(raw_value):
        return True
    if raw_unit and _DELTA_UNIT_RE.search(raw_unit):
        return True
    return False


def _extract_sentence_metric_hint(source_sentence: str) -> str:
    if not source_sentence:
        return ""
    match = _SENTENCE_METRIC_HINT_RE.search(source_sentence)
    return _clean_text_value(match.group(1)) if match else ""


def _infer_direction(source_sentence: str, fallback: str = "") -> str:
    fallback = _clean_text_value(fallback).lower()
    if fallback in {"increased", "decreased", "unchanged", "reached"}:
        return fallback
    if _DECREASE_DIRECTION_RE.search(source_sentence or ""):
        return "decreased"
    if _INCREASE_DIRECTION_RE.search(source_sentence or ""):
        return "increased"
    if _UNCHANGED_DIRECTION_RE.search(source_sentence or ""):
        return "unchanged"
    if _REACHED_DIRECTION_RE.search(source_sentence or ""):
        return "reached"
    return fallback or "reached"


def _extract_baseline_year(source_sentence: str, fallback: Any = None) -> str | None:
    match = _BASELINE_YEAR_RE.search(source_sentence or "")
    if not match:
        return None
    return next((group for group in match.groups() if group), None)


def _apply_entity_binding(raw_fact: dict[str, Any]) -> dict[str, Any]:
    bound = dict(raw_fact)
    raw_name = _clean_text_value(bound.get("raw_name"))
    parent_hint = _clean_text_value(bound.get("parent_metric_hint"))
    source_sentence = _clean_text_value(bound.get("source_sentence"))
    dimension_type = _clean_text_value(bound.get("dimension_type")) or "none"
    dimension_member = _clean_text_value(bound.get("dimension_member"))
    entity_label = dimension_member or (parent_hint if _ENTITY_HINT_RE.search(parent_hint) else "")
    sentence_metric_hint = _extract_sentence_metric_hint(source_sentence)

    if not parent_hint and raw_name and _ENTITY_HINT_RE.search(raw_name) and sentence_metric_hint:
        bound["parent_metric_hint"] = sentence_metric_hint
        parent_hint = sentence_metric_hint

    if raw_name and _ENTITY_HINT_RE.search(raw_name) and parent_hint:
        if parent_hint.lower() not in raw_name.lower():
            bound["raw_name"] = f"{parent_hint.title()} ({raw_name})"
            raw_name = bound["raw_name"]

    if raw_name and _GENERIC_ENTITY_METRIC_RE.fullmatch(raw_name) and entity_label:
        if entity_label.lower() not in raw_name.lower():
            bound["raw_name"] = f"{raw_name} ({entity_label})".strip()

    if parent_hint and parent_hint.lower() != raw_name.lower():
        if (not dimension_member) and _ENTITY_HINT_RE.search(parent_hint):
            bound["dimension_type"] = "segment"
            bound["dimension_member"] = parent_hint
            bound["scope"] = "sub_entity"
        elif dimension_type in {"", "none"} and _ENTITY_HINT_RE.search(parent_hint):
            bound["dimension_type"] = "segment"
            bound["dimension_member"] = parent_hint
            bound["scope"] = "sub_entity"

    return bound


def _infer_fact_interpretation(raw_fact: dict[str, Any]) -> dict[str, Any]:
    pretyped_fact_class = _clean_text_value(raw_fact.get("fact_class"))
    if pretyped_fact_class:
        fact_class = pretyped_fact_class
        metric_core = _clean_text_value(raw_fact.get("metric_core")) or _metric_core_from_name(
            _clean_text_value(raw_fact.get("parent_metric_hint")) or _clean_text_value(raw_fact.get("raw_name"))
        )
        typed = {
            "fact_class": fact_class,
            "metric_core": metric_core,
            "old_value": _normalize_value_string(raw_fact.get("old_value")),
            "new_value": _normalize_value_string(raw_fact.get("new_value")),
            "change_value": _normalize_value_string(raw_fact.get("change_value")),
            "change_unit": _normalize_value_string(raw_fact.get("change_unit")),
            "range_min": _normalize_value_string(raw_fact.get("range_min")),
            "range_max": _normalize_value_string(raw_fact.get("range_max")),
            "range_unit": _normalize_value_string(raw_fact.get("range_unit")),
            "numeric_spans": _extract_numeric_spans(_clean_text_value(raw_fact.get("source_sentence"))),
            "direction": _infer_direction(
                _clean_text_value(raw_fact.get("source_sentence")),
                _clean_text_value(raw_fact.get("direction")),
            ),
        }
        if not typed["new_value"]:
            typed["new_value"] = _normalize_value_string(raw_fact.get("raw_value"))
        if fact_class == "transition" and not typed["old_value"]:
            typed["old_value"] = _normalize_value_string(raw_fact.get("prior_value"))
        if fact_class == "change" and not typed["change_value"]:
            typed["change_value"] = _normalize_value_string(raw_fact.get("raw_value"))
        if fact_class == "ratio_change" and not typed["change_value"]:
            typed["change_value"] = _normalize_value_string(raw_fact.get("raw_value"))
        if fact_class == "range":
            if not typed["range_min"]:
                typed["range_min"] = _normalize_value_string(raw_fact.get("prior_value"))
            if not typed["range_max"]:
                typed["range_max"] = _normalize_value_string(raw_fact.get("raw_value"))
            if not typed["range_unit"]:
                typed["range_unit"] = _normalize_value_string(raw_fact.get("raw_unit"))
        return typed

    source_sentence = _clean_text_value(raw_fact.get("source_sentence"))
    raw_name = _clean_text_value(raw_fact.get("raw_name"))
    raw_value = _normalize_value_string(raw_fact.get("raw_value"))
    prior_value = _normalize_value_string(raw_fact.get("prior_value"))
    interpreted_prior_value = prior_value if _is_numeric_comparison_value(prior_value) else None
    direction = _clean_text_value(raw_fact.get("direction")) or None
    raw_unit = _clean_text_value(raw_fact.get("raw_unit"))
    metric_core = _metric_core_from_name(raw_name)
    numeric_spans = _extract_numeric_spans(source_sentence)

    interpretation: dict[str, Any] = {
        "fact_class": "scalar_kpi",
        "metric_core": metric_core,
        "old_value": None,
        "new_value": None,
        "change_value": None,
        "change_unit": None,
        "range_min": None,
        "range_max": None,
        "range_unit": None,
        "numeric_spans": numeric_spans,
        "direction": _infer_direction(source_sentence, direction or ""),
    }

    lower_sentence = source_sentence.lower()
    raw_value_has_percent = bool(raw_value and "%" in raw_value)
    prior_value_has_bps = bool(interpreted_prior_value and re.search(r"\b(?:bps|basis points)\b", interpreted_prior_value, re.IGNORECASE))
    explicit_pair = _pair_links_to_prior(source_sentence, interpreted_prior_value)
    change_like_value = _looks_like_change_measure(raw_name, raw_value, raw_unit)

    if interpreted_prior_value and raw_value:
        if prior_value_has_bps and raw_value_has_percent:
            bps_change = _extract_bps_change(numeric_spans, interpreted_prior_value) or interpreted_prior_value
            raw_fact["raw_unit"] = "%"
            interpretation.update(
                {
                    "fact_class": "change",
                    "new_value": raw_value,
                    "change_value": bps_change,
                    "change_unit": "bps",
                }
            )
            raw_fact["fact_type"] = "actual"
            return interpretation

        if _RANGE_CONTEXT_RE.search(lower_sentence) and not _CHANGE_WORD_RE.search(lower_sentence):
            if raw_name.lower() == "pack size":
                raw_fact["raw_name"] = "pack size range"
            interpretation.update(
                {
                    "fact_class": "range",
                    "range_min": prior_value,
                    "range_max": raw_value,
                    "range_unit": raw_unit or None,
                }
            )
            raw_fact["fact_type"] = "actual"
            return interpretation

        if not explicit_pair:
            interpretation["new_value"] = raw_value
            return interpretation

        interpretation.update(
            {
                "fact_class": "transition",
                "old_value": interpreted_prior_value,
                "new_value": raw_value,
            }
        )
        raw_fact["fact_type"] = "actual"
        change_component = _extract_change_component(
            source_sentence,
            exclude={interpreted_prior_value, raw_value},
        )
        if change_component:
            interpretation["change_value"] = change_component
            if re.search(r"\b(?:bps|basis points)\b", change_component, re.IGNORECASE):
                interpretation["change_unit"] = "bps"
            elif "%" in change_component:
                interpretation["change_unit"] = "%"
        return interpretation

    if raw_value and _CHANGE_WORD_RE.search(lower_sentence) and change_like_value:
        interpretation.update(
            {
                "fact_class": "change",
                "change_value": raw_value,
                "change_unit": raw_unit or None,
            }
        )
        raw_fact["fact_type"] = "delta"
        return interpretation

    if raw_value and _RANGE_CONTEXT_RE.search(lower_sentence) and len(numeric_spans) >= 2:
        if raw_name.lower() == "pack size":
            raw_fact["raw_name"] = "pack size range"
        interpretation.update(
            {
                "fact_class": "range",
                "range_min": numeric_spans[0],
                "range_max": numeric_spans[1],
                "range_unit": raw_unit or None,
            }
        )
        raw_fact["fact_type"] = "actual"
        return interpretation

    interpretation["new_value"] = raw_value
    return interpretation


def _apply_fact_interpreter(raw_fact: dict[str, Any]) -> dict[str, Any]:
    interpreted = _apply_entity_binding(raw_fact)
    interpreted.update(_infer_fact_interpretation(interpreted))
    interpreted["baseline_year"] = _extract_baseline_year(
        _clean_text_value(interpreted.get("source_sentence")),
        interpreted.get("baseline_year"),
    )
    return interpreted


def _apply_lean_fact_postprocessing(raw_fact: dict[str, Any]) -> dict[str, Any]:
    fact = dict(raw_fact)
    source_sentence = _clean_text_value(fact.get("source_sentence"))
    fact["direction"] = _infer_direction(source_sentence, fact.get("direction"))
    fact["baseline_year"] = _extract_baseline_year(source_sentence, fact.get("baseline_year"))
    return fact


def _call_openai_two_stage(chunk: Chunk, client: Any) -> Any:
    print(f"--- CHUNK: {chunk.chunk_id} (two-stage) ---", flush=True)
    print(f"Content preview: {chunk.content[:500]}", flush=True)
    print(f"Token estimate: {chunk.token_estimate}", flush=True)

    pass1a_prompt = _render_prompt_template(PASS1A_RECALL_PROMPT_TEMPLATE, chunk)
    print(f"Pass1a prompt preview: {pass1a_prompt[:300]}", flush=True)
    pass1a_start = time.monotonic()
    pass1a_response, pass1a_json, pass1a_raw = _call_structured_completion(
        client,
        system_prompt=pass1a_prompt,
        user_content="Extract candidate numeric facts from this section as JSON.",
        response_format=PASS1A_RESPONSE_FORMAT,
    )
    pass1a_elapsed = time.monotonic() - pass1a_start
    print(f"Pass1a raw response for {chunk.chunk_id}:", flush=True)
    print(pass1a_raw[:500], flush=True)
    print("---END PASS1A RESPONSE---", flush=True)
    raw_candidates = pass1a_json.get("candidates", []) if isinstance(pass1a_json, dict) else []
    typed_candidates = [c for c in raw_candidates if isinstance(c, dict)]
    sanitized_candidates, locally_dropped_candidates = _sanitize_candidates(typed_candidates)
    candidates = _dedupe_candidates(sanitized_candidates)
    print(
        f"Pass1a candidates: raw={len(raw_candidates)} sanitized={len(sanitized_candidates)} "
        f"locally_dropped={len(locally_dropped_candidates)} deduped={len(candidates)}",
        flush=True,
    )

    kept_records: list[dict[str, Any]] = []
    dropped_records: list[dict[str, Any]] = []
    pass1b_telemetry: list[dict[str, Any]] = []

    for batch_index, candidate_batch in enumerate(_batched(candidates, 25), start=1):
        candidates_json = json.dumps({"candidates": candidate_batch}, ensure_ascii=False, indent=2)
        pass1b_prompt = _render_prompt_template(
            PASS1B_TYPING_PROMPT_TEMPLATE,
            chunk,
            candidates_json=candidates_json,
        )
        print(
            f"Pass1b batch {batch_index}/{max(1, len(_batched(candidates, 25)))} "
            f"prompt preview: {pass1b_prompt[:220]}",
            flush=True,
        )
        batch_start = time.monotonic()
        pass1b_response, pass1b_json, pass1b_raw = _call_structured_completion(
            client,
            system_prompt=pass1b_prompt,
            user_content="Filter and type these candidate facts as JSON.",
            response_format=PASS1B_RESPONSE_FORMAT,
        )
        batch_elapsed = time.monotonic() - batch_start
        batch_facts = pass1b_json.get("facts", []) if isinstance(pass1b_json, dict) else []
        print(f"Pass1b raw response for {chunk.chunk_id} batch {batch_index}:", flush=True)
        print(pass1b_raw[:500], flush=True)
        print("---END PASS1B RESPONSE---", flush=True)
        for fact in batch_facts:
            if not isinstance(fact, dict):
                continue
            if fact.get("filter_action") == "keep":
                kept_records.append(_apply_fact_interpreter(_adapt_pass1b_keep_record(fact)))
            else:
                dropped_records.append(fact)
        batch_usage = None
        if getattr(pass1b_response, "usage", None) is not None:
            batch_usage = (
                pass1b_response.usage.model_dump()
                if hasattr(pass1b_response.usage, "model_dump")
                else dict(pass1b_response.usage)
            )
        pass1b_telemetry.append(
            {
                "batch_index": batch_index,
                "candidate_count": len(candidate_batch),
                "timing_seconds": batch_elapsed,
                "usage": batch_usage,
            }
        )

    validation_context = _validation_context_for_chunk(chunk)
    validation_start = time.monotonic()
    enriched_facts = enrich_facts(kept_records, validation_context)
    validation_elapsed = time.monotonic() - validation_start
    for index, fact in enumerate(enriched_facts, start=1):
        fact.setdefault("fact_id", f"{chunk.chunk_id}_fact_{index}")
    definition_start = time.monotonic()
    enriched_facts, definition_telemetry = _attach_metric_definitions(client, chunk, enriched_facts)
    definition_elapsed = time.monotonic() - definition_start

    pass1a_usage = None
    if getattr(pass1a_response, "usage", None) is not None:
        pass1a_usage = (
            pass1a_response.usage.model_dump()
            if hasattr(pass1a_response.usage, "model_dump")
            else dict(pass1a_response.usage)
        )

    telemetry = {
        "request": {
            "model": MODEL,
            "timeout": API_TIMEOUT_SECONDS,
            "pipeline": "pass1a_pass1b",
        },
        "stages": {
            "pass1a": {
                "response_format": deepcopy(PASS1A_RESPONSE_FORMAT),
                "usage": pass1a_usage,
                "timing_seconds": pass1a_elapsed,
                "raw_candidates": len(raw_candidates),
                "sanitized_candidates": len(sanitized_candidates),
                "locally_dropped_candidates": len(locally_dropped_candidates),
                "deduped_candidates": len(candidates),
                "local_drop_reasons": locally_dropped_candidates,
            },
            "pass1b": {
                "response_format": deepcopy(PASS1B_RESPONSE_FORMAT),
                "batches": pass1b_telemetry,
                "kept_records": len(kept_records),
                "dropped_records": len(dropped_records),
            },
            "validator": {
                "timing_seconds": validation_elapsed,
            },
            "define": {
                "response_format": deepcopy(DEFINE_RESPONSE_FORMAT),
                "timing_seconds": definition_elapsed,
                "batches": definition_telemetry,
            },
        },
        "retries": {
            "custom_retry_count": 0,
            "sdk_max_retries_configured": 1,
            "sdk_retry_count": None,
        },
    }
    return {"facts": enriched_facts, "_telemetry": telemetry, "_drops": dropped_records}


def _call_openai(chunk: Chunk) -> Any:
    content = (
        TABLE_EXTRACTION_PREFIX + chunk.content
        if chunk.chunk_type == "table"
        else chunk.content
    )
    system_prompt = _render_system_prompt(chunk)
    print(f"--- CHUNK: {chunk.chunk_id} ---", flush=True)
    print(f"System prompt preview: {system_prompt[:300]}", flush=True)
    print(f"Content preview: {content[:500]}", flush=True)
    print(f"Token estimate: {chunk.token_estimate}", flush=True)
    if chunk.chunk_id == "amazon_com_inc_consolidated_statements_of_cash_flows_2":
        print("--- CASH FLOW TABLE CONTENT ---", flush=True)
        print(content[:1500], flush=True)

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
    print(f"Calling API for {chunk.chunk_id}...", flush=True)
    if FAST_PARAGRAPH_MODE and TWO_STAGE_PASS1:
        return _call_openai_two_stage(chunk, client)
    request_messages = None
    response_format_snapshot = None
    start_time = time.monotonic()
    if FAST_PARAGRAPH_MODE:
        request_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Extract facts from this paragraph as JSON."},
        ]
        response_format_snapshot = deepcopy(PASS1_LEAN_RESPONSE_FORMAT)
        response = client.chat.completions.create(
            model=MODEL,
            response_format=PASS1_LEAN_RESPONSE_FORMAT,
            messages=request_messages,
            timeout=API_TIMEOUT_SECONDS,
        )
    else:
        request_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        response_format_snapshot = {
            "type": "json_schema",
            "json_schema": {
                "name": "facts_extraction",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "facts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "raw_name": {"type": "string"},
                                    "metric_core": {"type": "string"},
                                    "fact_class": {
                                        "type": "string",
                                        "enum": [
                                            "scalar_kpi",
                                            "change",
                                            "transition",
                                            "range",
                                            "ratio_change",
                                        ],
                                    },
                                    "direction": {
                                        "type": "string",
                                        "enum": [
                                            "increased",
                                            "decreased",
                                            "unchanged",
                                            "reached",
                                        ],
                                    },
                                    "raw_label_type": {"type": "string"},
                                    "raw_value": {
                                        "type": "string",
                                        "description": "Numeric value exactly as written. Must contain the reported number; do not use an empty string.",
                                    },
                                    "raw_unit": {"type": "string"},
                                    "raw_period": {"type": "string"},
                                    "baseline_year": {"type": ["string", "null"]},
                                    "source_sentence": {"type": "string"},
                                    "period_type": {"type": "string"},
                                    "fact_type": {"type": "string"},
                                    "scope": {"type": "string"},
                                    "dimension_type": {"type": "string"},
                                    "dimension_member": {"type": ["string", "null"]},
                                    "graph_fact_type": {"type": "string"},
                                    "parent_metric_hint": {"type": ["string", "null"]},
                                    "driver_phrase": {"type": ["string", "null"]},
                                },
                                "required": LEAN_FIELDS,
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["facts"],
                    "additionalProperties": False,
                },
            },
        }
        response = client.chat.completions.create(
            model=MODEL,
            response_format=response_format_snapshot,
            messages=request_messages,
            timeout=API_TIMEOUT_SECONDS,
        )
    elapsed = time.monotonic() - start_time
    print(f"Done {chunk.chunk_id} - got response in {elapsed:.1f}s", flush=True)

    content = response.choices[0].message.content or "{}"
    print(f"Raw API response for {chunk.chunk_id}:", flush=True)
    print(content[:500], flush=True)
    print("---END RESPONSE---", flush=True)
    response_json = json.loads(content)
    facts = response_json.get("facts", []) if isinstance(response_json, dict) else []
    facts = [_apply_lean_fact_postprocessing(fact) for fact in facts if isinstance(fact, dict)]
    validation_context = _validation_context_for_chunk(chunk)
    validation_start = time.monotonic()
    enriched_facts = enrich_facts(facts, validation_context)
    validation_elapsed = time.monotonic() - validation_start
    for index, fact in enumerate(enriched_facts, start=1):
        fact.setdefault("fact_id", f"{chunk.chunk_id}_fact_{index}")
    definition_start = time.monotonic()
    enriched_facts, definition_telemetry = _attach_metric_definitions(client, chunk, enriched_facts)
    definition_elapsed = time.monotonic() - definition_start
    usage = None
    if getattr(response, "usage", None) is not None:
        usage = response.usage.model_dump() if hasattr(response.usage, "model_dump") else dict(response.usage)
    telemetry = {
        "request": {
            "model": MODEL,
            "timeout": API_TIMEOUT_SECONDS,
            "response_format": response_format_snapshot,
        },
        "response": response.model_dump() if hasattr(response, "model_dump") else None,
        "usage": usage,
        "timing": {
            "api_seconds": elapsed,
            "validator_seconds": validation_elapsed,
            "define_seconds": definition_elapsed,
        },
        "define": {
            "response_format": deepcopy(DEFINE_RESPONSE_FORMAT),
            "batches": definition_telemetry,
        },
        "retries": {
            "custom_retry_count": 0,
            "sdk_max_retries_configured": 1,
            "sdk_retry_count": None,
        },
    }
    return {"facts": enriched_facts, "_telemetry": telemetry}


def _call_with_retry(chunk: Chunk) -> tuple[Chunk, Any | None, str | None]:
    retry_count = 0
    try:
        result = _call_openai(chunk)
        if isinstance(result, dict):
            result.setdefault("_telemetry", {}).setdefault("retries", {})["custom_retry_count"] = retry_count
        return chunk, result, None
    except Exception as first_error:
        print(
            f"Exception for {chunk.chunk_id} before retry: {first_error!r}",
            flush=True,
        )
        traceback.print_exception(
            type(first_error),
            first_error,
            first_error.__traceback__,
            file=sys.stdout,
        )
        sys.stdout.flush()

        retry_wait_seconds = RETRY_WAIT_SECONDS
        try:
            from openai import RateLimitError
        except ImportError:
            RateLimitError = None

        if RateLimitError is not None and isinstance(first_error, RateLimitError):
            retry_wait_seconds = 30
            print("Rate limit hit — waiting 30s before retry", flush=True)

        time.sleep(retry_wait_seconds)
        retry_count = 1
        try:
            result = _call_openai(chunk)
            if isinstance(result, dict):
                result.setdefault("_telemetry", {}).setdefault("retries", {})["custom_retry_count"] = retry_count
            return chunk, result, None
        except Exception as second_error:
            print(
                f"Retry exception for {chunk.chunk_id}: {second_error!r}",
                flush=True,
            )
            traceback.print_exception(
                type(second_error),
                second_error,
                second_error.__traceback__,
                file=sys.stdout,
            )
            sys.stdout.flush()
            if chunk.chunk_type == "table":
                return chunk, _extract_markdown_table_facts(chunk), None
            return chunk, None, f"{first_error}; retry failed: {second_error}"


def _extract_fact_items(response_json: Any) -> list[dict[str, Any]]:
    if not isinstance(response_json, dict):
        return []

    facts = response_json.get("facts", [])
    if not isinstance(facts, list):
        return []

    return [
        _apply_local_fact_defaults(fact)
        for fact in facts
        if isinstance(fact, dict)
    ]


def _to_extracted_fact(chunk: Chunk, raw_fact: dict[str, Any], index: int) -> ExtractedFact:
    dimension_member = str(raw_fact.get("dimension_member") or "")
    return ExtractedFact(
        fact_id=str(raw_fact.get("fact_id") or f"{chunk.chunk_id}_fact_{index}"),
        chunk_id=chunk.chunk_id,
        section_title=chunk.section_title,
        parent_section=chunk.parent_section,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        temporal_context=chunk.temporal_context,
        decision=str(raw_fact.get("decision", "keep")).lower(),
        metric=str(raw_fact.get("raw_name") or raw_fact.get("metric") or raw_fact.get("metric_name") or ""),
        value=raw_fact.get("raw_value", raw_fact.get("value")),
        unit=str(raw_fact.get("raw_unit") or raw_fact.get("unit", "")),
        period=str(raw_fact.get("raw_period") or raw_fact.get("period", "")),
        entity=str(raw_fact.get("entity", "")),
        segment=str(raw_fact.get("segment_name") or raw_fact.get("segment") or dimension_member),
        evidence=str(raw_fact.get("source_sentence") or raw_fact.get("evidence", "")),
        metric_definition=raw_fact.get("metric_definition"),
        baseline_year=raw_fact.get("baseline_year"),
        confidence=raw_fact.get("confidence"),
        raw=raw_fact,
    )


def run_pass1(
    chunks: list[dict[str, Any] | Chunk],
    output_path: str | Path = "pass1_output.json",
    print_facts: bool = False,
) -> list[ExtractedFact]:
    run_start = time.monotonic()
    chunk_models = [
        chunk if isinstance(chunk, Chunk) else Chunk.from_dict(chunk)
        for chunk in chunks
    ]
    skipped_chunks = []
    chunks_to_process = []
    for chunk in chunk_models:
        chunk_id = (chunk.chunk_id or "").lower()
        if (
            chunk.chunk_type == "table"
            and any(pattern in chunk_id for pattern in SKIP_CHUNK_ID_PATTERNS)
        ):
            print(
                f"Skipping non-financial chunk: {chunk.chunk_id}",
                flush=True,
            )
            skipped_chunks.append(chunk)
            continue
        chunks_to_process.extend(_split_large_table_chunk(chunk))

    facts = []
    telemetry_records = []
    historical_reprint_chunks = [
        chunk for chunk in chunks_to_process
        if chunk.temporal_context.is_historical_reprint
    ]
    failed_chunks = []

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CALLS) as executor:
        futures = []
        for chunk in chunks_to_process:
            futures.append(executor.submit(_call_with_retry, chunk))
            time.sleep(2)

        for future in as_completed(futures):
            chunk, response_json, error = future.result()
            if error:
                failed_chunks.append({"chunk_id": chunk.chunk_id, "error": error})
                continue

            if isinstance(response_json, dict) and response_json.get("_telemetry") is not None:
                telemetry = dict(response_json["_telemetry"])
                telemetry["chunk_id"] = chunk.chunk_id
                if response_json.get("_drops") is not None:
                    telemetry["drops"] = response_json.get("_drops")
                telemetry_records.append(telemetry)

            for index, raw_fact in enumerate(_extract_fact_items(response_json or {}), start=1):
                facts.append(_to_extracted_fact(chunk, raw_fact, index))

    pre_consolidation_count = len(facts)
    facts, anchor_consolidated = _consolidate_fact_anchors(facts)
    pre_dedup_count = len(facts)
    facts, dedup_removed = _dedup_extracted_facts(facts)

    write_start = time.monotonic()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "schema_version": PASS1_SCHEMA_VERSION,
                "facts": [fact.to_dict() for fact in facts],
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    write_elapsed = time.monotonic() - write_start

    telemetry_path = Path(output_path).with_name(Path(output_path).stem + "_telemetry.json")
    telemetry_payload = {
        "run": {
            "model": MODEL,
            "fast_paragraph_mode": FAST_PARAGRAPH_MODE,
            "input_chunks": len(chunks_to_process),
            "facts_before_anchor_consolidation": pre_consolidation_count,
            "facts_after_anchor_consolidation": pre_dedup_count,
            "anchor_consolidated_count": len(anchor_consolidated),
            "facts_before_dedup": pre_dedup_count,
            "facts_after_dedup": len(facts),
            "dedup_removed_count": len(dedup_removed),
            "total_wall_seconds": time.monotonic() - run_start,
            "file_write_seconds": write_elapsed,
        },
        "chunks": telemetry_records,
        "anchor_consolidated": anchor_consolidated,
        "dedup_removed": dedup_removed,
        "failed_chunks": failed_chunks,
    }
    with open(telemetry_path, "w", encoding="utf-8") as f:
        json.dump(telemetry_payload, f, indent=2, ensure_ascii=False)

    decision_counts = {"keep": 0, "rescue": 0, "drop": 0}
    for fact in facts:
        if fact.decision in decision_counts:
            decision_counts[fact.decision] += 1

    print(f"Chunks processed: {len(chunks_to_process)}", flush=True)
    print(f"Chunks skipped: {len(skipped_chunks)}", flush=True)
    print(
        "Historical reprint chunks processed: "
        f"{len(historical_reprint_chunks)}",
        flush=True,
    )
    print(f"Total facts extracted: {len(facts)}", flush=True)
    print(f"Anchor consolidations removed: {len(anchor_consolidated)}", flush=True)
    print(f"Duplicates removed: {len(dedup_removed)}", flush=True)
    print(
        "Facts by decision: "
        f"keep={decision_counts['keep']}, "
        f"rescue={decision_counts['rescue']}, "
        f"drop={decision_counts['drop']}",
        flush=True,
    )
    print(f"Chunks failed: {len(failed_chunks)}", flush=True)
    for failed_chunk in failed_chunks:
        print(f"- {failed_chunk['chunk_id']}: {failed_chunk['error']}", flush=True)

    if print_facts:
        for fact in facts:
            print(
                "raw_name="
                f"{fact.raw.get('raw_name', fact.metric)} | "
                "raw_value="
                f"{fact.raw.get('raw_value', fact.value)} | "
                f"decision={fact.decision} | "
                f"failed_checks={fact.raw.get('failed_checks', [])}",
                flush=True,
            )

    return facts


def print_test_fact_preview(output_path: str | Path, limit: int = 5) -> None:
    with open(output_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    facts = payload.get("facts", []) if isinstance(payload, dict) else payload

    for index, fact in enumerate(facts[:limit], start=1):
        raw = fact.get("raw", {})
        failed_checks = raw.get("failed_checks", [])
        checks = failed_checks if failed_checks else "all passed"
        source = str(raw.get("source_sentence") or fact.get("evidence") or "")[:100]
        unit = raw.get("raw_unit") or fact.get("unit") or ""
        segment_name = raw.get("segment_name") or fact.get("segment") or ""

        print("---", flush=True)
        print(f"Fact #{index}", flush=True)
        print(f"  Metric:    {raw.get('raw_name') or fact.get('metric') or ''}", flush=True)
        print(
            f"  Value:     {raw.get('raw_value', fact.get('value', ''))} ({unit})",
            flush=True,
        )
        print(
            "  Period:    "
            f"{raw.get('resolved_period_start', '')} to "
            f"{raw.get('resolved_period_end', '')}",
            flush=True,
        )
        print(f"  Type:      {raw.get('fact_type', '')}", flush=True)
        print(f"  Scope:     {raw.get('scope', '')} / {segment_name}", flush=True)
        print(f"  Decision:  {fact.get('decision', '')}", flush=True)
        print(f"  Checks:    {checks}", flush=True)
        print(f"  Source:    {source}", flush=True)
        print("---", flush=True)


def _shorten(value: Any, width: int) -> str:
    text = str(value or "")
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def _summary_period(fact: dict[str, Any]) -> str:
    raw = fact.get("raw", {})
    period = str(raw.get("raw_period") or fact.get("period") or "")
    start = str(raw.get("resolved_period_start") or "")
    end = str(raw.get("resolved_period_end") or "")

    for value in (period, start, end):
        if len(value) >= 4 and value[:4].isdigit():
            return f"FY{value[:4]}"

    temporal_context = fact.get("temporal_context", {})
    return str(temporal_context.get("primary_period") or "")


def print_fact_summary(output_path: str | Path) -> None:
    with open(output_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    facts = payload.get("facts", []) if isinstance(payload, dict) else payload

    counts = {"keep": 0, "rescue": 0, "drop": 0}
    for fact in facts:
        decision = str(fact.get("decision", "")).lower()
        if decision in counts:
            counts[decision] += 1

    index_width = max(1, len(str(len(facts))))
    metric_width = 26
    value_width = 12
    period_width = 8

    print("FACT SUMMARY", flush=True)
    print("-" * 78, flush=True)
    print(
        f"{'#':>{index_width}}   "
        f"{'Metric':<{metric_width}}  "
        f"{'Value':<{value_width}}  "
        f"{'Period':<{period_width}}  "
        "Decision",
        flush=True,
    )

    for index, fact in enumerate(facts, start=1):
        raw = fact.get("raw", {})
        metric = raw.get("raw_name") or fact.get("metric") or ""
        value = raw.get("raw_value", fact.get("value", ""))
        period = _summary_period(fact)
        decision = fact.get("decision", "")

        print(
            f"{index:>{index_width}}   "
            f"{_shorten(metric, metric_width):<{metric_width}}  "
            f"{_shorten(value, value_width):<{value_width}}  "
            f"{_shorten(period, period_width):<{period_width}}  "
            f"{decision}",
            flush=True,
        )

    print(flush=True)
    print(f"Total: {len(facts)} facts", flush=True)
    print(
        f"Keep: {counts['keep']} | "
        f"Rescue: {counts['rescue']} | "
        f"Drop: {counts['drop']}",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Pass 1 fact extraction")
    parser.add_argument(
        "--input",
        default=str(Path(__file__).with_name("chunks_output.json")),
        help="Input chunks JSON path",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output path for Pass 1 JSON",
    )
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--sample", action="store_true")
    parser.add_argument(
        "--chunk",
        metavar="CHUNK_ID",
        help="Process a single chunk by chunk_id and print the full fact output",
    )
    parser.add_argument(
        "--summary",
        metavar="PATH",
        help="Print a compact fact summary table from a Pass 1 JSON output file",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use fast paragraph-test mode with a lighter prompt and json_object output",
    )
    args = parser.parse_args()

    FAST_PARAGRAPH_MODE = args.fast

    if args.summary:
        print_fact_summary(args.summary)
        raise SystemExit(0)

    input_path = Path(args.input)
    METADATA_CONTEXT = _load_metadata_for_input(input_path)

    with open(input_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    if args.chunk:
        output_path = args.output or "pass1_single_output.json"
        selected_chunks = [
            chunk for chunk in chunks
            if chunk.get("chunk_id") == args.chunk
        ]
        if not selected_chunks:
            raise SystemExit(f"Chunk not found: {args.chunk}")

        facts = run_pass1(
            selected_chunks[:1],
            output_path=output_path,
        )
        print(
            json.dumps(
                {
                    "schema_version": PASS1_SCHEMA_VERSION,
                    "facts": [fact.to_dict() for fact in facts],
                },
                indent=2,
                ensure_ascii=False,
            ),
            flush=True,
        )
    elif args.test:
        output_path = args.output or "pass1_test_output.json"
        text_chunks = [
            chunk for chunk in chunks
            if chunk.get("chunk_type") == "text"
            and chunk.get("token_estimate", 0) > 200
        ]
        table_chunks = [
            chunk for chunk in chunks
            if chunk.get("chunk_type") == "table"
            and chunk.get("token_estimate", 0) > 200
        ]
        table_chunks = [
            chunk for chunk in table_chunks
            if not _is_excluded_table_chunk(chunk)
        ]

        test_chunks = text_chunks[:1] + table_chunks[:2]
        chunks = test_chunks if len(test_chunks) >= 3 else chunks[:3]

        print("Selected test chunks:", flush=True)
        for chunk in chunks:
            print(
                f"- {chunk.get('chunk_id', '')} "
                f"({chunk.get('chunk_type', '')}, "
                f"{chunk.get('token_estimate', 0)} tokens)",
                flush=True,
            )
        run_pass1(
            chunks,
            output_path=output_path,
        )
        print_test_fact_preview(output_path)
    elif args.sample:
        output_path = args.output or "pass1_sample_output.json"
        chunks = chunks[:20]
        run_pass1(
            chunks,
            output_path=output_path,
        )
    else:
        run_pass1(chunks, output_path=args.output or "pass1_output.json")
