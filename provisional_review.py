from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


REVIEW_FIELDNAMES = [
    "raw_name",
    "metric_core",
    "metric_definition",
    "fact_class",
    "raw_unit",
    "period",
    "best_canonical_id",
    "best_score",
    "second_best_score",
    "reason",
    "triage_bucket",
    "recommended_action",
    "automation_status",
    "proposed_canonical_id",
    "review_status",
    "reviewed_canonical_id",
    "review_notes",
]

AUTO_HANDLED_STATUSES = {
    "auto_route_financial",
    "auto_keep_company_specific",
    "auto_keep_reviewed_provisional",
}


_UNIVERSAL_PATTERNS = [
    ("non_renewable_energy_share", r"\bnon[-\s]?renewable energy share\b"),
    ("combined_scope_1_2_emissions_intensity", r"\bscope\s*1\s*(?:\+|&|and)\s*(?:scope\s*)?2\b.*\bintensity\b|\bscope\s*1\+2\b.*\bintensity\b|\bscope\s*1&scope\s*2\b.*\bintensity\b"),
    ("combined_scope_1_2_emissions", r"\bscope\s*1\s*(?:\+|&|and)\s*(?:scope\s*)?2\b|\bscope\s*1\+2\b|\bscope\s*1&scope\s*2\b"),
    ("water_conservation_potential", r"\bwater conservation potential\b|\brainwater conservation potential\b|\bwater capacity created\b|\bwater replenishment potential\b"),
    ("employee_headcount", r"\btotal permanent employees\b|\bemployee headcount\b|\bnumber of employees\b"),
    ("worker_headcount", r"\bpermanent workers\b|\bworker headcount\b|\bnumber of workers\b"),
    ("female_workforce_share", r"\bfemale employees\b|\bwomen employees\b|\bgender diversity\b"),
    ("employee_turnover_rate", r"\bemployee turnover\b|\battrition\b"),
    ("employee_training_coverage", r"\btrained on\b|\btraining coverage\b|\bemployees trained\b|\bworkers trained\b"),
    ("customer_satisfaction_score", r"\bcustomer satisfaction\b|\bconsumer satisfaction\b|\bcsat\b|\bcsi\b"),
    ("patent_count", r"\bpatents?\b"),
    ("water_neutral_facility_count", r"\bwater neutral (?:plant|facility)\b"),
    ("zero_hazardous_waste_to_landfill_facilities", r"\bzhwl\b|\bzero hazardous waste\b"),
    ("biodiversity_tree_count", r"\btrees\b|\bmiyawaki\b"),
    ("biodiversity_restoration_area", r"\bsq\.?mt\b|\bsquare meters\b|\bbiodiversity\b.*\barea\b|\bmiyawaki\b.*\barea\b"),
    ("green_building_certified_units", r"\bgreen building\b"),
    ("carbon_neutral_facility_count", r"\bcarbon neutral units\b|\bcarbon neutral facilit(?:y|ies)\b|\bcertified as carbon neutral\b"),
    ("epr_compliance_rate", r"\bepr compliance\b"),
    ("recycled_plastic_content_share", r"\brecycled plastics?\b|\bldpe\b|\bpet by volume\b|\bpcr\b"),
    ("code_of_conduct_coverage", r"\bcode of conduct\b|\bbusiness ethics\b"),
    ("farmer_reach", r"\bfarmers? enrolled\b|\bfarmers? reached\b"),
    ("distribution_reach", r"\bnetwork reach\b|\boutlets?\b|\bvillages\b|\bdistributors?\b"),
]

_COMPANY_SPECIFIC_PATTERNS = [
    r"\bparachute\b|\bsaffola\b|\bbeardo\b|\bcoconut oil\b|\bhair oils?\b|\bpremium personal care\b|\bfoods delivered\b",
    r"\bbangladesh\b|\bvietnam\b|\begypt\b|\bmena\b|\bmiddle east\b|\bsouth africa\b|\bsouth-east asia\b|\binternational business\b|\bdomestic business\b",
    r"\bperundurai\b|\bpuducherry\b|\bsanand\b|\bjalgaon\b|\bguhawati\b",
    r"\bcategory [123] (?:rigids|flexibles|multi-layered packaging)\b",
]

