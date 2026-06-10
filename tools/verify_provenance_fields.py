from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


COMPANIES = ("nestle_india", "tata_consumer", "gcpl", "itc")
FIELDS = ("chunk_id", "section_id", "doc_id", "prev_chunk_id", "next_chunk_id")


def _load_facts(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        facts = payload.get("facts", [])
    else:
        facts = payload
    return [fact for fact in facts if isinstance(fact, dict)]


def _candidate_paths(company: str, root: Path) -> list[Path]:
    names = [
        f"{company}_pass2_rerun.json",
        f"{company}_pass2.json",
    ]
    return [root / "workspace_test_outputs" / name for name in names] + [root / name for name in names]


def _resolve_input(company: str, root: Path) -> Path | None:
    for path in _candidate_paths(company, root):
        if path.exists():
            return path
    return None


def _field_present(fact: dict[str, Any], field: str) -> bool:
    return field in fact


def verify_company(path: Path) -> dict[str, Any]:
    facts = _load_facts(path)
    counts = {field: 0 for field in FIELDS}
    for fact in facts:
        for field in FIELDS:
            if _field_present(fact, field):
                counts[field] += 1
    total = len(facts)
    verdict = "PASS" if all(count == total for count in counts.values()) else "FAIL"
    return {"total": total, "counts": counts, "verdict": verdict}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify provenance fields on available Pass 2 outputs.")
    parser.add_argument("--root", default=".", help="Workspace root containing Pass 2 outputs.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    any_fail = False
    for company in COMPANIES:
        path = _resolve_input(company, root)
        if path is None:
            print(f"{company}: SKIP (no Pass 2 output found)")
            continue
        result = verify_company(path)
        print(f"{company}: {path}")
        total = result["total"]
        for field in FIELDS:
            count = result["counts"][field]
            status = "PASS" if count == total else "FAIL"
            print(f"  {field} present: {count} / {total} ({status})")
        print(f"  overall verdict: {result['verdict']}")
        any_fail = any_fail or result["verdict"] == "FAIL"
    raise SystemExit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
