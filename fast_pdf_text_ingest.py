from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import fitz

from audit_selected_pages import run_coverage_audit
from section_finder import find_operational_sections, get_registry_keyword_weights

EXCLUDE_KEYWORDS = {
    "independent auditor": 7,
    "financial statements": 7,
    "consolidated financial": 7,
    "standalone financial": 7,
    "notes to accounts": 6,
    "notes to the financial": 6,
    "balance sheet": 6,
    "statement of profit and loss": 6,
    "cash flow statement": 6,
    "shareholding": 5,
    "notice": 4,
    "proxy": 4,
    "secretarial audit": 5,
    "directors' report": 3,
    "board's report": 3,
}


def _token_estimate(content: str) -> int:
    return max(1, (len(content) + 3) // 4) if content else 0


def _normalize_space(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _page_score(text: str) -> tuple[int, int]:
    lower = text.lower()
    include_score = sum(weight for keyword, weight in get_registry_keyword_weights().items() if keyword in lower)
    exclude_score = sum(weight for keyword, weight in EXCLUDE_KEYWORDS.items() if keyword in lower)
    return include_score, exclude_score


def _has_numeric_metric(text: str) -> bool:
    if not re.search(r"\d", text):
        return False
    return bool(
        re.search(
            r"[%₹$€£]|"
            r"\b(?:crore|lakh|million|billion|tonnes?|tons?|kg|kl|litres?|"
            r"employees?|workers?|sites?|plants?|factories?|facilities?|"
            r"stores?|outlets?|suppliers?|hours?|days?|women|men|co2|co2e)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def extract_pages(pdf_path: str | Path) -> list[dict[str, Any]]:
    doc = fitz.open(str(pdf_path))
    pages = []
    for page_index, page in enumerate(doc, start=1):
        text = _normalize_space(page.get_text("text"))
        include_score, exclude_score = _page_score(text)
        pages.append(
            {
                "page": page_index,
                "text": text,
                "include_score": include_score,
                "exclude_score": exclude_score,
                "has_numeric_metric": _has_numeric_metric(text),
            }
        )
    return pages


def select_operational_pages(
    pages: list[dict[str, Any]],
    *,
    min_score: int,
    max_pages: int | None,
) -> list[dict[str, Any]]:
    selected = [
        page for page in pages
        if page["has_numeric_metric"]
        and page["include_score"] >= min_score
        and page["include_score"] > page["exclude_score"]
        and len(page["text"].split()) >= 40
    ]
    selected.sort(key=lambda page: (-page["include_score"], page["page"]))
    if max_pages:
        selected = selected[:max_pages]
    return sorted(selected, key=lambda page: page["page"])


def _split_words_with_overlap(words: list[str], max_words: int, overlap_words: int) -> list[list[str]]:
    chunks = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_words)
        chunks.append(words[start:end])
        if end >= len(words):
            break
        start = max(end - overlap_words, start + 1)
    return chunks


def build_chunks(
    selected_pages: list[dict[str, Any]],
    *,
    doc_id: str,
    company_name: str,
    filing_year: int,
    fiscal_year_end: str,
    max_words: int,
    overlap_words: int,
) -> list[dict[str, Any]]:
    chunks = []
    primary_period = f"FY{filing_year}"
    prior_period = f"FY{filing_year - 1}"
    for page in selected_pages:
        words = page["text"].split()
        for part_index, chunk_words in enumerate(
            _split_words_with_overlap(words, max_words=max_words, overlap_words=overlap_words),
            start=1,
        ):
            content = " ".join(chunk_words)
            chunk_id = f"{doc_id}_p{page['page']:03d}_{part_index}"
            chunks.append(
                {
                    "doc_id": doc_id,
                    "section_id": f"{doc_id}_page_{page['page']:03d}",
                    "chunk_id": chunk_id,
                    "prev_chunk_id": None,
                    "next_chunk_id": None,
                    "section_title": f"{company_name} operational text page {page['page']}",
                    "parent_section": "fast_pdf_text_ingest",
                    "page_start": page["page"],
                    "page_end": page["page"],
                    "chunk_type": "text",
                    "content": content,
                    "char_count": len(content),
                    "token_estimate": _token_estimate(content),
                    "temporal_context": {
                        "filing_year": filing_year,
                        "fiscal_year_end": fiscal_year_end,
                        "primary_period": primary_period,
                        "prior_period": prior_period,
                    },
                }
            )
    for index, chunk in enumerate(chunks):
        chunk["prev_chunk_id"] = chunks[index - 1]["chunk_id"] if index > 0 else None
        chunk["next_chunk_id"] = chunks[index + 1]["chunk_id"] if index + 1 < len(chunks) else None
    return chunks


def write_metadata(
    output_chunks_path: str | Path,
    *,
    company_name: str,
    filing_type: str,
    filing_year: int,
    fiscal_year_end: str,
    currency: str,
    coverage_audit: dict[str, Any] | None = None,
) -> Path:
    chunks_path = Path(output_chunks_path)
    metadata_path = chunks_path.with_name(f"{chunks_path.stem.replace('_chunks', '')}_metadata.json")
    if chunks_path.stem.endswith("_chunks"):
        metadata_path = chunks_path.with_name(f"{chunks_path.stem[:-7]}_metadata.json")
    metadata = {
        "company_name": company_name,
        "filing_type": filing_type,
        "has_segments": True,
        "filing_year": filing_year,
        "fiscal_year_end_month": fiscal_year_end,
        "primary_period": f"FY{filing_year}",
        "prior_period": f"FY{filing_year - 1}",
        "currency": currency,
        "metadata_confidence": "medium",
    }
    if coverage_audit is not None:
        metadata["coverage_audit"] = coverage_audit
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return metadata_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast page-text PDF ingestion using PyMuPDF.")
    parser.add_argument("pdf", help="Input PDF path")
    parser.add_argument("--output", required=True, help="Output chunks JSON path")
    parser.add_argument("--company-name", default="Company")
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--filing-type", default="Annual Report")
    parser.add_argument("--filing-year", type=int, default=2022)
    parser.add_argument("--fiscal-year-end", default="March")
    parser.add_argument("--currency", default="INR")
    parser.add_argument("--min-score", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=35)
    parser.add_argument("--max-words", type=int, default=520)
    parser.add_argument("--overlap-words", type=int, default=70)
    parser.add_argument("--page-report", default="", help="Optional selected-page report JSON path")
    parser.add_argument(
        "--force-continue",
        action="store_true",
        help="Continue even if the automatic coverage audit reports HIGH risk unselected pages.",
    )
    args = parser.parse_args()

    doc_id = args.doc_id or re.sub(r"[^a-z0-9]+", "_", args.company_name.lower()).strip("_")
    pages = extract_pages(args.pdf)
    section_selection = find_operational_sections(args.pdf)
    coverage_audit_result = run_coverage_audit(args.pdf, section_selection["selected_pages"])
    if coverage_audit_result.risk_level == "HIGH" and not args.force_continue:
        flagged_pages = ", ".join(str(row["page"]) for row in coverage_audit_result.flagged_pages if row["risk_level"] == "HIGH")
        raise SystemExit(
            "PIPELINE HALTED - Coverage audit found "
            f"{coverage_audit_result.high_signal_unselected} high-signal unselected pages.\n"
            f"Pages: {flagged_pages or 'none listed'}\n"
            "Rerun with --force-continue to override."
        )
    selected_page_indexes = set(section_selection["selected_pages"])
    selected_pages = [
        page
        for page in pages
        if (int(page["page"]) - 1) in selected_page_indexes
    ]
    chunks = build_chunks(
        selected_pages,
        doc_id=doc_id,
        company_name=args.company_name,
        filing_year=args.filing_year,
        fiscal_year_end=args.fiscal_year_end,
        max_words=args.max_words,
        overlap_words=args.overlap_words,
    )

    output_path = Path(args.output)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(chunks, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    metadata_path = write_metadata(
        output_path,
        company_name=args.company_name,
        filing_type=args.filing_type,
        filing_year=args.filing_year,
        fiscal_year_end=args.fiscal_year_end,
        currency=args.currency,
        coverage_audit={
            "high_signal_unselected": coverage_audit_result.high_signal_unselected,
            "borderline_review_candidates": coverage_audit_result.borderline_review_candidates,
            "risk_level": coverage_audit_result.risk_level,
            "coverage_audit_overridden": bool(args.force_continue and coverage_audit_result.risk_level == "HIGH"),
            "flagged_pages": [
                {
                    "page": row["page"],
                    "risk_level": row["risk_level"],
                    "miss_reason": row["miss_reason"],
                }
                for row in coverage_audit_result.flagged_pages
            ],
        },
    )
    if args.page_report:
        with Path(args.page_report).open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "section_selection": section_selection,
                    "coverage_audit": {
                        "high_signal_unselected": coverage_audit_result.high_signal_unselected,
                        "borderline_review_candidates": coverage_audit_result.borderline_review_candidates,
                        "risk_level": coverage_audit_result.risk_level,
                        "coverage_audit_overridden": bool(args.force_continue and coverage_audit_result.risk_level == "HIGH"),
                        "flagged_pages": [
                            {
                                "page": row["page"],
                                "risk_level": row["risk_level"],
                                "miss_reason": row["miss_reason"],
                            }
                            for row in coverage_audit_result.flagged_pages
                        ],
                    },
                    "pages": [
                        {
                            "page": page["page"],
                            "include_score": page["include_score"],
                            "exclude_score": page["exclude_score"],
                            "preview": page["text"][:500],
                        }
                        for page in selected_pages
                    ],
                },
                handle,
                indent=2,
                ensure_ascii=False,
            )
            handle.write("\n")

    print(f"Pages scanned: {len(pages)}")
    print(f"Pages selected: {len(selected_pages)}")
    print(f"Section finder method: {section_selection['method']}")
    print(
        "Coverage audit: "
        f"risk={coverage_audit_result.risk_level}, "
        f"high_signal_unselected={coverage_audit_result.high_signal_unselected}, "
        f"borderline_review_candidates={coverage_audit_result.borderline_review_candidates}"
    )
    if args.force_continue and coverage_audit_result.risk_level == "HIGH":
        print("WARNING: coverage audit override active", flush=True)
    if section_selection.get("toc_sections_found"):
        print("TOC sections found:", "; ".join(section_selection["toc_sections_found"]))
    if section_selection.get("warnings"):
        print("Section finder warnings:", " | ".join(section_selection["warnings"]))
    print(f"Chunks written: {len(chunks)} -> {output_path.resolve()}")
    print(f"Metadata written: {metadata_path.resolve()}")
    if selected_pages:
        print("Selected pages:", ", ".join(str(page["page"]) for page in selected_pages))


if __name__ == "__main__":
    main()