_FINANCIAL_PATTERNS = [
    r"\bebitda\b|\bprofit\b|\bpat\b|\beps\b|\bmarket capitalisation\b|\bdividend\b|\bdebt\b",
    r"\bturnover\b|\brevenue from operations\b|\boperating margin\b|\bcurrent ratio\b|\breturn on net worth\b",
    r"\bcash generated\b|\bnet surplus\b|\bemployee cost\b|\badvertisement and sales promotion\b|\bcapex\b|\bcapital expenditure\b",
]

_EXTRACTOR_BUG_PATTERNS = [
    r"\bcapacity created\b",
]

_UNIVERSAL_COMPILED = [
    (canonical_id, re.compile(pattern, re.I))
    for canonical_id, pattern in _UNIVERSAL_PATTERNS
]
_COMPANY_SPECIFIC_COMPILED = [re.compile(pattern, re.I) for pattern in _COMPANY_SPECIFIC_PATTERNS]
_FINANCIAL_COMPILED = [re.compile(pattern, re.I) for pattern in _FINANCIAL_PATTERNS]
_EXTRACTOR_BUG_COMPILED = [re.compile(pattern, re.I) for pattern in _EXTRACTOR_BUG_PATTERNS]


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").lower()).strip("_")
    return re.sub(r"_+", "_", cleaned) or "unknown_metric"


def _score_value(entry: dict[str, Any]) -> float | None:
    score = entry.get("best_score")
    if isinstance(score, (int, float)):
        return float(score)
    return None


def _entry_text(entry: dict[str, Any]) -> str:
    return " ".join(
        str(entry.get(key) or "")
        for key in ("raw_name", "metric_core", "metric_definition", "reason")
    )


def classify_provisional(entry: dict[str, Any]) -> dict[str, str]:
    text = _entry_text(entry)
    best_canonical_id = str(entry.get("best_canonical_id") or "")
    score = _score_value(entry)
    reason = str(entry.get("reason") or "")
    review_action = str(entry.get("review_action") or "").strip()

    if review_action == "route_financial":
        return {
            "triage_bucket": "out_of_operational_scope",
            "recommended_action": "route_to_financial_registry_or_ignore",
            "automation_status": "auto_route_financial",
            "proposed_canonical_id": best_canonical_id or _slugify(str(entry.get("raw_name") or "")),
        }

    if review_action in {"keep_provisional", "do_not_auto_accept"}:
        return {
            "triage_bucket": "reviewed_provisional",
            "recommended_action": "keep_reviewed_provisional",
            "automation_status": "auto_keep_reviewed_provisional",
            "proposed_canonical_id": best_canonical_id or _slugify(str(entry.get("raw_name") or "")),
        }

    if review_action == "candidate_canonical":
        return {
            "triage_bucket": "universal_gap",
            "recommended_action": "add_canonical",
            "automation_status": "candidate_canonical",
            "proposed_canonical_id": best_canonical_id or _slugify(str(entry.get("raw_name") or "")),
        }

    for canonical_id, pattern in _UNIVERSAL_COMPILED:
        if not pattern.search(text):
            continue
        if best_canonical_id == canonical_id and score is not None and score >= 0.55:
            return {
                "triage_bucket": "near_miss",
                "recommended_action": "review_existing_mapping",
                "automation_status": "needs_human_review",
                "proposed_canonical_id": canonical_id,
            }
        return {
            "triage_bucket": "universal_gap",
            "recommended_action": "add_canonical",
            "automation_status": "candidate_canonical",
            "proposed_canonical_id": canonical_id,
        }

    if any(pattern.search(text) for pattern in _EXTRACTOR_BUG_COMPILED):
        return {
            "triage_bucket": "extractor_definition_bug",
            "recommended_action": "fix_define_step_then_regenerate",
            "automation_status": "fix_extractor",
            "proposed_canonical_id": _slugify(str(entry.get("raw_name") or "")),
        }

    if score is not None and score >= 0.55:
        return {
            "triage_bucket": "near_miss",
            "recommended_action": (
                "review_existing_mapping"
                if "ambiguous match" in reason
                else "review_or_alias_existing_canonical"
            ),
            "automation_status": "needs_human_review",
            "proposed_canonical_id": best_canonical_id or _slugify(str(entry.get("raw_name") or "")),
        }

    if any(pattern.search(text) for pattern in _COMPANY_SPECIFIC_COMPILED):
        return {
            "triage_bucket": "company_specific",
            "recommended_action": "keep_company_specific_provisional",
            "automation_status": "auto_keep_company_specific",
            "proposed_canonical_id": _slugify(str(entry.get("raw_name") or "")),
        }

    if any(pattern.search(text) for pattern in _FINANCIAL_COMPILED):
        return {
            "triage_bucket": "out_of_operational_scope",
            "recommended_action": "route_to_financial_registry_or_ignore",
            "automation_status": "auto_route_financial",
            "proposed_canonical_id": _slugify(str(entry.get("raw_name") or "")),
        }

    return {
        "triage_bucket": "needs_review",
        "recommended_action": "human_review",
        "automation_status": "needs_human_review",
        "proposed_canonical_id": _slugify(str(entry.get("raw_name") or "")),
    }


