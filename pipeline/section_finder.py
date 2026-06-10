from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


import argparse
import json
from functools import lru_cache
import re
from pathlib import Path
from typing import Any

import fitz

from metric_registry_seed import REGISTRY as SEED_REGISTRY


TARGET_PATTERNS = [
    "key performance",
    "kpi",
    "management discussion",
    "md&a",
    "mda",
    "operational performance",
    "operations review",
    "environment",
    "sustainability",
    "esg",
    "good and green",
    "greener",
    "brsr",
    "business responsibility",
    "business responsibility and sustainability",
    "business responsibility report",
    "principle-wise performance",
    "principle wise performance",
    "principle-wise disclosure",
    "section c",
    "sustainability report",
    "supply chain",
    "manufacturing",
    "board’s report",
    "board’s report",
    "directors report",
    "director’s report",
    "annual report on csr",
    "corporate social responsibility",
    "societal initiatives",
    "people initiatives",
    "empowering and engaging",
    "long lasting partnerships",
    "responsible sourcing",
    "conservation of energy",
    "financial highlights",
    "performance highlights",
    "value creation",
    "principle 6",
    "principle 3",
    "principle 8",
    "principle 1",
    "integrated report",
    "responsible business",
    "gri index",
    "gri standards",
    "non-financial",
    "esg performance",
    "climate",
    "carbon neutral",
    "emission",
    "water steward",
    "energy manag",
    "circularity",
    "waste manag",
    "materiality",
    "stakeholder",
]

DEFAULT_REGISTRY_PATH = str(_ROOT / "registry" / "consumer_master_registry_v1.json")
SUPPLEMENTAL_REGISTRY_PATH = str(_ROOT / "registry" / "registry_additions_approved.json")


