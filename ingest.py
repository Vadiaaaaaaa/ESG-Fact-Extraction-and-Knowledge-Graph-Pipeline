import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

BATCH_SIZE = 10
AMAZON_REPORT_PDF = (
    r"C:\Users\Vedika.Sahoo\OneDrive - GlobalData PLC\Desktop"
    r"\Amazon-2025-Annual-Report.pdf"
)


def _build_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = True
    pipeline_options.images_scale = 0.5

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )


def _convert_batch(pdf_path, start_page, end_page, output_path):
    converter = _build_converter()
    result = converter.convert(str(pdf_path), page_range=(start_page, end_page))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.document.export_to_dict(), f, ensure_ascii=False)


def _get_page_count(pdf_path):
    converter = _build_converter()
    result = converter.convert(str(pdf_path), page_range=(1, 1))

    page_count = getattr(getattr(result, "input", None), "page_count", None)
    if page_count is None:
        page_count = getattr(result.document, "num_pages", None)
    if callable(page_count):
        page_count = page_count()

    if page_count is None:
        exported = result.document.export_to_dict()
        page_count = len(exported.get("pages", {}))

    if not page_count:
        raise RuntimeError(f"Could not determine page count for {pdf_path}")

    return int(page_count)


def _ref_target(value):
    if not isinstance(value, str) or not value.startswith("#/"):
        return None

    parts = value[2:].split("/")
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])

    return None


def _rewrite_refs(value, offsets):
    if isinstance(value, dict):
        ref = value.get("$ref")
        target = _ref_target(ref)
        if target is not None:
            collection, index = target
            if collection in offsets:
                value["$ref"] = f"#/{collection}/{index + offsets[collection]}"

        for child_value in value.values():
            _rewrite_refs(child_value, offsets)

    elif isinstance(value, list):
        for item in value:
            _rewrite_refs(item, offsets)

    elif isinstance(value, str):
        target = _ref_target(value)
        if target is not None:
            collection, index = target
            if collection in offsets:
                return f"#/{collection}/{index + offsets[collection]}"

    return value


def _append_collection(combined, batch, collection, offsets):
    for item in batch.get(collection, []):
        item = copy.deepcopy(item)
        _rewrite_refs(item, offsets)

        target = _ref_target(item.get("self_ref"))
        if target is not None:
            item["self_ref"] = f"#/{collection}/{target[1] + offsets[collection]}"

        combined.setdefault(collection, []).append(item)


def _merge_batches(batch_outputs):
    if not batch_outputs:
        return {}

    combined = copy.deepcopy(batch_outputs[0])
    combined["texts"] = []
    combined["tables"] = []
    combined["pictures"] = []
    combined["groups"] = []
    combined["key_value_items"] = []
    combined["form_items"] = []
    combined["pages"] = {}
    combined.setdefault("body", {})["children"] = []

    collections = [
        "texts",
        "tables",
        "pictures",
        "groups",
        "key_value_items",
        "form_items",
    ]

    for batch in batch_outputs:
        offsets = {
            collection: len(combined.get(collection, []))
            for collection in collections
        }

        for collection in collections:
            _append_collection(combined, batch, collection, offsets)

        body_children = copy.deepcopy(batch.get("body", {}).get("children", []))
        _rewrite_refs(body_children, offsets)
        combined["body"]["children"].extend(body_children)

        for page_key, page in batch.get("pages", {}).items():
            combined["pages"][str(page_key)] = copy.deepcopy(page)

    return combined


def process_pdf(pdf_path, output_path):
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    doc_id = str(uuid.uuid4())
    page_count = _get_page_count(pdf_path)
    batch_outputs = []

    with tempfile.TemporaryDirectory(prefix="docling_batches_") as temp_dir:
        temp_dir = Path(temp_dir)

        for start_page in range(1, page_count + 1, BATCH_SIZE):
            end_page = min(start_page + BATCH_SIZE - 1, page_count)
            batch_path = temp_dir / f"batch_{start_page}_{end_page}.json"

            print(f"Processing pages {start_page}-{end_page} of {page_count}...")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--batch",
                    str(pdf_path),
                    str(start_page),
                    str(end_page),
                    str(batch_path),
                ],
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                if completed.stdout:
                    print(completed.stdout)
                if completed.stderr:
                    print(completed.stderr, file=sys.stderr)
                completed.check_returncode()

            with open(batch_path, "r", encoding="utf-8") as f:
                batch = json.load(f)

            batch_outputs.append(batch)
            blocks = (
                len(batch.get("texts", []))
                + len(batch.get("tables", []))
                + len(batch.get("pictures", []))
            )
            print(f"Batch complete: {blocks} blocks extracted")

    combined = _merge_batches(batch_outputs)
    combined["doc_id"] = doc_id
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    print(
        f"Total blocks: {len(combined.get('texts', []))} texts, "
        f"{len(combined.get('tables', []))} tables"
    )


def _print_first_text_blocks(output_path, count=5):
    with open(output_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"\nFirst {count} text blocks:")
    for index, block in enumerate(data.get("texts", [])[:count], start=1):
        print(f"{index}. {block.get('text', '')}")


def _parse_args():
    parser = argparse.ArgumentParser(description="Batch Docling PDF ingestion")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("args", nargs="*")
    return parser.parse_args()


if __name__ == "__main__":
    parsed_args = _parse_args()

    if parsed_args.batch:
        if len(parsed_args.args) != 4:
            raise SystemExit(
                "Batch mode requires: pdf_path start_page end_page output_path"
            )

        batch_pdf_path, batch_start, batch_end, batch_output_path = parsed_args.args
        _convert_batch(
            batch_pdf_path,
            int(batch_start),
            int(batch_end),
            batch_output_path,
        )
    else:
        output = Path(__file__).with_name("amazon_merged_output.json")
        process_pdf(AMAZON_REPORT_PDF, output)
        _print_first_text_blocks(output)
