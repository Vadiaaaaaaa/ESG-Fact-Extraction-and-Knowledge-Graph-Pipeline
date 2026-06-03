import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

DEFAULT_METADATA = {
    "company_name": "",
    "ticker": "",
    "filing_type": "",
    "filing_year": None,
    "fiscal_year_end_month": "",
    "primary_period": "",
    "prior_period": "",
    "has_segments": False,
    "currency": "USD",
    "reporting_scale": "not_stated",
    "reporting_scale_factor": None,
    "metadata_confidence": "low",
}

LEGAL_SUFFIX_PATTERN = (
    r"S\.A\.|N\.V\.|Inc\.?|Corp\.?|Corporation|LLC|PLC|plc|Ltd\.?|Limited|AG|SE"
)
CURRENCY_ALIASES = {
    "USD": [r"\bUSD\b", r"\bUS\$\b", r"\$"],
    "CHF": [r"\bCHF\b", r"\bSwiss francs?\b"],
    "EUR": [r"\bEUR\b", r"\beuros?\b", r"Ã¢â€šÂ¬"],
    "GBP": [r"\bGBP\b", r"\bpounds?\s+sterling\b", r"Ã‚Â£"],
    "JPY": [r"\bJPY\b", r"\byen\b", r"Ã‚Â¥"],
    "CNY": [r"\bCNY\b", r"\bRMB\b", r"\byuan\b"],
}
COMPANY_TOKEN_RE = r"[A-ZÀ-ÖØ-Ý][\wÀ-ÖØ-öø-ÿ&'\.\-]*"


def _cell_text(cell: dict[str, Any]) -> str:
    return " ".join(str(cell.get("text", "")).split())


def _table_text(table: dict[str, Any]) -> str:
    data = table.get("data") or {}
    cells = data.get("table_cells")
    if isinstance(cells, list):
        return " ".join(_cell_text(cell) for cell in cells)
    return str(table.get("text") or "")


def _section_text(section: dict[str, Any]) -> str:
    parts = [
        str(section.get("section_title") or ""),
        str(section.get("parent_section") or ""),
        str(section.get("content") or ""),
    ]
    parts.extend(str(block) for block in section.get("text_blocks", []))
    parts.extend(_table_text(table) for table in section.get("tables", []))
    return " ".join(part for part in parts if part).strip()


def _section_heading_text(section: dict[str, Any]) -> str:
    parts = [str(section.get("section_title") or "")]
    parts.extend(str(block) for block in section.get("text_blocks", [])[:8])
    return " ".join(part for part in parts if part).strip()


def _normalize_company_name(value: str) -> str:
    name = " ".join(value.split())
    name = re.sub(r"^(?:the\s+)?registrant\s*[:\-]\s*", "", name, flags=re.IGNORECASE)
    legal_tail = re.search(rf"((?:The\s+)?(?:{COMPANY_TOKEN_RE}\s+){{0,5}}(?:{LEGAL_SUFFIX_PATTERN}))$", name)
    if legal_tail:
        name = legal_tail.group(1)
    name = re.sub(r"\s+", " ", name).strip(" ,;:-")
    if re.fullmatch(rf"(?:{LEGAL_SUFFIX_PATTERN})", name):
        return ""
    return name


def _company_candidates_from_text(text: str) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    patterns = [
        (
            re.compile(
                rf"\b((?:The\s+)?(?:{COMPANY_TOKEN_RE}\s+){{0,5}}(?:{LEGAL_SUFFIX_PATTERN}))\s*[-|]\s*(?:Annual Report|Annual Review|Financial Statements)\s+(20\d{{2}})\b"
            ),
            12,
        ),
        (
            re.compile(
                rf"\b((?:The\s+)?(?:{COMPANY_TOKEN_RE}\s+){{0,5}}(?:{LEGAL_SUFFIX_PATTERN}))\b"
            ),
            8,
        ),
        (
            re.compile(
                rf"\b((?:The\s+)?(?:{COMPANY_TOKEN_RE}\s+){{0,5}}Company)\s*[-|]?\s*(?:Annual Report|Annual Review|Financial Statements)?\b"
            ),
            7,
        ),
        (
            re.compile(
                rf"\b((?:{COMPANY_TOKEN_RE}\s+){{0,4}}{COMPANY_TOKEN_RE})\s*[-|]\s*(?:Annual Report|Annual Review)\s+(20\d{{2}})\b"
            ),
            10,
        ),
    ]

    for pattern, score in patterns:
        for match in pattern.finditer(text):
            raw_name = match.group(1)
            name = _normalize_company_name(raw_name)
            if not name:
                continue
            if re.search(r"\b(Annual|Review|Report|Statements|Contents|Chairman|CEO|Financial)\b", name):
                continue
            candidates.append((name, score))

    return candidates


