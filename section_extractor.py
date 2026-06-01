import argparse
import json
import re
from pathlib import Path
from typing import Any

from models import Section


SECTION_KEYWORDS = [
    "item 1",
    "item 2",
    "item 3",
    "item 4",
    "item 5",
    "item 6",
    "item 7",
    "item 8",
    "item 9",
    "item 10",
    "item 1a",
    "item 1b",
    "item 7a",
    "business",
    "risk factor",
    "properties",
    "legal proceeding",
    "market for",
    "management",
    "financial statement",
    "notes to",
    "controls and procedure",
    "executive officer",
    "dear shareholder",
    "consolidated statement",
    "consolidated balance",
    "liquidity",
    "capital resource",
    "critical accounting",
    "quantitative",
    "selected financial",
    "segment result",
    "overview",
    "outlook",
    "1997 letter",
]

SHORT_HEADER_FINANCIAL_KEYWORDS = [
    "revenue",
    "income",
    "cash",
    "earnings",
    "profit",
    "loss",
    "assets",
    "equity",
]


def _load_docling_json(docling_json: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(docling_json, (str, Path)):
        with open(docling_json, "r", encoding="utf-8") as f:
            return json.load(f)

    return docling_json


def _parse_ref(ref: str) -> tuple[str | None, int | None]:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None, None

    parts = ref[2:].split("/")
    if len(parts) != 2 or not parts[1].isdigit():
        return None, None

    return parts[0], int(parts[1])


def _resolve_ref(docling_json: dict[str, Any], ref: str) -> tuple[str | None, dict[str, Any] | None]:
    collection, index = _parse_ref(ref)
    if collection not in {"texts", "tables", "groups"}:
        return None, None

    blocks = docling_json.get(collection, [])
    if index >= len(blocks):
        return None, None

    return collection, blocks[index]


def _iter_body_blocks(docling_json: dict[str, Any], refs: list[dict[str, str]]):
    for ref_item in refs:
        collection, block = _resolve_ref(docling_json, ref_item.get("$ref"))
        if block is None:
            continue

        if collection == "groups":
            yield from _iter_body_blocks(docling_json, block.get("children", []))
        else:
            yield collection, block


def _first_page_no(block: dict[str, Any]) -> int | None:
    prov = block.get("prov") or []
    if not prov:
        return None

    return prov[0].get("page_no")


def _finalize_section(section: dict[str, Any] | None) -> Section | None:
    if section is None:
        return None

    return Section(
        section_title=section["section_title"],
        parent_section=section["parent_section"],
        page_start=section["page_start"],
        page_end=section.pop("_last_page", section["page_start"]),
        doc_id=section["doc_id"],
        section_id=section["section_id"],
        text_blocks=section["text_blocks"],
        tables=section["tables"],
        content="\n".join(section["text_blocks"]),
    )


def _starts_section(block: dict[str, Any]) -> bool:
    if block.get("label") != "section_header":
        return False

    text = block.get("text", "")
    text_lower = text.lower()
    if any(keyword in text_lower for keyword in SECTION_KEYWORDS):
        return True

    words = text.split()
    return (
        len(words) < 6
        and any(keyword in text_lower for keyword in SHORT_HEADER_FINANCIAL_KEYWORDS)
    )


def _is_item_section_title(title: str) -> bool:
    return re.search(r"\bitem\s+\d+[a-z]?\b", title.lower()) is not None


def _append_to_section(section: dict[str, Any], collection: str, block: dict[str, Any]) -> None:
    if collection == "tables" or block.get("label") == "table":
        section["tables"].append(block)
        return

    text = block.get("text")
    if text:
        section["text_blocks"].append(text)


def _collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]

    if isinstance(value, dict):
        strings = []
        for child_value in value.values():
            strings.extend(_collect_strings(child_value))
        return strings

    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_collect_strings(item))
        return strings

    return []


def _table_content(table: dict[str, Any]) -> str:
    chunks = []

    if table.get("text"):
        chunks.append(table["text"])

    data = table.get("data")
    if isinstance(data, dict) and isinstance(data.get("table_cells"), list):
        chunks.extend(
            cell.get("text", "")
            for cell in data["table_cells"]
            if cell.get("text")
        )
    elif data is not None:
        chunks.extend(_collect_strings(data))

    return "\n".join(chunks)


def _section_word_count(section: Section) -> int:
    table_content = "\n".join(
        _table_content(table)
        for table in section.tables
    )
    return len(f"{section.content}\n{table_content}".split())


def _content_preview(section: Section, length: int = 200) -> str:
    content = section.content.strip()
    if not content:
        content = " ".join(
            _table_content(table)
            for table in section.tables
        ).strip()

    return " ".join(content.split())[:length]


def extract_sections(docling_json: dict[str, Any] | str | Path) -> list[Section]:
    docling_json = _load_docling_json(docling_json)
    doc_id = docling_json.get("doc_id")
    if not doc_id:
        raise ValueError("doc_id not found — re-run ingest.py first")

    sections = []
    current_section = None
    current_parent = ""
    section_index = 1

    body_children = docling_json.get("body", {}).get("children", [])
    for collection, block in _iter_body_blocks(docling_json, body_children):
        label = block.get("label")
        page_no = _first_page_no(block)

        if _starts_section(block):
            finalized = _finalize_section(current_section)
            if finalized is not None:
                sections.append(finalized)

            section_title = block.get("text", "")
            is_item_section = _is_item_section_title(section_title)
            current_section = {
                "section_title": section_title,
                "parent_section": "" if is_item_section else current_parent,
                "page_start": page_no,
                "page_end": None,
                "doc_id": doc_id,
                "section_id": f"{doc_id}_s{section_index:03d}",
                "text_blocks": [],
                "tables": [],
                "_last_page": page_no,
            }
            section_index += 1
            if is_item_section:
                current_parent = section_title
            continue

        if current_section is None:
            continue

        _append_to_section(current_section, collection, block)

        if page_no is not None:
            current_section["_last_page"] = page_no

    finalized = _finalize_section(current_section)
    if finalized is not None:
        sections.append(finalized)

    return sections


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract sections from Docling JSON")
    parser.add_argument(
        "--input",
        default=str(Path(__file__).with_name("amazon_merged_output.json")),
        help="Input Docling merged JSON path",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("sections_output.json")),
        help="Output sections JSON path",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    docling_json = _load_docling_json(input_path)
    result = extract_sections(docling_json)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([section.to_dict() for section in result], f, indent=2, ensure_ascii=False)

    print(f"Saved to {output_path}")
    print(f"Number of sections found: {len(result)}")
    for section in result:
        word_count = _section_word_count(section)
        preview = _content_preview(section)
        print(
            f"{section.section_title} | "
            f"pages {section.page_start}-{section.page_end} | "
            f"{word_count} words | "
            f"{len(section.tables)} tables | "
            f"{preview}"
        )
