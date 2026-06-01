import argparse
import json
import re
from pathlib import Path
from typing import Any

from models import Chunk, Section, TemporalContext


MAX_WORDS_PER_CHUNK = 180
SHORT_SECTION_WORDS = 200
OVERLAP_WORDS = 40
MIN_TOKEN_ESTIMATE = 20
FILING_YEAR = 2025
HISTORICAL_YEAR_THRESHOLD = 5
EXPLICIT_REPRINT_PATTERNS = [
    r"\breprinted from\b",
    r"\boriginally published\b",
    r"\boriginally written\b",
    r"\bas published in\b",
    r"\bthe following\b.*?\bwas\b.*?\bpublished\b",
    r"\bfrom our\s+\d{4}\s+annual report\b",
    r"\boriginal\s+\d{4}\s+.*?\bletter\s+follows\b",
]
SELECTED_FINANCIAL_DATA_PATTERNS = [
    "selected financial data",
    "five year summary",
    "ten year summary",
    "historical financial",
]
SHAREHOLDER_LETTER_RE = re.compile(
    r"\b(?:dear shareholders|to our shareholders)\s*:",
    re.IGNORECASE,
)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "section"


def _token_estimate(content: str) -> int:
    return max(1, (len(content) + 3) // 4) if content else 0


def _chunk_record(
    section: Section,
    chunk_number: int,
    chunk_type: str,
    content: str,
    is_historical_reprint: bool,
) -> Chunk:
    section_title = section.section_title
    return Chunk(
        doc_id=section.doc_id,
        section_id=section.section_id,
        chunk_id=f"{_slugify(section_title)}_{chunk_number}",
        section_title=section_title,
        parent_section=section.parent_section,
        page_start=section.page_start,
        page_end=section.page_end,
        chunk_type=chunk_type,
        content=content,
        char_count=len(content),
        token_estimate=_token_estimate(content),
        is_historical_reprint=is_historical_reprint,
        temporal_context=TemporalContext(
            filing_year=FILING_YEAR,
            fiscal_year_end="December",
            primary_period=f"FY{FILING_YEAR}",
            prior_period=f"FY{FILING_YEAR - 1}",
            is_historical_reprint=is_historical_reprint,
        ),
    )


def _dedupe_chunk_ids(chunks: list[Chunk]) -> list[Chunk]:
    counts: dict[str, int] = {}
    duplicate_bases = {
        chunk.chunk_id
        for chunk in chunks
        if sum(1 for other in chunks if other.chunk_id == chunk.chunk_id) > 1
    }

    for chunk in chunks:
        base_id = chunk.chunk_id
        if base_id not in duplicate_bases:
            counts[base_id] = counts.get(base_id, 0) + 1
            continue

        parent_slug = _slugify(chunk.parent_section)[:15] or "section"
        candidate = f"{parent_slug}_{base_id}"
        occurrence = counts.get(candidate, 0) + 1
        counts[candidate] = occurrence

        if occurrence > 1:
            candidate = f"{candidate}_{occurrence}"

        chunk.chunk_id = candidate

    return chunks


def _has_historical_year_header(section_title: str, filing_year: int = FILING_YEAR) -> bool:
    years = [
        int(match)
        for match in re.findall(r"\b(19\d{2}|20\d{2})\b", section_title)
    ]
    return any(filing_year - year > HISTORICAL_YEAR_THRESHOLD for year in years)


def _is_selected_financial_data_section(section_title: str) -> bool:
    title = section_title.lower()
    return any(pattern in title for pattern in SELECTED_FINANCIAL_DATA_PATTERNS)


def _is_shareholder_letter_header(section_title: str) -> bool:
    return bool(SHAREHOLDER_LETTER_RE.search(section_title))


def _reprint_split_index(
    content: str,
    split_on_shareholder_letter: bool,
) -> int | None:
    candidates = []

    for pattern in EXPLICIT_REPRINT_PATTERNS:
        match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
        if match:
            candidates.append(match.start())

    if split_on_shareholder_letter:
        for match in SHAREHOLDER_LETTER_RE.finditer(content):
            if match.start() > 0:
                candidates.append(match.start())
                break

    return min(candidates) if candidates else None


def _split_reprint_content(
    content: str,
    split_on_shareholder_letter: bool,
) -> tuple[str, str] | None:
    split_index = _reprint_split_index(content, split_on_shareholder_letter)
    if split_index is None:
        return None

    before = content[:split_index].strip()
    after = content[split_index:].strip()
    if not after:
        return None
    return before, after


def _cell_text(cell: dict[str, Any]) -> str:
    return " ".join(str(cell.get("text", "")).split())


def _table_cells(table: dict[str, Any]) -> list[dict[str, Any]]:
    data = table.get("data") or {}
    cells = data.get("table_cells")
    return cells if isinstance(cells, list) else []


def _build_grid(cells: list[dict[str, Any]]) -> list[list[str]]:
    max_row = max((cell.get("end_row_offset_idx", 0) for cell in cells), default=0)
    max_col = max((cell.get("end_col_offset_idx", 0) for cell in cells), default=0)
    grid = [["" for _ in range(max_col)] for _ in range(max_row)]

    for cell in cells:
        text = _cell_text(cell)
        if not text:
            continue

        start_row = cell.get("start_row_offset_idx", 0)
        end_row = max(start_row + 1, cell.get("end_row_offset_idx", start_row + 1))
        start_col = cell.get("start_col_offset_idx", 0)
        end_col = max(start_col + 1, cell.get("end_col_offset_idx", start_col + 1))

        for row in range(start_row, min(end_row, max_row)):
            for col in range(start_col, min(end_col, max_col)):
                grid[row][col] = text

    return grid


def _header_rows(cells: list[dict[str, Any]]) -> set[int]:
    rows = set()
    for cell in cells:
        if cell.get("column_header"):
            for row in range(
                cell.get("start_row_offset_idx", 0),
                cell.get("end_row_offset_idx", 0),
            ):
                rows.add(row)
    return rows


def _row_header_texts(cells: list[dict[str, Any]], row_index: int) -> list[str]:
    row_labels = []
    for cell in cells:
        if not cell.get("row_header") and not cell.get("row_section"):
            continue
        if cell.get("start_row_offset_idx", 0) <= row_index < cell.get("end_row_offset_idx", 0):
            text = _cell_text(cell)
            if text and text not in row_labels:
                row_labels.append(text)
    return row_labels


def _column_labels(grid: list[list[str]], header_rows: set[int]) -> list[str]:
    if not grid:
        return []

    labels = ["Metric"]
    max_col = len(grid[0])
    for col in range(1, max_col):
        parts = []
        for row_index in sorted(header_rows):
            value = grid[row_index][col].strip()
            if value and value not in parts:
                parts.append(value)

        joined = " ".join(parts)
        year_match = re.search(r"\b(20\d{2}|19\d{2})\b", joined)
        labels.append(year_match.group(1) if year_match else joined or f"Column {col}")

    return labels


def _markdown_escape(value: str) -> str:
    return value.replace("|", "\\|")


def _table_to_text(table: dict[str, Any]) -> str:
    cells = _table_cells(table)
    if not cells:
        if table.get("text"):
            return table["text"]
        if table.get("data") is not None:
            return json.dumps(table["data"], ensure_ascii=False)
        return ""

    grid = _build_grid(cells)
    header_rows = _header_rows(cells)
    column_labels = _column_labels(grid, header_rows)
    if not column_labels:
        return ""

    lines = [
        "| " + " | ".join(_markdown_escape(label) for label in column_labels) + " |",
        "| " + " | ".join("---" for _ in column_labels) + " |",
    ]

    for row_index, row in enumerate(grid):
        if row_index in header_rows:
            continue

        row_values = [value for value in row if value]
        if not row_values:
            continue

        row_label_parts = _row_header_texts(cells, row_index)
        row_label = " ".join(row_label_parts) or row[0] or f"Row {row_index + 1}"
        value_cells = row[1:len(column_labels)]
        if not any(value_cells):
            lines.append(
                "| "
                + " | ".join(
                    [_markdown_escape(row_label)]
                    + ["" for _ in column_labels[1:]]
                )
                + " |"
            )
            continue

        lines.append(
            "| "
            + " | ".join(
                _markdown_escape(value)
                for value in [row_label] + value_cells
            )
            + " |"
        )

    return "\n".join(lines)


def _split_sentences(content: str) -> list[str]:
    content = " ".join(content.split())
    if not content:
        return []

    return re.split(r"(?<=[.!?])\s+", content)


def _word_count(text: str) -> int:
    return len(text.split())


def _overlap_tail(sentences: list[str], target_words: int) -> list[str]:
    if not sentences or target_words <= 0:
        return []

    overlap: list[str] = []
    words = 0
    for sentence in reversed(sentences):
        overlap.insert(0, sentence)
        words += _word_count(sentence)
        if words >= target_words:
            break
    return overlap


def _text_chunks(content: str) -> list[str]:
    sentences = _split_sentences(content)
    if not sentences:
        return []

    chunks = []
    current = []
    current_words = 0

    for sentence in sentences:
        sentence_words = _word_count(sentence)
        if current and current_words + sentence_words > MAX_WORDS_PER_CHUNK:
            chunks.append(" ".join(current))
            current = _overlap_tail(current, OVERLAP_WORDS)
            current_words = sum(_word_count(existing) for existing in current)

        current.append(sentence)
        current_words += sentence_words

    if current:
        chunk = " ".join(current)
        if not chunks or chunk != chunks[-1]:
            chunks.append(chunk)

    return chunks


def chunk_sections(sections: list[dict[str, Any] | Section]) -> list[Chunk]:
    chunks = []
    shareholder_letter_seen = False

    for raw_section in sections:
        section = (
            raw_section
            if isinstance(raw_section, Section)
            else Section.from_dict(raw_section)
        )
        if not section.doc_id or not section.section_id:
            print(
                "Warning: skipping section missing doc_id or section_id: "
                f"{section.section_title}"
            )
            continue
        chunk_number = 1
        content = section.content
        tables = section.tables
        has_tables = bool(tables)
        word_count = len(content.split())
        is_shareholder_section = _is_shareholder_letter_header(section.section_title)
        section_is_historical = (
            _has_historical_year_header(section.section_title)
            or _is_selected_financial_data_section(section.section_title)
            or (is_shareholder_section and shareholder_letter_seen)
        )
        split_on_shareholder_letter = shareholder_letter_seen or is_shareholder_section

        if is_shareholder_section:
            shareholder_letter_seen = True

        if content.strip():
            if word_count < SHORT_SECTION_WORDS and not has_tables:
                text_chunks = [content.strip()]
            else:
                text_chunks = _text_chunks(content)

            for text_chunk in text_chunks:
                if section_is_historical:
                    chunks.append(
                        _chunk_record(
                            section,
                            chunk_number,
                            "text",
                            text_chunk,
                            is_historical_reprint=True,
                        )
                    )
                    chunk_number += 1
                    continue

                split_content = _split_reprint_content(
                    text_chunk,
                    split_on_shareholder_letter=split_on_shareholder_letter,
                )
                if not split_content:
                    chunks.append(
                        _chunk_record(
                            section,
                            chunk_number,
                            "text",
                            text_chunk,
                            is_historical_reprint=False,
                        )
                    )
                    chunk_number += 1
                    continue

                before, after = split_content
                if before:
                    chunks.append(
                        _chunk_record(
                            section,
                            chunk_number,
                            "text",
                            before,
                            is_historical_reprint=False,
                        )
                    )
                    chunk_number += 1

                chunks.append(
                    _chunk_record(
                        section,
                        chunk_number,
                        "text",
                        after,
                        is_historical_reprint=True,
                    )
                )
                chunk_number += 1
                section_is_historical = True

        for table in tables:
            table_text = _table_to_text(table)
            chunks.append(
                _chunk_record(
                    section,
                    chunk_number,
                    "table",
                    table_text,
                    is_historical_reprint=section_is_historical,
                )
            )
            chunk_number += 1

    return _dedupe_chunk_ids(chunks)


def _drop_small_chunks(chunks: list[Chunk]) -> tuple[list[Chunk], int]:
    kept_chunks = [
        chunk for chunk in chunks
        if chunk.token_estimate >= MIN_TOKEN_ESTIMATE
    ]
    return kept_chunks, len(chunks) - len(kept_chunks)


def _print_summary(chunks: list[Chunk], dropped_count: int = 0) -> None:
    text_chunks = [chunk for chunk in chunks if chunk.chunk_type == "text"]
    table_chunks = [chunk for chunk in chunks if chunk.chunk_type == "table"]
    token_counts = [chunk.token_estimate for chunk in chunks]
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0
    largest = max(chunks, key=lambda chunk: chunk.token_estimate, default=None)
    smallest = min(chunks, key=lambda chunk: chunk.token_estimate, default=None)

    print(f"Dropped chunks under {MIN_TOKEN_ESTIMATE} tokens: {dropped_count}")
    print(f"Total chunks: {len(chunks)}")
    print(f"Text chunks: {len(text_chunks)}")
    print(f"Table chunks: {len(table_chunks)}")
    print(f"Avg token estimate: {avg_tokens:.1f}")
    if largest:
        print(
            "Largest chunk: "
            f"{largest.chunk_id} ({largest.token_estimate} tokens)"
        )
    if smallest:
        print(
            "Smallest chunk: "
            f"{smallest.chunk_id} ({smallest.token_estimate} tokens)"
        )


def inspect_chunk(chunk_id: str, input_path: str | Path = "chunks_output.json") -> None:
    path = Path(input_path)
    if not path.is_absolute():
        path = Path(__file__).with_name(str(path))

    with open(path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    matches = [
        Chunk.from_dict(chunk)
        for chunk in chunks
        if chunk.get("chunk_id") == chunk_id
    ]

    if not matches:
        print(f"Chunk not found: {chunk_id}")
        raise SystemExit(1)

    if len(matches) > 1:
        print(f"Found {len(matches)} chunks with id: {chunk_id}")

    for index, chunk in enumerate(matches, start=1):
        if len(matches) > 1:
            print(f"\n=== Match {index} of {len(matches)} ===")

        page_start = chunk.page_start if chunk.page_start is not None else "unknown"
        page_end = chunk.page_end if chunk.page_end is not None else "unknown"

        print(f"chunk_id: {chunk.chunk_id}")
        print(f"section_title: {chunk.section_title}")
        print(f"parent_section: {chunk.parent_section}")
        print(f"page_range: {page_start} to {page_end}")
        print(f"chunk_type: {chunk.chunk_type}")
        print(f"token_estimate: {chunk.token_estimate}")
        print(
            "is_historical_reprint: "
            f"{chunk.temporal_context.is_historical_reprint}"
        )
        print("\n--- FULL CONTENT START ---")
        print(chunk.content)
        print("--- FULL CONTENT END ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build or inspect report chunks")
    parser.add_argument(
        "--input",
        default=str(Path(__file__).with_name("sections_output.json")),
        help="Input sections JSON path",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("chunks_output.json")),
        help="Output chunks JSON path",
    )
    parser.add_argument(
        "--inspect",
        metavar="CHUNK_ID",
        help="Print full details and content for a chunk id from the input JSON",
    )
    args = parser.parse_args()

    if args.inspect:
        inspect_chunk(args.inspect, input_path=args.input)
        raise SystemExit(0)

    input_path = Path(args.input)
    with open(input_path, "r", encoding="utf-8") as f:
        sections = json.load(f)

    chunks = chunk_sections(sections)
    chunks, dropped_count = _drop_small_chunks(chunks)

    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([chunk.to_dict() for chunk in chunks], f, indent=2, ensure_ascii=False)

    print(f"Saved to {output_path}")
    _print_summary(chunks, dropped_count)
