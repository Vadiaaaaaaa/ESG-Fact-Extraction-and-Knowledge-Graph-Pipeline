from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import fitz

from section_finder import (
    ISOLATED_OPERATIONAL_FACT_RE,
    _is_explicitly_excluded,
    _numeric_token_count,
    score_page,
)


KEY_TERMS = [
    "brsr",
    "business responsibility",
    "sustainability",
    "environment",
    "emissions",
    "scope 1",
    "scope 2",
    "scope 3",
    "energy",
    "renewable",
    "water",
    "waste",
    "plastic",
    "packaging",
    "supply chain",
    "manufacturing",
    "factory",
    "safety",
    "training",
    "employee",
    "diversity",
    "distribution",
    "outlet",
]


def _normalize_space(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _hits(text: str) -> str:
    lower = text.lower()
    return "; ".join(term for term in KEY_TERMS if term in lower)


def _preview(text: str, limit: int = 420) -> str:
    return _normalize_space(text.replace("\n", " "))[:limit]


def _load_selected(page_report: str | Path) -> set[int]:
    report = json.loads(Path(page_report).read_text(encoding="utf-8"))
    return set(report["section_selection"]["selected_pages"])


def _hit_set(text: str) -> set[str]:
    lower = text.lower()
    return {term for term in KEY_TERMS if term in lower}


def _review_signal(
    *,
    index: int,
    text: str,
    score: int,
    numeric_tokens: int,
    selected: bool,
    excluded: bool,
    selected_pages: set[int],
) -> tuple[bool, str, str]:
    if selected or excluded:
        return False, "", ""

    hits = _hit_set(text)
    operational_hits = hits & {
        "sustainability",
        "environment",
        "emissions",
        "energy",
        "renewable",
        "water",
        "waste",
        "plastic",
        "packaging",
        "supply chain",
        "manufacturing",
        "factory",
        "safety",
        "training",
        "employee",
        "diversity",
        "distribution",
        "outlet",
    }
    adjacent_to_selected = (index - 1 in selected_pages) or (index + 1 in selected_pages)

    if score >= 15 or (score >= 8 and numeric_tokens >= 20):
        return True, "HIGH", "high_keyword_and_numeric_signal"
    if ISOLATED_OPERATIONAL_FACT_RE.search(text):
        return True, "HIGH", "isolated_operational_fact_pattern"
    if score >= 8 and operational_hits:
        return True, "MEDIUM", "keyword_signal_without_many_numbers"
    if score >= 5 and numeric_tokens >= 10 and operational_hits:
        return True, "MEDIUM", "borderline_keyword_numeric_signal"
    if adjacent_to_selected and score >= 3 and numeric_tokens >= 10 and operational_hits:
        return True, "LOW", "section_boundary_neighbor"
    if numeric_tokens >= 50 and {"manufacturing", "factory", "distribution", "employee", "water", "safety"} & hits:
        return True, "LOW", "numeric_dense_with_operational_terms"
    return False, "", ""


def audit(pdf_path: str | Path, page_report: str | Path) -> list[dict[str, Any]]:
    selected = _load_selected(page_report)
    rows: list[dict[str, Any]] = []
    with fitz.open(str(pdf_path)) as doc:
        for index, page in enumerate(doc):
            text = _normalize_space(page.get_text("text"))
            score = score_page(text)
            numeric_tokens = _numeric_token_count(text)
            excluded = _is_explicitly_excluded(text)
            high_signal_unselected = (
                index not in selected
                and not excluded
                and (score >= 15 or (score >= 8 and numeric_tokens >= 20))
            )
            review_candidate, risk_level, miss_reason = _review_signal(
                index=index,
                text=text,
                score=score,
                numeric_tokens=numeric_tokens,
                selected=index in selected,
                excluded=excluded,
                selected_pages=selected,
            )
            rows.append(
                {
                    "page": index + 1,
                    "selected": index in selected,
                    "score": score,
                    "numeric_tokens": numeric_tokens,
                    "excluded": excluded,
                    "high_signal_unselected": high_signal_unselected,
                    "review_candidate": review_candidate,
                    "risk_level": risk_level,
                    "miss_reason": miss_reason,
                    "hits": _hits(text),
                    "preview": _preview(text),
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit selected PDF pages for missed operational/ESG signal.")
    parser.add_argument("pdf")
    parser.add_argument("--page-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    rows = audit(args.pdf, args.page_report)
    with open(args.output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    selected_count = sum(1 for row in rows if row["selected"])
    missed = [row for row in rows if row["high_signal_unselected"]]
    review_candidates = [row for row in rows if row["review_candidate"]]
    print(f"pages: {len(rows)}")
    print(f"selected: {selected_count}")
    print(f"high_signal_unselected: {len(missed)}")
    print(f"borderline_review_candidates: {len(review_candidates)}")
    for row in sorted(missed, key=lambda item: (-item["score"], -item["numeric_tokens"], item["page"]))[: args.top]:
        print(
            f"p{row['page']}: score={row['score']} nums={row['numeric_tokens']} "
            f"hits={row['hits']} :: {row['preview']}"
        )
    if not missed and review_candidates:
        print("borderline candidates to inspect:")
    for row in sorted(
        review_candidates,
        key=lambda item: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(item["risk_level"]), 9),
            -int(item["score"]),
            -int(item["numeric_tokens"]),
            int(item["page"]),
        ),
    )[: args.top]:
        print(
            f"p{row['page']} [{row['risk_level']}:{row['miss_reason']}]: "
            f"score={row['score']} nums={row['numeric_tokens']} "
            f"hits={row['hits']} :: {row['preview']}"
        )


if __name__ == "__main__":
    main()