def _is_generic_company_name(value: str) -> bool:
    normalized = " ".join(value.split()).strip(" ,;:-")
    generic_names = {
        "The Company",
        "Company",
        "The Group",
        "Group",
    }
    return (
        not normalized
        or normalized in generic_names
        or "Globally Managed Businesses" in normalized
    )


def _extract_company_name(sections: list[dict[str, Any]]) -> tuple[str, bool]:
    heading_text = " ".join(_section_heading_text(section) for section in sections[:5])
    full_text = " ".join(_section_text(section) for section in sections[:10])
    prioritized_texts = [heading_text, full_text]

    prioritized_patterns = [
        re.compile(
            rf"\bFinancial\s+Statements\s+of\s+((?:The\s+)?(?:{COMPANY_TOKEN_RE}\s+){{0,5}}(?:{LEGAL_SUFFIX_PATTERN}))(?=[^\w]|$)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"\b((?:The\s+)?(?:{COMPANY_TOKEN_RE}\s+){{0,5}}(?:{LEGAL_SUFFIX_PATTERN}))\s+and\s+its\s+subsidiaries\b",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"\b((?:The\s+)?(?:{COMPANY_TOKEN_RE}\s+){{0,5}})(?:\s+Group)\s+(20\d{{2}})\b",
            flags=re.IGNORECASE,
        ),
    ]

    for prioritized_text in prioritized_texts:
        for pattern in prioritized_patterns:
            for match in pattern.finditer(prioritized_text):
                company_name = _normalize_company_name(match.group(1))
                if _is_generic_company_name(company_name):
                    continue

                if not re.search(rf"\b(?:{LEGAL_SUFFIX_PATTERN}|Company)\b", company_name):
                    legal_pattern = re.compile(
                        rf"({re.escape(company_name)}(?:\s+(?:{LEGAL_SUFFIX_PATTERN})))(?=[^\w]|$)"
                    )
                    legal_match = legal_pattern.search(full_text)
                    if legal_match:
                        company_name = _normalize_company_name(legal_match.group(1))

                if _is_generic_company_name(company_name):
                    continue

                return company_name, True

    weighted_counts: Counter[str] = Counter()
    for text, boost in ((heading_text, 3), (full_text, 1)):
        for candidate, score in _company_candidates_from_text(text):
            if _is_generic_company_name(candidate):
                continue
            weighted_counts[candidate] += score * boost

    if not weighted_counts:
        return "", False

    company_name, score = weighted_counts.most_common(1)[0]
    if _is_generic_company_name(company_name):
        return "", False
    if not re.search(rf"\b(?:{LEGAL_SUFFIX_PATTERN}|Company)\b", company_name):
        legal_pattern = re.compile(
            rf"({re.escape(company_name)}(?:\s+(?:{LEGAL_SUFFIX_PATTERN})))(?=[^\w]|$)"
        )
        legal_match = legal_pattern.search(full_text)
        if legal_match:
            company_name = _normalize_company_name(legal_match.group(1))
    return company_name, score >= 20


