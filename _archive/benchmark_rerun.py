from __future__ import annotations

import csv
import json
import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from check_confidence_fields import _enrich_fact as enrich_confidence_fact
from check_provenance_fields import _build_chunk_lookup, _build_pass1_lookup, _fill_provenance
from normalizer import _metric_registry_with_seed
from unit_normaliser import normalise_fact_value

ROOT = Path(__file__).resolve().parent
OUTDIR = ROOT / "workspace_test_outputs"

# PDF paths below are resolved relative to ROOT/pdfs/ so the project is portable.
# Place each PDF in C:\Users\Vedika.Sahoo\test\pdfs\ (or update the paths as needed).
_PDFS = ROOT / "pdfs"

BENCHMARKS = {
    "tata_consumer": {
        "pdf": _PDFS / "tata-consumer-ar-2023-24.pdf",
        "company_name": "Tata Consumer Products",
        "doc_id": "tata_consumer",
        "filing_type": "Annual Report",
        "filing_year": 2024,
        "fiscal_year_end": "March",
        "currency": "INR",
    },
    "gcpl": {
        "pdf": _PDFS / "GCPL_Annual_Report_2022_23_b1d494e9a9.pdf",
        "company_name": "Godrej Consumer Products",
        "doc_id": "gcpl",
        "filing_type": "annual_report",
        "filing_year": 2023,
        "fiscal_year_end": "March",
        "currency": "INR",
    },
    "nestle_india": {
        "pdf": _PDFS / "Annual-Report-2023-24-nestle-india.pdf",
        "company_name": "Nestle India",
        "doc_id": "nestle_india",
        "filing_type": "annual_report",
        "filing_year": 2024,
        "fiscal_year_end": "March",
        "currency": "INR",
    },
    "itc": {
        "pdf": _PDFS / "ITC-Report-and-Accounts-2025.pdf",
        "company_name": "ITC",
        "doc_id": "itc",
        "filing_type": "annual_report",
        "filing_year": 2025,
        "fiscal_year_end": "March",
        "currency": "INR",
    },
    "nestle_india_2022": {
        "pdf": _PDFS / "nestle-india-Annual-Report-2022.pdf",
        "company_name": "Nestle India",
        "doc_id": "nestle_india_2022",
        "filing_type": "annual_report",
        "filing_year": 2022,
        "fiscal_year_end": "December",
        "currency": "INR",
    },
    "nestle_india_2021": {
        "pdf": _PDFS / "Nestle-India-Annual-Report-2021.pdf",
        "company_name": "Nestle India",
        "doc_id": "nestle_india_2021",
        "filing_type": "annual_report",
        "filing_year": 2021,
        "fiscal_year_end": "December",
        "currency": "INR",
    },
}


