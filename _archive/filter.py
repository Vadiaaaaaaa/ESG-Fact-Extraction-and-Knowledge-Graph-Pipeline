import json
import re
from pathlib import Path


SIGNAL_PATTERNS = [
    re.compile(r"\$[\d,]+(?:\.\d+)?"),
    re.compile(r"\d+\.?\d*%"),
    re.compile(r"\d+\s?(billion|million|trillion|B|M|bn|mn)", re.IGNORECASE),
    re.compile(
        r"\b(revenue|profit|income|loss|margin|EBITDA|earnings|cash flow|"
        r"capex|operating|growth|decline|segment|AWS|fiscal|quarter|annual|"
        r"YoY|guidance|forecast)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(Q[1-4]\s?\d{4}|FY\d{4}|fiscal year|\d{4} results)\b", re.IGNORECASE),
]


def _load_docling_json(docling_json):
    if isinstance(docling_json, (str, Path)):
        with open(docling_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        print(f'len(docling_json["texts"]): {len(data["texts"])}')
        return data

    return docling_json


def _signal_count(text):
    return sum(1 for pattern in SIGNAL_PATTERNS if pattern.search(text or ""))


def filter_blocks(docling_json):
    data = _load_docling_json(docling_json)
    texts = data["texts"]
    tables = data["tables"]

    kept_indexes = set()

    for index, block in enumerate(texts):
        if _signal_count(block.get("text", "")) >= 2:
            for context_index in (index - 1, index, index + 1):
                if 0 <= context_index < len(texts):
                    kept_indexes.add(context_index)

    kept_texts = [
        block
        for index, block in enumerate(texts)
        if index in kept_indexes
    ]

    return {
        "kept_texts": kept_texts,
        "all_tables": tables,
        "dropped_count": len(texts) - len(kept_texts),
        "kept_count": len(kept_texts),
        "table_count": len(tables),
    }


if __name__ == "__main__":
    input_path = Path(__file__).with_name("amazon_output.json")
    source_data = _load_docling_json(input_path)

    filtered = filter_blocks(source_data)

    print(f"Total text blocks in document: {len(source_data.get('texts', []))}")
    print(f"Blocks kept after filter: {filtered['kept_count']}")
    print(f"Blocks dropped: {filtered['dropped_count']}")
    print(f"Number of tables: {filtered['table_count']}")
    print("First 3 kept text blocks:")

    for block in filtered["kept_texts"][:3]:
        print(block.get("text", ""))
