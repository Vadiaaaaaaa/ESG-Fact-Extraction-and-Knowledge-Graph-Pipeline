from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_COMPANIES = {
    "tata_consumer": {
        "pass1": Path("workspace_test_outputs/tata_consumer_pass1_edc.json"),
        "pass2": Path("workspace_test_outputs/tata_consumer_pass2.json"),
        "chunks": Path("workspace_test_outputs/tata_consumer_fast_chunks.json"),
    },
    "gcpl": {
        "pass1": Path("workspace_test_outputs/gcpl_pass1_edc.json"),
        "pass2": Path("workspace_test_outputs/gcpl_pass2.json"),
        "chunks": Path("workspace_test_outputs/gcpl_fast_chunks.json"),
    },
    "nestle_india": {
        "pass1": Path("workspace_test_outputs/nestle_india_pass1_edc.json"),
        "pass2": Path("workspace_test_outputs/nestle_india_pass2.json"),
        "chunks": Path("workspace_test_outputs/nestle_india_fast_chunks.json"),
    },
    "itc": {
        "pass1": Path("workspace_test_outputs/itc_pass1_edc.json"),
        "pass2": Path("workspace_test_outputs/itc_pass2.json"),
        "chunks": Path("workspace_test_outputs/itc_fast_chunks.json"),
    },
}


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_fact_list(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, dict):
        facts = payload.get("facts", [])
    else:
        facts = payload
    return [fact for fact in facts if isinstance(fact, dict)]


def _build_pass1_lookup(path: Path) -> dict[str, dict[str, Any]]:
    return {
        str(fact.get("fact_id") or ""): fact
        for fact in _load_fact_list(path)
        if str(fact.get("fact_id") or "")
    }


def _build_chunk_lookup(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path)
    chunks = payload.get("chunks", payload) if isinstance(payload, dict) else payload
    return {
        str(chunk.get("chunk_id") or ""): chunk
        for chunk in chunks
        if isinstance(chunk, dict) and str(chunk.get("chunk_id") or "")
    }


def _present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _fill_provenance(
    fact: dict[str, Any],
    pass1_lookup: dict[str, dict[str, Any]],
    chunk_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(fact)
    pass1_fact = pass1_lookup.get(str(updated.get("fact_id") or ""), {})
    raw = updated.get("raw") if isinstance(updated.get("raw"), dict) else {}
    chunk_id = (
        str(updated.get("chunk_id") or "")
        or str(pass1_fact.get("chunk_id") or "")
        or str(raw.get("chunk_id") or "")
    )
    if chunk_id:
        updated["chunk_id"] = chunk_id

    section_id = (
        str(updated.get("section_id") or "")
        or str(pass1_fact.get("section_id") or "")
    )
    doc_id = (
        str(updated.get("doc_id") or "")
        or str(pass1_fact.get("doc_id") or "")
    )

    chunk = chunk_lookup.get(chunk_id, {})
    if not section_id:
        section_id = str(chunk.get("section_id") or "")
    if not doc_id:
        doc_id = str(chunk.get("doc_id") or "")

    updated["section_id"] = section_id
    updated["doc_id"] = doc_id
    return updated


def check_company(name: str, paths: dict[str, Path], *, apply: bool = False) -> dict[str, Any]:
    pass1_lookup = _build_pass1_lookup(paths["pass1"])
    chunk_lookup = _build_chunk_lookup(paths["chunks"])
    facts = _load_fact_list(paths["pass2"])

    updated_facts = [_fill_provenance(fact, pass1_lookup, chunk_lookup) for fact in facts]

    missing = [
        str(fact.get("fact_id") or "")
        for fact in updated_facts
        if not (_present(fact.get("chunk_id")) and _present(fact.get("section_id")) and _present(fact.get("doc_id")))
    ]

    report = {
        "company": name,
        "total_facts": len(updated_facts),
        "chunk_id_present": sum(1 for fact in updated_facts if _present(fact.get("chunk_id"))),
        "section_id_present": sum(1 for fact in updated_facts if _present(fact.get("section_id"))),
        "doc_id_present": sum(1 for fact in updated_facts if _present(fact.get("doc_id"))),
        "missing_fact_ids": missing,
    }

    if apply:
        with open(paths["pass2"], "w", encoding="utf-8") as handle:
            json.dump(updated_facts, handle, ensure_ascii=False, indent=2)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify chunk_id, section_id, and doc_id in Pass 2 outputs.")
    parser.add_argument("--apply", action="store_true", help="Write backfilled provenance fields to the Pass 2 files.")
    args = parser.parse_args()

    all_reports = [
        check_company(name, paths, apply=args.apply)
        for name, paths in DEFAULT_COMPANIES.items()
    ]

    print("provenance field check")
    for report in all_reports:
        print(
            f"{report['company']}: total={report['total_facts']} "
            f"chunk_id={report['chunk_id_present']} "
            f"section_id={report['section_id_present']} "
            f"doc_id={report['doc_id_present']}"
        )
        if report["missing_fact_ids"]:
            print(f"  missing: {', '.join(report['missing_fact_ids'][:10])}")


if __name__ == "__main__":
    main()