def run_command(command: list[str]) -> None:
    print("$", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_facts(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, dict):
        facts = payload.get("facts", [])
    else:
        facts = payload
    return [fact for fact in facts if isinstance(fact, dict)]


def pass2_counts(facts: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for fact in facts:
        decision = str(fact.get("normalization_decision") or "").lower()
        if not decision:
            continue
        counts[decision] += 1
    return counts


def period_stats(pass1_facts: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(pass1_facts)
    period_type_present = sum(1 for fact in pass1_facts if str(fact.get("period_type") or "").strip())
    period_start_present = sum(1 for fact in pass1_facts if fact.get("period_start"))
    confidence_counts = Counter(str(f.get("period_confidence") or "") for f in pass1_facts)
    type_counts = Counter(str(f.get("period_type") or "unknown") for f in pass1_facts)
    return {
        "period_type_present": period_type_present,
        "period_start_present": period_start_present,
        "period_confidence": confidence_counts,
        "period_type_counts": type_counts,
        "total": total,
    }


def fact_type_stats(pass1_facts: list[dict[str, Any]]) -> Counter[str]:
    counts = Counter(str(fact.get("fact_type") or "unknown") for fact in pass1_facts)
    return counts


def unit_stats(pass1_facts: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for fact in pass1_facts:
        confidence = str(normalise_fact_value(fact).get("normalisation_confidence") or "failed")
        counts[confidence] += 1
    return counts


def provenance_stats(pass2_facts: list[dict[str, Any]], pass1_path: Path, chunk_path: Path) -> dict[str, int]:
    pass1_lookup = _build_pass1_lookup(pass1_path)
    chunk_lookup = _build_chunk_lookup(chunk_path)
    enriched = [_fill_provenance(fact, pass1_lookup, chunk_lookup) for fact in pass2_facts]
    return {
        "chunk_id_present": sum(1 for fact in enriched if str(fact.get("chunk_id") or "").strip()),
        "section_id_present": sum(1 for fact in enriched if str(fact.get("section_id") or "").strip()),
        "doc_id_present": sum(1 for fact in enriched if str(fact.get("doc_id") or "").strip()),
        "total": len(enriched),
    }


def confidence_enriched(pass2_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry_lookup = {
        str(entry.get("canonical_id") or ""): entry
        for entry in _metric_registry_with_seed()
        if str(entry.get("canonical_id") or "")
    }
    return [enrich_confidence_fact(fact, registry_lookup) for fact in pass2_facts]


def load_page_audit_stats(csv_path: Path) -> dict[str, int]:
    rows: list[dict[str, str]] = []
    with open(csv_path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows.extend(reader)
    return {
        "pages": len(rows),
        "selected": sum(1 for row in rows if str(row.get("selected") or "").lower() == "true"),
        "high_signal_unselected": sum(1 for row in rows if str(row.get("high_signal_unselected") or "").lower() == "true"),
        "review_candidates": sum(1 for row in rows if str(row.get("review_candidate") or "").lower() == "true"),
    }


def rerun_company(key: str, config: dict[str, Any], *, resume: bool = True) -> dict[str, Any]:
    chunks_path = OUTDIR / f"{key}_rerun_fast_chunks.json"
    page_report_path = OUTDIR / f"{key}_rerun_selected_pages.json"
    audit_csv_path = OUTDIR / f"{key}_rerun_section_coverage_audit.csv"
    pass1_path = OUTDIR / f"{key}_pass1_rerun.json"
    pass2_path = OUTDIR / f"{key}_pass2_rerun.json"
    readable_path = OUTDIR / f"{key}_pass2_rerun_readable.csv"

    if not (resume and chunks_path.exists() and page_report_path.exists()):
        run_command(
            [
                sys.executable,
                "fast_pdf_text_ingest.py",
                str(config["pdf"]),
                "--output",
                str(chunks_path),
                "--company-name",
                str(config["company_name"]),
                "--doc-id",
                str(config["doc_id"]),
                "--filing-type",
                str(config["filing_type"]),
                "--filing-year",
                str(config["filing_year"]),
                "--fiscal-year-end",
                str(config["fiscal_year_end"]),
                "--currency",
                str(config["currency"]),
                "--page-report",
                str(page_report_path),
            ]
        )
    if not (resume and audit_csv_path.exists()):
        run_command(
            [
                sys.executable,
                "audit_selected_pages.py",
                str(config["pdf"]),
                "--page-report",
                str(page_report_path),
                "--output",
                str(audit_csv_path),
            ]
        )
    if not (resume and pass1_path.exists()):
        run_command(
            [
                sys.executable,
                "extractor.py",
                "--input",
                str(chunks_path),
                "--output",
                str(pass1_path),
            ]
        )
    if not (resume and pass2_path.exists()):
        run_command(
            [
                sys.executable,
                "normalizer.py",
                "--input",
                str(pass1_path),
                "--output",
                str(pass2_path),
            ]
        )
    if not (resume and readable_path.exists()):
        run_command(
            [
                sys.executable,
                "export_readable_facts.py",
                str(pass1_path),
                str(readable_path),
            ]
        )

    before_path = OUTDIR / f"{key}_pass2.json"
    before_pass2 = load_facts(before_path) if before_path.exists() else []
    after_pass2 = load_facts(pass2_path)
    after_pass1 = load_facts(pass1_path)

    after_pass2_conf = confidence_enriched(after_pass2)

    return {
        "company": key,
        "before_counts": pass2_counts(before_pass2),
        "after_counts": pass2_counts(after_pass2_conf),
        "period": period_stats(after_pass1),
        "fact_type": fact_type_stats(after_pass1),
        "units": unit_stats(after_pass1),
        "provenance": provenance_stats(after_pass2_conf, pass1_path, chunks_path),
        "page_audit": load_page_audit_stats(audit_csv_path),
        "paths": {
            "chunks": chunks_path,
            "page_report": page_report_path,
            "audit_csv": audit_csv_path,
            "pass1": pass1_path,
            "pass2": pass2_path,
            "readable": readable_path,
        },
    }


def format_company_report(result: dict[str, Any]) -> str:
    before = result["before_counts"]
    after = result["after_counts"]
    period = result["period"]
    fact_type = result["fact_type"]
    units = result["units"]
    provenance = result["provenance"]
    page_audit = result["page_audit"]
    total_pass2 = provenance["total"]
    total_pass1 = period["total"]

    lines = [
        f"Company: {result['company']}",
        (
            "Pass 2 before:  "
            f"normalized {before.get('normalized', 0)} / "
            f"partial {before.get('partial', 0)} / "
            f"new_metric {before.get('new_metric', 0)} / "
            f"financial {before.get('out_of_scope_financial', 0)}"
        ),
        (
            "Pass 2 after:   "
            f"normalized {after.get('normalized', 0)} / "
            f"partial {after.get('partial', 0)} / "
            f"new_metric {after.get('new_metric', 0)} / "
            f"financial {after.get('out_of_scope_financial', 0)}"
        ),
        (
            "Delta:          "
            f"{after.get('normalized', 0) - before.get('normalized', 0):+} normalized, "
            f"{after.get('partial', 0) - before.get('partial', 0):+} partial"
        ),
        "",
        "Page selection audit:",
        f"  pages selected:           {page_audit['selected']} / {page_audit['pages']}",
        f"  high_signal_unselected:   {page_audit['high_signal_unselected']}",
        f"  review_candidates:        {page_audit['review_candidates']}",
        "",
        "Period field coverage:",
        f"  period_type present:      {period['period_type_present']} / {total_pass1}",
        f"  period_start present:     {period['period_start_present']} / {total_pass1}",
        (
            "  period_confidence extracted vs inferred: "
            f"{period['period_confidence'].get('extracted', 0)} / {period['period_confidence'].get('inferred', 0)}"
        ),
        "",
        "fact_type coverage:",
        f"  measurement:  {fact_type.get('measurement', 0)}",
        f"  target:       {fact_type.get('target', 0)}",
        f"  baseline:     {fact_type.get('baseline', 0)}",
        f"  ratio:        {fact_type.get('ratio', 0)}",
        f"  boolean:      {fact_type.get('boolean', 0)}",
        f"  count:        {fact_type.get('count', 0)}",
        f"  unknown:      {fact_type.get('unknown', 0)}",
        "",
        "Unit normalisation:",
        f"  success:       {units.get('exact', 0)}",
        f"  inferred:      {units.get('inferred', 0)}",
        f"  needs_context: {units.get('needs_context', 0)}",
        f"  failed:        {units.get('failed', 0)}",
        "",
        "Provenance fields:",
        f"  chunk_id present:    {provenance['chunk_id_present']} / {total_pass2}",
        f"  section_id present:  {provenance['section_id_present']} / {total_pass2}",
        f"  doc_id present:      {provenance['doc_id_present']} / {total_pass2}",
    ]

    warnings: list[str] = []
    before_norm = before.get("normalized", 0)
    after_norm = after.get("normalized", 0)
    if before_norm and after_norm < (before_norm * 0.85):
        warnings.append("normalized count dropped by more than 15%")
    if units.get("needs_context", 0) > 200:
        warnings.append("needs_context unit count above 200")
    if period["period_type_counts"].get("unknown", 0) > (0.10 * total_pass1):
        warnings.append("period_type unknown above 10% of facts")
    if (
        provenance["chunk_id_present"] < total_pass2
        or provenance["section_id_present"] < total_pass2
        or provenance["doc_id_present"] < total_pass2
    ):
        warnings.append("provenance field coverage below 100%")
    if page_audit["high_signal_unselected"] > 0:
        warnings.append("page selection left high-signal pages unselected")

    if warnings:
        lines.extend(["", "Flags:"])
        lines.extend([f"  - {warning}" for warning in warnings])
    lines.append("")
    lines.append("-" * 72)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rerun benchmark annual reports end to end and generate a diff report.")
    parser.add_argument("--company", action="append", choices=sorted(BENCHMARKS.keys()), help="Limit rerun to one or more benchmark companies.")
    parser.add_argument("--no-resume", action="store_true", help="Do not reuse existing rerun artifacts.")
    args = parser.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    selected = args.company or list(BENCHMARKS.keys())
    results = [rerun_company(name, BENCHMARKS[name], resume=not args.no_resume) for name in selected]
    report = "\n".join(format_company_report(result) for result in results)
    report_path = ROOT / "benchmark_diff_report.txt"
    report_path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"Report written: {report_path}")


if __name__ == "__main__":
    main()
