import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


PASS3_PROMPT = """You are a financial fact rescue engine. You receive a fact 
that could not be fully normalized in Pass 2, plus additional 
context chunks from the same filing. Your job is to resolve 
the ambiguity and either promote the fact to "keep" or 
confirm it should be "drop".

DOCUMENT CONTEXT:
- Company: {company}
- Document fiscal period: {document_period}
- Filing type: {filing_type}
- Default currency: {default_currency}

FACT TO RESCUE:
{fact_json}

WHY IT NEEDS RESCUE:
{rescue_reason}

ADDITIONAL CONTEXT CHUNKS:
{context_chunks}

VALID CANONICAL IDS:
{valid_canonical_ids}

YOUR TASK:

STEP 1 — READ THE RESCUE REASON
  The rescue_reason explains exactly what is ambiguous.
  Common reasons:
    - Period unclear (run rate, annualised, unspecified)
    - Scale unclear (unit not stated in fact)
    - Metric ambiguous (could be two different canonicals)
    - Value is a movement not a level (increase of X)
    - Scope unclear (segment vs consolidated)

STEP 2 — SEARCH THE CONTEXT CHUNKS
  Read every context chunk provided.
  Look for any sentence or table that resolves the ambiguity.
  Quote the exact sentence that resolves it in resolution_evidence.
  If no context chunk resolves it → rescue_outcome = "drop"

STEP 3 — RESOLVE AND OUTPUT

  If resolved:
    rescue_outcome = "promote"
    Set corrected values for any fields that were wrong:
      resolved_period_start, resolved_period_end
      period_type
      scope, segment_name
      value_normalized (if scale was ambiguous)
      canonical_id (if metric was ambiguous)
      normalization_decision = "normalized"
    resolution_evidence = exact quote from context that 
      resolved it (under 20 words)
    resolution_note = brief explanation of what changed

  If not resolved:
    rescue_outcome = "drop"
    resolution_evidence = null
    resolution_note = explain why context was insufficient

OUTPUT FORMAT:
Return ONLY a valid JSON object. No markdown, no explanation.

{{
  "fact_id": "",
  "rescue_outcome": "promote" | "drop",
  "resolution_evidence": "",
  "resolution_note": "",
  "resolved_period_start": "",
  "resolved_period_end": "",
  "period_type": "",
  "scope": "",
  "segment_name": "",
  "value_normalized": null,
  "canonical_id": "",
  "normalization_decision": "normalized" | "drop"
}}"""


MODEL = "gpt-5-mini"
API_TIMEOUT_SECONDS = 90
RETRY_WAIT_SECONDS = 10
DEFAULT_INPUT = "pass2_output.json"
DEFAULT_OUTPUT = "pass3_output.json"
SAMPLE_PARTIAL_FACTS = 50


def _load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str | Path, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _chunks_path_for_input(pass2_path: str | Path) -> Path:
    pass2_path = Path(pass2_path)
    name = pass2_path.name
    if name.endswith("_pass2.json"):
        chunks_name = name[: -len("_pass2.json")] + "_chunks.json"
    else:
        chunks_name = pass2_path.stem + "_chunks.json"

    chunks_path = pass2_path.with_name(chunks_name)
    if not chunks_path.exists():
        raise FileNotFoundError(
            f"No chunks file found — expected {chunks_path.name}"
        )
    return chunks_path


def _metadata_path_for_input(pass2_path: str | Path) -> Path:
    pass2_path = Path(pass2_path)
    name = pass2_path.name
    if name.endswith("_pass2.json"):
        metadata_name = name[: -len("_pass2.json")] + "_metadata.json"
    else:
        metadata_name = pass2_path.stem + "_metadata.json"

    metadata_path = pass2_path.with_name(metadata_name)
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"No metadata file found — expected {metadata_path.name}"
        )
    return metadata_path


def _load_checkpoint_fact_ids(path: str | Path) -> set[str]:
    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return set()

    try:
        checkpoint_facts = _load_json(checkpoint_path)
    except Exception:
        return set()

    if not isinstance(checkpoint_facts, list):
        return set()

    return {
        str(fact.get("fact_id", ""))
        for fact in checkpoint_facts
        if str(fact.get("fact_id", ""))
        and str(fact.get("rescue_outcome", "")).lower() in {"promote", "drop", "error"}
    }


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