def build_review_rows(results: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry in results.get("provisional", []) or []:
        classification = classify_provisional(entry)
        score = _score_value(entry)
        second_best_score = entry.get("second_best_score")
        rows.append(
            {
                "raw_name": str(entry.get("raw_name") or ""),
                "metric_core": str(entry.get("metric_core") or ""),
                "metric_definition": str(entry.get("metric_definition") or ""),
                "fact_class": str(entry.get("fact_class") or ""),
                "raw_unit": str(entry.get("raw_unit") or ""),
                "period": str(entry.get("period") or ""),
                "best_canonical_id": str(entry.get("best_canonical_id") or ""),
                "best_score": "" if score is None else f"{score:.3f}",
                "second_best_score": (
                    f"{float(second_best_score):.3f}"
                    if isinstance(second_best_score, (int, float))
                    else ""
                ),
                "reason": str(entry.get("reason") or ""),
                **classification,
                "review_status": "",
                "reviewed_canonical_id": "",
                "review_notes": "",
            }
        )
    return rows


def summarize_review_rows(rows: list[dict[str, str]]) -> dict[str, Counter]:
    return {
        "triage_bucket": Counter(row["triage_bucket"] for row in rows),
        "recommended_action": Counter(row["recommended_action"] for row in rows),
        "automation_status": Counter(row["automation_status"] for row in rows),
    }


def write_review_files(
    results: dict[str, list[dict[str, Any]]],
    output_prefix: str | Path,
) -> dict[str, Any]:
    rows = build_review_rows(results)
    action_rows = [
        row for row in rows
        if row["automation_status"] not in AUTO_HANDLED_STATUSES
    ]
    prefix = Path(output_prefix)
    csv_path = prefix.with_suffix(".csv")
    md_path = prefix.with_suffix(".md")
    action_csv_path = prefix.with_name(f"{prefix.name}_action_queue").with_suffix(".csv")

    for attempt in range(0, 100):
        candidate_csv_path = csv_path if attempt == 0 else prefix.with_name(f"{prefix.name}_{attempt}").with_suffix(".csv")
        try:
            with candidate_csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDNAMES)
                writer.writeheader()
                writer.writerows(rows)
            csv_path = candidate_csv_path
            break
        except PermissionError:
            if attempt == 99:
                raise

    counts = summarize_review_rows(rows)
    action_counts = summarize_review_rows(action_rows)
    total = sum(len(results.get(bucket, []) or []) for bucket in ("accept", "provisional", "quarantine"))
    for attempt in range(0, 100):
        candidate_action_csv_path = (
            action_csv_path
            if attempt == 0
            else prefix.with_name(f"{prefix.name}_action_queue_{attempt}").with_suffix(".csv")
        )
        try:
            with candidate_action_csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDNAMES)
                writer.writeheader()
                writer.writerows(action_rows)
            action_csv_path = candidate_action_csv_path
            break
        except PermissionError:
            if attempt == 99:
                raise

    for attempt in range(0, 100):
        candidate_md_path = md_path if attempt == 0 else prefix.with_name(f"{prefix.name}_{attempt}").with_suffix(".md")
        try:
            with candidate_md_path.open("w", encoding="utf-8") as handle:
                handle.write("# Provisional Review Queue\n\n")
                handle.write(f"- Total facts: {total}\n")
                handle.write(f"- Accept: {len(results.get('accept', []) or [])}\n")
                handle.write(f"- Provisional: {len(results.get('provisional', []) or [])}\n")
                handle.write(f"- Quarantine: {len(results.get('quarantine', []) or [])}\n\n")
                for title, key in (
                    ("Triage Counts", "triage_bucket"),
                    ("Recommended Actions", "recommended_action"),
                    ("Automation Status", "automation_status"),
                ):
                    handle.write(f"## {title}\n\n")
                    for label, count in counts[key].most_common():
                        handle.write(f"- {label}: {count}\n")
                    handle.write("\n")

                handle.write("## Action Queue Counts\n\n")
                handle.write(f"- Rows needing action: {len(action_rows)}\n")
                for label, count in action_counts["automation_status"].most_common():
                    handle.write(f"- {label}: {count}\n")
                handle.write("\n")

                handle.write("## Rows\n\n")
                handle.write(
                    "| raw_name | best_canonical_id | best_score | triage_bucket | "
                    "recommended_action | automation_status | proposed_canonical_id | reason |\n"
                )
                handle.write("|---|---|---:|---|---|---|---|---|\n")
                for row in rows:
                    cells = [
                        row["raw_name"],
                        row["best_canonical_id"],
                        row["best_score"],
                        row["triage_bucket"],
                        row["recommended_action"],
                        row["automation_status"],
                        row["proposed_canonical_id"],
                        row["reason"],
                    ]
                    escaped = [
                        str(cell or "").replace("|", "\\|").replace("\n", " ")
                        for cell in cells
                    ]
                    handle.write("| " + " | ".join(escaped) + " |\n")
            md_path = candidate_md_path
            break
        except PermissionError:
            if attempt == 99:
                raise

    return {
        "csv_path": csv_path,
        "action_csv_path": action_csv_path,
        "markdown_path": md_path,
        "rows": rows,
        "action_rows": action_rows,
        "counts": counts,
    }


def _load_pass1_payload(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a provisional review queue from Pass 1 output.")
    parser.add_argument("input", help="Path to Pass 1 EDC JSON")
    parser.add_argument(
        "--output-prefix",
        metavar="PATH",
        help="Output prefix for .csv and .md files",
    )
    args = parser.parse_args()

    import normalizer

    payload = _load_pass1_payload(args.input)
    facts, _ = normalizer._extract_pass1_facts_and_metadata(payload, source_path=args.input)
    results = normalizer.dry_run(facts)
    prefix = args.output_prefix or f"{Path(args.input).with_suffix('').name}_provisional_review"
    report = write_review_files(results, prefix)
    print(f"Provisional rows: {len(report['rows'])}")
    print(f"CSV: {report['csv_path'].resolve()}")
    print(f"Action queue CSV: {report['action_csv_path'].resolve()}")
    print(f"Markdown: {report['markdown_path'].resolve()}")


if __name__ == "__main__":
    main()