def _extract_filing_type(text: str) -> str:
    match = re.search(r"\bFORM\s+(10-K|10-Q)\b", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()

    if re.search(r"\bAnnual\s+(?:Report|Review)\b", text, flags=re.IGNORECASE):
        return "annual_report"

    return ""


def _extract_filing_year(sections: list[dict[str, Any]]) -> tuple[int | None, bool]:
    early_text = " ".join(_section_heading_text(section) for section in sections[:3])
    patterns = [
        r"\bAnnual\s+(?:Report|Review)\s+(20\d{2})\b",
        r"\bFinancial\s+Statements\s+(20\d{2})\b",
        r"\bFor\s+the\s+year\s+ended\s+[A-Za-z]+\s+\d{1,2},\s+(20\d{2})\b",
        r"\bYear\s+ended\s+[A-Za-z]+\s+\d{1,2},\s+(20\d{2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, early_text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1)), True

    return None, False


def _extract_fiscal_date(text: str) -> tuple[str, int | None]:
    month_pattern = "|".join(MONTHS)
    patterns = [
        rf"\bfiscal\s+year\s+ended\s+({month_pattern})\s+\d{{1,2}},\s+(\d{{4}})",
        rf"\byear\s+ended\s+({month_pattern})\s+\d{{1,2}},\s+(\d{{4}})",
        rf"\bfor\s+the\s+year\s+ended\s+({month_pattern})\s+\d{{1,2}},\s+(\d{{4}})",
        rf"\bYear\s+Ended\s+({month_pattern})\s+\d{{1,2}},?\s*(\d{{4}})?",
    ]

    for pattern in patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        dated_matches = [
            (match.group(1), int(match.group(2)))
            for match in matches
            if len(match.groups()) >= 2 and match.group(2)
        ]
        if dated_matches:
            month, year = max(dated_matches, key=lambda item: item[1])
            return month.capitalize(), year

    date_matches = re.findall(
        rf"\b({month_pattern})\s+\d{{1,2}},\s+(20\d{{2}}|19\d{{2}})\b",
        text,
        flags=re.IGNORECASE,
    )
    if date_matches:
        month, year = max(date_matches, key=lambda item: int(item[1]))
        return month.capitalize(), int(year)

    return "", None


def _extract_fiscal_year_end_month(sections: list[dict[str, Any]]) -> tuple[str, bool]:
    text = " ".join(_section_text(section) for section in sections[:10])
    month_pattern = "|".join(MONTHS)
    patterns = [
        rf"\b(?:for\s+the\s+)?year\s+ended\s+({month_pattern})\s+\d{{1,2}}(?:,\s+\d{{4}})?",
        rf"\bas\s+of\s+({month_pattern})\s+(2[89]|3[01])(?:,\s+\d{{4}})?",
        rf"\bat\s+({month_pattern})\s+(2[89]|3[01]),\s+\d{{4}}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).capitalize(), True

    return "December", False


def _extract_quarter(text: str) -> str:
    quarter_match = re.search(
        r"\bquarterly\s+period\s+ended\s+"
        r"(" + "|".join(MONTHS) + r")\s+\d{1,2},\s+(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if not quarter_match:
        return ""

    month = quarter_match.group(1).lower()
    if month in {"january", "february", "march"}:
        return "Q1"
    if month in {"april", "may", "june"}:
        return "Q2"
    if month in {"july", "august", "september"}:
        return "Q3"
    return "Q4"


def _extract_ticker(text: str) -> str:
    patterns = [
        r"\bTrading Symbol[s]?\b[^\n.]{0,120}?\b([A-Z]{1,6})\b",
        r"\b(?:ticker|symbol)\s*(?::|is|of|under)?\s*['\"]?([A-Z0-9]{2,8})['\"]?\b",
        r"\bsymbol\s+['\"]([A-Z]{1,6})['\"]?",
        r"\bsymbol\s+([A-Z]{2,6})\b",
        r"\b(?:Nasdaq|NYSE)[^\n.]{0,160}?\b(?:symbol|ticker)\s+['\"]?([A-Z]{1,6})['\"]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            ticker = match.group(1).upper()
            if len(ticker) > 1 and ticker not in {"THE", "AND", "FOR", "INC", "CORP", "NYSE", "NASDAQ", "NAME"}:
                return ticker
    return ""


def _count_currency_mentions(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for currency, patterns in CURRENCY_ALIASES.items():
        for pattern in patterns:
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            if pattern == r"\$":
                matches = [
                    match
                    for match in re.finditer(pattern, text)
                    if not re.match(r"[A-Z]", text[max(0, match.start() - 1):match.start()])
                ]
            counts[currency] += len(matches)
    return counts


def _extract_currency(sections: list[dict[str, Any]]) -> tuple[str, bool]:
    table_counts: Counter[str] = Counter()
    first_ten_sections = sections[:10]
    for section in first_ten_sections:
        for table in section.get("tables", []):
            table_counts.update(_count_currency_mentions(_table_text(table)))

    non_usd_counts = {
        currency: count
        for currency, count in table_counts.items()
        if currency != "USD" and count > 3
    }
    if non_usd_counts:
        currency = max(non_usd_counts, key=non_usd_counts.get)
        return currency, True

    text_counts = _count_currency_mentions(" ".join(_section_text(section) for section in first_ten_sections))
    non_usd_text_counts = {
        currency: count
        for currency, count in text_counts.items()
        if currency != "USD" and count > 3
    }
    if non_usd_text_counts:
        currency = max(non_usd_text_counts, key=non_usd_text_counts.get)
        return currency, True

    if text_counts.get("USD", 0) > 0 or table_counts.get("USD", 0) > 0:
        return "USD", True

    return "USD", False


def _extract_reporting_scale(sections: list[dict[str, Any]]) -> tuple[str, int | None]:
    first_ten_text = " ".join(_section_text(section) for section in sections[:10])
    patterns = [
        (r"\bin\s+billions?\s+of\b", "billions", 1_000_000_000),
        (r"\b(?:CHF|USD|EUR|GBP|JPY|CNY)\s+billions?\b", "billions", 1_000_000_000),
        (r"\bin\s+millions?\s+of\b", "millions", 1_000_000),
        (r"\b(?:CHF|USD|EUR|GBP|JPY|CNY)\s+millions?\b", "millions", 1_000_000),
    ]
    for pattern, scale_name, scale_factor in patterns:
        if re.search(pattern, first_ten_text, flags=re.IGNORECASE):
            return scale_name, scale_factor
    return "not_stated", None


def extract_filing_metadata(sections: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = dict(DEFAULT_METADATA)
    first_three_text = " ".join(_section_text(section) for section in sections[:3])
    first_five_text = " ".join(_section_text(section) for section in sections[:5])
    first_ten_text = " ".join(_section_text(section) for section in sections[:10])

    company_name, company_confident = _extract_company_name(sections)
    filing_type = _extract_filing_type(first_three_text) or _extract_filing_type(first_ten_text)
    filing_year, filing_year_confident = _extract_filing_year(sections)
    fiscal_month, explicit_fiscal_month = _extract_fiscal_year_end_month(sections)
    ticker = _extract_ticker(first_three_text) or _extract_ticker(first_ten_text)
    currency, currency_confident = _extract_currency(sections)
    reporting_scale, reporting_scale_factor = _extract_reporting_scale(sections)
    has_segments = len(re.findall(r"\bsegments?\b", first_five_text, flags=re.IGNORECASE)) > 3

    metadata["company_name"] = company_name
    metadata["ticker"] = ticker
    metadata["filing_type"] = filing_type
    metadata["filing_year"] = filing_year
    metadata["fiscal_year_end_month"] = fiscal_month
    metadata["primary_period"] = f"FY{filing_year}" if filing_year else ""
    metadata["prior_period"] = f"FY{filing_year - 1}" if filing_year else ""
    metadata["has_segments"] = has_segments
    metadata["currency"] = currency
    metadata["reporting_scale"] = reporting_scale
    metadata["reporting_scale_factor"] = reporting_scale_factor

    if filing_type == "10-Q":
        quarter = _extract_quarter(first_three_text) or _extract_quarter(first_ten_text)
        if quarter and filing_year:
            metadata["primary_period"] = f"{filing_year}{quarter}"

    metadata["metadata_confidence"] = (
        "high"
        if company_confident and currency_confident and filing_year_confident
        else "low"
    )

    return metadata


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract filing metadata from sections JSON")
    parser.add_argument(
        "--input",
        default=str(Path(__file__).with_name("sections_output.json")),
        help="Input sections JSON path",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output metadata JSON path",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    with open(input_path, "r", encoding="utf-8") as f:
        sections = json.load(f)

    metadata = extract_filing_metadata(sections)

    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"Saved to {output_path}")

    print(json.dumps(metadata, indent=2))