def _chunk_index_lookup(chunks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        str(chunk.get("chunk_id", "")): index
        for index, chunk in enumerate(chunks)
    }


def _format_chunk_preview(chunk: dict[str, Any]) -> str:
    content = str(chunk.get("content", "")).replace("\n", " ").strip()
    return f"[{chunk.get('chunk_id', '')}]: {content[:500]}"


def _context_chunks_for_fact(
    fact: dict[str, Any],
    chunks: list[dict[str, Any]],
    chunk_index: dict[str, int],
) -> str:
    current_chunk_id = str(fact.get("chunk_id", ""))
    if current_chunk_id not in chunk_index:
        return "(chunk not found)"

    index = chunk_index[current_chunk_id]
    selected_indexes = [index]
    if index - 1 >= 0:
        selected_indexes.append(index - 1)
    if index + 1 < len(chunks):
        selected_indexes.append(index + 1)
    if index + 2 < len(chunks):
        selected_indexes.append(index + 2)

    context = [_format_chunk_preview(chunks[selected_index]) for selected_index in selected_indexes[:4]]

    return "\n".join(context) if context else "(no surrounding chunks)"


def _build_rescue_reason(fact: dict[str, Any]) -> str:
    raw = fact.get("raw", {})
    parts = []

    mapping_note = str(fact.get("mapping_note", "")).strip()
    if mapping_note:
        parts.append(f"Pass 2 mapping note: {mapping_note}")

    rescue_note = str(raw.get("rescue_note", "")).strip()
    if rescue_note:
        parts.append(f"Pass 1 rescue note: {rescue_note}")

    failed_checks = raw.get("failed_checks", [])
    if isinstance(failed_checks, list) and failed_checks:
        parts.append("Failed checks: " + ", ".join(str(item) for item in failed_checks))

    return " ".join(parts) if parts else "No explicit rescue reason was recorded."


def _build_prompt(
    metadata: dict[str, Any],
    fact: dict[str, Any],
    rescue_reason: str,
    context_chunks: str,
    valid_canonical_ids: list[str],
) -> str:
    prompt = PASS3_PROMPT.format(
        company=metadata.get("company_name", ""),
        document_period=metadata.get("primary_period", ""),
        filing_type=metadata.get("filing_type", ""),
        default_currency=metadata.get("currency", "USD"),
        fact_json=json.dumps(fact, ensure_ascii=False, indent=2),
        rescue_reason=rescue_reason,
        context_chunks=context_chunks,
        valid_canonical_ids="\n".join(
            f"- {canonical_id}" for canonical_id in valid_canonical_ids
        ),
    )
    prompt += (
        "\n\nCRITICAL RULES:\n"
        "- You may ONLY use canonical_ids from the valid list above.\n"
        "- If the correct canonical_id is not in the list, set canonical_id to null and rescue_outcome = \"drop\".\n"
        "- Never invent or create new canonical_ids.\n"
        "- Never use snake_case of the raw_name as a canonical_id.\n"
    )
    return prompt


def _call_openai(prompt: str) -> dict[str, Any]:
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
        messages=[{"role": "system", "content": prompt}],
        timeout=API_TIMEOUT_SECONDS,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(_strip_code_fences(content))


def _apply_rescue_update(fact: dict[str, Any], rescue_result: dict[str, Any]) -> None:
    raw = fact.setdefault("raw", {})
    rescue_outcome = str(rescue_result.get("rescue_outcome", "")).lower()

    fact["rescue_outcome"] = rescue_outcome
    fact["resolution_evidence"] = rescue_result.get("resolution_evidence")
    fact["resolution_note"] = rescue_result.get("resolution_note")
    fact["normalization_decision"] = rescue_result.get(
        "normalization_decision",
        "normalized" if rescue_outcome == "promote" else "drop",
    )

    canonical_id = rescue_result.get("canonical_id")
    if canonical_id:
        fact["canonical_id"] = canonical_id

    if rescue_result.get("value_normalized") is not None:
        fact["value_normalized"] = rescue_result.get("value_normalized")

    segment_name = rescue_result.get("segment_name", "")
    if segment_name is not None:
        fact["segment"] = segment_name
        raw["segment_name"] = segment_name

    for key in ["resolved_period_start", "resolved_period_end", "period_type", "scope"]:
        value = rescue_result.get(key)
        if value:
            raw[key] = value