def _normalize_space(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _norm_heading(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _iter_pages(doc: fitz.Document) -> list[dict[str, Any]]:
    pages = []
    for index, page in enumerate(doc):
        pages.append({"index": index, "text": _normalize_space(page.get_text("text"))})
    return pages


def _term_hits(text: str, term: str) -> int:
    lower = text.lower()
    term_lower = term.lower()
    if " " in term_lower or "&" in term_lower:
        return lower.count(term_lower)
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(term_lower)}(?![a-z0-9])", lower))


def _canonical_keyword_weight(term: str) -> int:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return 0
    if re.search(r"\d|/|%", normalized) or normalized.count(" ") >= 2:
        return 3
    if normalized.count(" ") == 1 or len(normalized) >= 12:
        return 2
    return 1


def _normalize_registry_keyword(value: Any) -> str:
    keyword = str(value or "").replace("_", " ").strip().lower()
    keyword = re.sub(r"\s+", " ", keyword)
    return keyword


def _load_registry_entries(registry_path: str | Path | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    path = Path(registry_path) if registry_path else Path(DEFAULT_REGISTRY_PATH)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            entries.extend(item for item in payload if isinstance(item, dict))
    else:
        entries.extend(item for item in SEED_REGISTRY if isinstance(item, dict))

    supplemental = Path(SUPPLEMENTAL_REGISTRY_PATH)
    if (registry_path is None or path.name != supplemental.name) and supplemental.exists():
        payload = json.loads(supplemental.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            entries.extend(item for item in payload if isinstance(item, dict))
    return entries


@lru_cache(maxsize=4)
def get_registry_keywords(registry_path: str | None = None) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for entry in _load_registry_entries(registry_path):
        raw_candidates = [
            entry.get("display_name"),
            entry.get("canonical_id"),
            *(entry.get("aliases") or []),
        ]
        for candidate in raw_candidates:
            keyword = _normalize_registry_keyword(candidate)
            if len(keyword) < 3 or keyword in seen:
                continue
            seen.add(keyword)
            keywords.append(keyword)
    keywords.sort(key=lambda value: (-_canonical_keyword_weight(value), -len(value), value))
    return keywords


@lru_cache(maxsize=4)
def get_registry_keyword_weights(registry_path: str | None = None) -> dict[str, int]:
    return {
        keyword: _canonical_keyword_weight(keyword)
        for keyword in get_registry_keywords(registry_path)
    }


def score_page(text: str, registry_path: str | Path | None = None) -> int:
    return sum(
        _term_hits(text, keyword) * weight
        for keyword, weight in get_registry_keyword_weights(str(registry_path) if registry_path else None).items()
    )


def _operational_keyword_count(text: str, registry_path: str | Path | None = None) -> int:
    return sum(
        _term_hits(text, keyword)
        for keyword in get_registry_keywords(str(registry_path) if registry_path else None)
    )


def _numeric_token_count(text: str) -> int:
    return len(
        re.findall(
            r"\b\d[\d,]*(?:\.\d+)?%?\b|%|\b(?:tonnes?|tons?|tco2e|co2e|kl|kilolitres?|gj|gigajoules?|mw|megawatts?|crore|lakhs?|million|billion)\b",
            text,
            flags=re.I,
        )
    )


def _looks_like_board_bio(text: str) -> bool:
    first_chunk = text[:1200]
    first_lower = first_chunk.lower()
    if (
        re.search(r"\bDIN\s*:\s*\d+", first_chunk)
        and re.search(r"\b(non[-\s]?executive|chairman|director|committee|board)\b", first_lower)
    ):
        return True
    words = text.split()[:100]
    if _numeric_token_count(" ".join(words)) > 0:
        return False
    first_text = " ".join(words)
    proper_name_count = len(
        re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b", first_text)
    )
    paragraphs = [p for p in re.split(r"\n+", text.strip()) if p.strip()]
    avg_words = (sum(len(p.split()) for p in paragraphs) / len(paragraphs)) if paragraphs else 999
    return proper_name_count > 3 and avg_words < 55


def _looks_like_auditor_report(text: str) -> bool:
    lower = text.lower()
    return any(
        phrase in lower
        for phrase in ("to the members of", "we have audited", "independent auditor")
    )


def _looks_like_legal_notice(text: str) -> bool:
    lower = text.lower()
    if any(
        phrase in lower[:1200]
        for phrase in ("notice of annual general meeting", "notice of the annual general meeting")
    ):
        return True
    if not any(
        phrase in lower
        for phrase in ("notice is hereby given", "pursuant to section", "companies act")
    ):
        return False
    return _operational_keyword_count(text) < 5


def _looks_like_pure_financial_statement(text: str) -> bool:
    tokens = re.findall(r"\S+", text)
    if not tokens:
        return False
    numeric_tokens = sum(1 for token in tokens if re.search(r"\d", token))
    return (numeric_tokens / len(tokens)) > 0.80 and _operational_keyword_count(text) < 5


def _looks_like_financial_statement_notes(text: str) -> bool:
    first_lower = re.sub(r"\s+", " ", text[:1600]).lower()
    if not re.search(
        r"\bnotes\s+(?:to\s+(?:the\s+)?(?:consolidated\s+|standalone\s+)?|"
        r"forming\s+part\s+of\s+(?:the\s+)?)financial\s+statements\b",
        first_lower,
    ):
        return False
    return _operational_keyword_count(text) < 25


def _looks_like_exhibit_index(text: str) -> bool:
    lower = text.lower()
    if lower.count("incorporated by reference") >= 2:
        return True
    first_lower = lower[:1600]
    exhibit_numbers = len(re.findall(r"\b(?:exhibit\s+)?\d{1,2}\.\d{1,2}\b", first_lower))
    return "exhibit" in first_lower and exhibit_numbers >= 5


def _looks_like_reference_index(text: str) -> bool:
    first_lower = re.sub(r"\s+", " ", text[:1800]).lower()
    return "disclosure reference" in first_lower and "gri" in first_lower


def _looks_like_director_certificate(text: str) -> bool:
    first_lower = re.sub(r"\s+", " ", text[:1600]).lower()
    return (
        "certificate of non-disqualification of directors" in first_lower
        or "non-disqualification of directors" in first_lower
    )


def _is_explicitly_excluded(text: str) -> bool:
    return (
        _looks_like_board_bio(text)
        or _looks_like_auditor_report(text)
        or _looks_like_legal_notice(text)
        or _looks_like_pure_financial_statement(text)
        or _looks_like_financial_statement_notes(text)
        or _looks_like_exhibit_index(text)
        or _looks_like_reference_index(text)
        or _looks_like_director_certificate(text)
    )


def _looks_like_target_title(title: str) -> bool:
    norm = _norm_heading(title)
    return any(_norm_heading(pattern) in norm for pattern in TARGET_PATTERNS)


def _page_looks_like_toc_text(text: str) -> bool:
    compact_hits = len(re.findall(r"\b\d{1,4}\.\s+\S+", _normalize_space(text)))
    line_hits = len(_toc_pairs_from_page(text))
    lower = text.lower()
    return (
        compact_hits >= 5
        or line_hits >= 5
        or ("annual report" in lower and "content" in lower and compact_hits >= 3)
    )


def _find_heading_page(pages: list[dict[str, Any]], title: str, printed_index: int) -> int | None:
    norm_title = _norm_heading(title)
    if len(norm_title) < 5:
        return None

    search_ranges = [
        range(max(0, printed_index - 25), min(len(pages), printed_index + 35)),
        range(0, min(len(pages), 80)),
        range(0, len(pages)),
    ]
    words = norm_title.split()
    title_prefix = " ".join(words[: min(8, len(words))])
    for page_range in search_ranges:
        for index in page_range:
            if index < 15 and _page_looks_like_toc_text(pages[index]["text"]):
                continue
            page_norm = _norm_heading(pages[index]["text"][:2500])
            if norm_title and norm_title in page_norm:
                return index
            if len(title_prefix) >= 8 and title_prefix in page_norm:
                return index
    return None


def _toc_from_bookmarks(doc: fitz.Document) -> list[dict[str, Any]]:
    entries = []
    for level, title, page_number in doc.get_toc() or []:
        title = _normalize_space(str(title or ""))
        title_lower = title.lower()
        if (
            not title
            or not page_number
            or int(page_number) < 1
            or title.startswith("_")
            or title_lower.startswith("ashow")
        ):
            continue
        entries.append(
            {
                "level": int(level),
                "title": title,
                "pdf_index": max(0, min(len(doc) - 1, int(page_number) - 1)),
                "printed_page": int(page_number),
                "source": "bookmark",
            }
        )
    return entries


TOC_LINE_RE = re.compile(
    r"^\s*(?P<title>.{3,120}?)(?:\.{2,}|\s{2,}|\s+\-+\s+|\s+)(?P<page>\d{1,4})\s*$"
)


def _toc_pairs_from_page(text: str) -> list[tuple[str, int]]:
    pairs = []
    for raw_line in text.splitlines():
        line = _normalize_space(raw_line)
        match = TOC_LINE_RE.match(line)
        if not match:
            continue
        title = _normalize_space(match.group("title").strip(".- "))
        if len(title.split()) > 16 or len(title) < 3:
            continue
        pairs.append((title, int(match.group("page"))))
    return pairs


COMPACT_TOC_ENTRY_RE = re.compile(
    r"(?P<page>\d{1,4})\.\s+(?P<title>.*?)(?=\s+\d{1,4}\.\s+|$)"
)


def _compact_toc_pairs_from_page(text: str) -> list[tuple[str, int]]:
    normalized = _normalize_space(text)
    pairs = []
    for match in COMPACT_TOC_ENTRY_RE.finditer(normalized):
        title = _normalize_space(match.group("title").strip(".- "))
        page = int(match.group("page"))
        if not title or len(title) < 3 or len(title.split()) > 18:
            continue
        title_lower = title.lower()
        if title_lower in {"annual report", "content", "contents"}:
            continue
        pairs.append((title, page))
    return pairs


def _toc_from_text(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_pairs: list[tuple[str, int]] = []
    for page in pages[:15]:
        pairs = [
            (title, printed_page)
            for title, printed_page in (
                _toc_pairs_from_page(page["text"])
                + _compact_toc_pairs_from_page(page["text"])
            )
            if 1 <= printed_page <= len(pages) + 20
        ]
        if len(pairs) >= 5:
            raw_pairs.extend(pairs)
    if len(raw_pairs) < 5:
        return []

    entries = []
    offsets = []
    for title, printed_page in raw_pairs:
        printed_index = max(0, printed_page - 1)
        found_index = _find_heading_page(pages, title, printed_index)
        if found_index is not None:
            offsets.append(found_index - printed_index)
        entries.append(
            {
                "level": 1,
                "title": title,
                "pdf_index": printed_index,
                "printed_page": printed_page,
                "source": "text_toc",
            }
        )

    offset = 0
    if offsets:
        offsets.sort()
        offset = offsets[len(offsets) // 2]

    for entry in entries:
        corrected = int(entry["printed_page"]) - 1 + offset
        entry["pdf_index"] = max(0, min(len(pages) - 1, corrected))
    return entries


def _dedupe_toc(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for entry in sorted(entries, key=lambda item: (item["pdf_index"], item["level"], item["title"].lower())):
        key = (_norm_heading(entry["title"]), entry["pdf_index"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _select_from_toc(entries: list[dict[str, Any]], page_count: int) -> tuple[list[int], list[str]]:
    selected: set[int] = set()
    sections_found = []
    entries = _dedupe_toc(entries)
    for idx, entry in enumerate(entries):
        if not _looks_like_target_title(entry["title"]):
            continue
        start = max(0, int(entry["pdf_index"]) - 1)
        next_start = page_count
        for next_entry in entries[idx + 1 :]:
            candidate_start = int(next_entry["pdf_index"])
            if candidate_start > int(entry["pdf_index"]):
                next_start = candidate_start
                break
        end = max(start, next_start - 1)
        selected.update(range(start, min(page_count, end + 1)))
        sections_found.append(entry["title"])
    return sorted(selected), sections_found


def _select_by_keyword(pages: list[dict[str, Any]], page_count: int, keyword_threshold: int = 3) -> tuple[list[int], int]:
    scored = [
        (page["index"], score_page(page["text"]), page["text"])
        for page in pages
    ]
    threshold = keyword_threshold
    selected = [
        index
        for index, score, text in scored
        if score >= threshold and not _is_explicitly_excluded(text)
    ]
    if page_count > 50 and len(selected) < 8:
        existing = set(selected)
        for index, _score, _text in sorted(scored, key=lambda item: (-item[1], item[0])):
            existing.add(index)
            if len(existing) >= 8:
                break
        selected = sorted(existing)
    return sorted(set(selected)), threshold


def _expand_for_low_density(
    selected_pages: list[int],
    pages: list[dict[str, Any]],
    warnings: list[str],
) -> list[int]:
    selected = set(selected_pages)
    numeric_density = sum(_numeric_token_count(pages[index]["text"]) for index in selected)
    if numeric_density >= 50 or not pages:
        return sorted(selected)

    warnings.append(
        f"Selected pages had low numeric density ({numeric_density} tokens); added 5 highest-scoring unselected pages."
    )
    for page in sorted(pages, key=lambda item: (-score_page(item["text"]), item["index"])):
        if page["index"] in selected:
            continue
        selected.add(page["index"])
        if len(selected) >= len(selected_pages) + 5:
            break
    return sorted(selected)


def _augment_toc_selection_with_high_signal_pages(
    selected_pages: list[int],
    pages: list[dict[str, Any]],
    warnings: list[str],
) -> list[int]:
    selected = set(selected_pages)
    additions = [
        page["index"]
        for page in pages
        if page["index"] not in selected
        and score_page(page["text"]) >= 15
        and not _is_explicitly_excluded(page["text"])
    ]
    if additions:
        selected.update(additions)
        warnings.append(
            f"TOC selection augmented with {len(additions)} high-scoring unselected page(s)."
        )
    return sorted(selected)


ISOLATED_OPERATIONAL_FACT_RE = re.compile(
    r"\b("
    r"plant\s+locations?|plants?\s+are\s+located|manpower\s+figure|"
    r"manufacturing\s+locations?|factory\s+locations?|"
    r"ninth\s+factory|9th\s+factory|"
    r"sustainability\s+spend|sustainable\s+operations"
    r")\b",
    re.I,
)


def _augment_with_isolated_operational_facts(
    selected_pages: list[int],
    pages: list[dict[str, Any]],
    warnings: list[str],
) -> list[int]:
    selected = set(selected_pages)
    additions = []
    for page in pages:
        if page["index"] in selected or _is_explicitly_excluded(page["text"]):
            continue
        text = page["text"]
        score = score_page(text)
        if ISOLATED_OPERATIONAL_FACT_RE.search(text) or (
            score >= 10
            and _numeric_token_count(text) >= 5
            and re.search(r"\b(sustainability|factory|plant|operations|supply chain|logistics)\b", text, re.I)
        ):
            additions.append(page["index"])
    if additions:
        selected.update(additions)
        warnings.append(
            f"Selection augmented with {len(additions)} isolated operational fact page(s)."
        )
    return sorted(selected)


GAP_FILL_THRESHOLD = 5    # reduced from 10; keeps scattered keyword pages from bridging into large blocks
BUFFER_PAGES = 2          # reduced from 3; applied only to non-heuristic pages (see find_operational_sections)

_HEURISTIC_GAP_FILL_THRESHOLD = 10   # original values kept for structurally-anchored BRSR heuristic pages
_HEURISTIC_BUFFER_PAGES = 3


def _apply_gap_fill(selected_pages: list[int], page_count: int, threshold: int = GAP_FILL_THRESHOLD) -> list[int]:
    """Fill gaps of up to `threshold` pages between consecutive selected pages."""
    if len(selected_pages) < 2:
        return selected_pages
    filled: set[int] = set(selected_pages)
    sorted_pages = sorted(selected_pages)
    for prev_page, next_page in zip(sorted_pages, sorted_pages[1:]):
        if 0 < (next_page - prev_page) <= threshold:
            filled.update(range(prev_page, next_page + 1))
    return sorted(filled)


def _apply_buffer(selected_pages: list[int], page_count: int, buf: int = BUFFER_PAGES) -> list[int]:
    """Add `buf` pages before and after each selected page."""
    buffered: set[int] = set()
    for page in selected_pages:
        for offset in range(-buf, buf + 1):
            candidate = page + offset
            if 0 <= candidate < page_count:
                buffered.add(candidate)
    return sorted(buffered)


_BRSR_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:business\s+responsibility\s+(?:and\s+sustainability\s+)?report|"
    r"brsr\b|"
    r"section\s+c\s*[:\-–]|"
    r"principle[-\s]wise\s+(?:performance|disclosure))",
    re.I,
)


def _apply_brsr_range_heuristic(
    pages: list[dict[str, Any]],
    selected_pages: list[int],
    warnings: list[str],
    max_range: int = 70,
    min_score: int = 1,
) -> list[int]:
    """
    Scan for the first page where a BRSR section heading appears in the top half
    of the page (not just a passing in-paragraph mention).  Once found, select
    all pages in the following `max_range` pages that score >= `min_score` on
    any keyword.  Operates only when called — the caller is responsible for only
    invoking this when TOC matching failed.
    """
    _toc_page_number_re = re.compile(r"(?m)^\s*\d{2,3}\s*$")

    start_index: int | None = None
    for page in pages:
        text = page["text"]
        top_half = text[: max(len(text) // 2, 800)]
        if _BRSR_HEADING_RE.search(top_half):
            # Skip TOC pages: they contain the heading as a listing entry surrounded
            # by many standalone page-number tokens (e.g. "231", "295" on their own lines)
            if len(_toc_page_number_re.findall(text)) >= 5:
                continue
            start_index = page["index"]
            break

    if start_index is None:
        warnings.append("BRSR range heuristic: no BRSR heading found in top-half of any page; skipping.")
        return selected_pages

    end_index = min(start_index + max_range, len(pages))
    candidate_range = range(start_index, end_index)
    added: list[int] = []
    selected_set = set(selected_pages)
    for idx in candidate_range:
        if idx in selected_set:
            continue
        page_text = pages[idx]["text"]
        if _is_explicitly_excluded(page_text):
            continue
        if score_page(page_text) >= min_score or _numeric_token_count(page_text) >= 3:
            added.append(idx)

    if added:
        # Report 1-based printed page numbers in the warning so it reads naturally,
        # but the values stored in selected_set are 0-based PDF indices, which is
        # the currency used by every other selector in this file and consumed by
        # fast_pdf_text_ingest.py via: (page["page"] - 1) in selected_page_indexes
        warnings.append(
            f"BRSR range heuristic: added {len(added)} pages "
            f"(PDF 0-based indices {min(added)}–{max(added)}, "
            f"1-based pages {min(added)+1}–{max(added)+1}; "
            f"section heading at 0-based index {start_index}, 1-based page {start_index+1})."
        )
        selected_set.update(added)

    return sorted(selected_set)


def find_operational_sections(pdf_path: str, keyword_threshold: int = 3) -> dict:
    warnings: list[str] = []
    with fitz.open(str(pdf_path)) as doc:
        page_count = len(doc)
        pages = _iter_pages(doc)

        heuristic_pages: set[int] = set()
        if page_count < 60:
            selected_pages = list(range(page_count))
            method = "full_document"
            toc_sections_found = None
            warnings.append("Document has fewer than 60 pages; selected full document.")
        else:
            bookmark_toc = _toc_from_bookmarks(doc)
            text_toc = [] if bookmark_toc else _toc_from_text(pages)
            toc_entries = bookmark_toc or text_toc
            selected_pages, toc_sections = _select_from_toc(toc_entries, page_count) if toc_entries else ([], [])
            if selected_pages:
                method = "toc"
                toc_sections_found = toc_sections
                selected_pages = _augment_toc_selection_with_high_signal_pages(
                    selected_pages,
                    pages,
                    warnings,
                )
            else:
                toc_failed = bool(toc_entries)
                if toc_entries:
                    warnings.append("TOC was found but no target sections matched; falling back to keyword scoring.")
                selected_pages, threshold = _select_by_keyword(pages, page_count, keyword_threshold=keyword_threshold)
                method = "keyword"
                toc_sections_found = None
                if len(selected_pages) < 5 and page_count > 60:
                    warnings.append("Section finding returned fewer than 5 pages on a long document; selected full document.")
                    selected_pages = list(range(page_count))
                    method = "full_document"
                elif toc_failed:
                    _pre_heuristic = set(selected_pages)
                    selected_pages = _apply_brsr_range_heuristic(pages, selected_pages, warnings)
                    heuristic_pages = set(selected_pages) - _pre_heuristic

        selected_pages = _expand_for_low_density(selected_pages, pages, warnings)
        selected_pages = _augment_with_isolated_operational_facts(
            selected_pages,
            pages,
            warnings,
        )
        if method != "full_document":
            if heuristic_pages:
                # Non-heuristic pages: reduced thresholds prevent scattered financial pages
                # from bridging into large contiguous blocks.
                non_heuristic = sorted(set(selected_pages) - heuristic_pages)
                non_heuristic = _apply_gap_fill(non_heuristic, page_count)           # uses GAP_FILL_THRESHOLD=5
                non_heuristic = _apply_buffer(non_heuristic, page_count)             # uses BUFFER_PAGES=2
                # Heuristic pages: original thresholds; these are structurally anchored
                # and may have sparse narrative pages between them.
                heuristic_list = sorted(heuristic_pages)
                heuristic_list = _apply_gap_fill(heuristic_list, page_count, threshold=_HEURISTIC_GAP_FILL_THRESHOLD)
                heuristic_list = _apply_buffer(heuristic_list, page_count, buf=_HEURISTIC_BUFFER_PAGES)
                selected_pages = sorted(set(non_heuristic) | set(heuristic_list))
            else:
                selected_pages = _apply_gap_fill(selected_pages, page_count)
                selected_pages = _apply_buffer(selected_pages, page_count)

    return {
        "method": method,
        "selected_pages": selected_pages,
        "page_count": page_count,
        "selected_count": len(selected_pages),
        "toc_sections_found": toc_sections_found,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Find operational/ESG annual-report PDF pages.")
    parser.add_argument("pdf", nargs="+", help="PDF path(s)")
    args = parser.parse_args()
    for pdf in args.pdf:
        result = find_operational_sections(pdf)
        print(json.dumps({"pdf": str(Path(pdf)), **result}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