def _mark_rescue_error(fact: dict[str, Any], note: str) -> None:
    fact["rescue_outcome"] = "error"
    fact["resolution_evidence"] = None
    fact["resolution_note"] = note


def _valid_canonical_ids_from_registry(path: str | Path = "metric_registry.json") -> list[str]:
    registry = _load_json(path)
    return sorted(
        {
            str(metric.get("canonical_id", "")).strip()
            for metric in registry
            if str(metric.get("canonical_id", "")).strip()
        }
    )


def _validate_rescue_result(
    rescue_result: dict[str, Any],
    valid_canonical_ids: set[str],
) -> dict[str, Any]:
    validated = dict(rescue_result)
    canonical_id = str(validated.get("canonical_id") or "").strip()
    if canonical_id and canonical_id not in valid_canonical_ids:
        print(f"REJECTED invented canonical_id: {canonical_id}", flush=True)
        validated["rescue_outcome"] = "drop"
        validated["canonical_id"] = None
        validated["normalization_decision"] = "drop"
        validated["resolution_note"] = "Rejected: canonical_id not in registry"
    return validated


def _normalize_label(value: str) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").split())


def _promotion_allowed(fact: dict[str, Any], rescue_result: dict[str, Any]) -> tuple[bool, str]:
    canonical_id = str(rescue_result.get("canonical_id") or "").strip()
    if not canonical_id:
        return True, ""

    raw = fact.get("raw", {}) or {}
    raw_name = str(raw.get("raw_name") or fact.get("metric") or "")
    normalized_raw_name = _normalize_label(raw_name)

    if not normalized_raw_name:
        return False, "Rejected: empty raw label for promotion"

    if normalized_raw_name in {"total", "subtotal"}:
        return False, "Rejected: table scaffold label"
    if normalized_raw_name.startswith("row "):
        return False, "Rejected: table scaffold label"
    if normalized_raw_name in {
        "total liabilities and equity",
        "total liabilities",
    }:
        return False, "Rejected: balance-sheet identity label"

    if canonical_id == "total_assets":
        allowed_total_asset_labels = {
            "asset",
            "assets",
            "total assets",
            "total current assets",
            "total non current assets",
            "total non-current assets",
            "total current asset",
            "total non current asset",
            "total non-current asset",
        }
        if normalized_raw_name not in allowed_total_asset_labels:
            return False, "Rejected: raw label too broad for total_assets"

    if canonical_id == "total_revenue":
        revenue_terms = {"revenue", "sales", "net sales", "turnover"}
        if not any(term in normalized_raw_name for term in revenue_terms):
            return False, "Rejected: geography/label-only revenue row"

    return True, ""


def _print_summary(facts: list[dict[str, Any]]) -> None:
    attempted = [
        fact for fact in facts
        if fact.get("rescue_outcome") in {"promote", "drop", "error"}
    ]
    promoted = sum(1 for fact in attempted if fact.get("rescue_outcome") == "promote")
    dropped = sum(1 for fact in attempted if fact.get("rescue_outcome") == "drop")
    errors = sum(1 for fact in attempted if fact.get("rescue_outcome") == "error")

    print(f"Total rescue facts attempted: {len(attempted)}", flush=True)
    print(f"Promoted count: {promoted}", flush=True)
    print(f"Dropped count: {dropped}", flush=True)
    print(f"Failed/error count: {errors}", flush=True)


def run_pass3(
    input_path: str | Path = DEFAULT_INPUT,
    output_path: str | Path = DEFAULT_OUTPUT,
    dry_run: bool = False,
    sample_mode: bool = False,
) -> list[dict[str, Any]]:
    facts = _load_json(input_path)
    chunks = _load_json(_chunks_path_for_input(input_path))
    metadata = _load_json(_metadata_path_for_input(input_path))
    valid_canonical_ids = _valid_canonical_ids_from_registry()
    valid_canonical_id_set = set(valid_canonical_ids)
    chunk_index = _chunk_index_lookup(chunks)
    checkpoint_fact_ids = _load_checkpoint_fact_ids(output_path)

    rescue_queue = [
        fact for fact in facts
        if str(fact.get("normalization_decision", "")).lower() == "partial"
        and str(fact.get("fact_id", "")) not in checkpoint_fact_ids
    ]
    skipped_from_checkpoint = sum(
        1
        for fact in facts
        if str(fact.get("normalization_decision", "")).lower() == "partial"
        and str(fact.get("fact_id", "")) in checkpoint_fact_ids
    )
    print(
        f"Skipped {skipped_from_checkpoint} already-rescued facts from checkpoint",
        flush=True,
    )

    if sample_mode:
        rescue_queue = rescue_queue[:SAMPLE_PARTIAL_FACTS]
        print(
            f"Sample mode: processing first {SAMPLE_PARTIAL_FACTS} partial facts only",
            flush=True,
        )

    if dry_run:
        for fact in rescue_queue:
            context_chunks = _context_chunks_for_fact(fact, chunks, chunk_index)
            rescue_reason = _build_rescue_reason(fact)
            print(f"FACT: {fact.get('fact_id')}", flush=True)
            print(f"RESCUE REASON: {rescue_reason}", flush=True)
            print("CONTEXT CHUNKS:", flush=True)
            print(context_chunks, flush=True)
            print("-" * 80, flush=True)
        return facts

    processed_since_write = 0
    for fact in rescue_queue:
        fact_id = fact.get("fact_id", "")
        context_chunks = _context_chunks_for_fact(fact, chunks, chunk_index)
        rescue_reason = _build_rescue_reason(fact)
        prompt = _build_prompt(
            metadata,
            fact,
            rescue_reason,
            context_chunks,
            valid_canonical_ids,
        )
        print(f"Rescuing {fact_id}...", flush=True)

        try:
            result = _call_openai(prompt)
        except Exception as first_error:
            print(
                f"Error rescuing {fact_id}, retrying in {RETRY_WAIT_SECONDS}s: {first_error!r}",
                flush=True,
            )
            time.sleep(RETRY_WAIT_SECONDS)
            try:
                result = _call_openai(prompt)
            except Exception as second_error:
                print(f"Failed rescuing {fact_id}: {second_error!r}", flush=True)
                _mark_rescue_error(fact, f"API error: {second_error}")
                continue

        if not isinstance(result, dict):
            _mark_rescue_error(fact, "Parse error: rescue response was not a JSON object")
            continue

        outcome = str(result.get("rescue_outcome", "")).lower()
        if outcome not in {"promote", "drop"}:
            _mark_rescue_error(fact, "Parse error: invalid rescue_outcome")
            processed_since_write += 1
            if processed_since_write >= 10:
                _write_json(output_path, facts)
                processed_since_write = 0
            continue

        result = _validate_rescue_result(result, valid_canonical_id_set)
        if str(result.get("rescue_outcome", "")).lower() == "promote":
            is_allowed, rejection_note = _promotion_allowed(fact, result)
            if not is_allowed:
                print(
                    f"REJECTED suspicious promotion: {fact_id} -> {result.get('canonical_id')}",
                    flush=True,
                )
                result["rescue_outcome"] = "drop"
                result["canonical_id"] = None
                result["normalization_decision"] = "drop"
                result["resolution_note"] = rejection_note
        _apply_rescue_update(fact, result)
        processed_since_write += 1
        if processed_since_write >= 10:
            _write_json(output_path, facts)
            processed_since_write = 0

    _write_json(output_path, facts)
    _print_summary(facts)
    return facts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Pass 3 fact rescue")
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        metavar="PATH",
        help="Path to Pass 2 output JSON (default: pass2_output.json)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help="Path to Pass 3 output JSON (default: pass3_output.json)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample", action="store_true")
    parser.add_argument(
        "--summary",
        metavar="PATH",
        help="Print summary only for an existing pass3 output file",
    )
    args = parser.parse_args()

    if args.summary:
        _print_summary(_load_json(args.summary))
        raise SystemExit(0)

    run_pass3(
        input_path=args.input,
        output_path=args.output,
        dry_run=args.dry_run,
        sample_mode=args.sample,
    )
