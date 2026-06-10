from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


COMPANIES = ("nestle_india", "tata_consumer", "gcpl", "itc")


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


def verify_company(path: Path) -> dict[str, Any]:
    facts = _load_facts(path)
    total = len(facts)
    present = 0
    null_by_confidence = {"failed": 0, "needs_context": 0, "exact_but_null": 0, "inferred_but_null": 0}
    for fact in facts:
        confidence = str(fact.get("normalisation_confidence") or "").lower()
        value = fact.get("normalised_value")
        if value is not None:
            present += 1
            continue
        if confidence == "failed":
            null_by_confidence["failed"] += 1
        elif confidence == "needs_context":
            null_by_confidence["needs_context"] += 1
        elif confidence == "exact":
            null_by_confidence["exact_but_null"] += 1
        elif confidence == "inferred":
            null_by_confidence["inferred_but_null"] += 1

    verdict = "PASS" if null_by_confidence["exact_but_null"] == 0 and null_by_confidence["inferred_but_null"] == 0 else "FAIL"
    return {
        "total": total,
        "present": present,
        "null_by_confidence": null_by_confidence,
        "verdict": verdict,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify authoritative normalized value fields on available Pass 2 outputs.")
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
        print(f"  total facts: {result['total']}")
        print(f"  normalised_value present: {result['present']}")
        print("  normalised_value null - by confidence level:")
        print(f"    failed: {result['null_by_confidence']['failed']}")
        print(f"    needs_context: {result['null_by_confidence']['needs_context']}")
        print(f"    exact but null (ERROR): {result['null_by_confidence']['exact_but_null']}")
        print(f"    inferred but null (ERROR): {result['null_by_confidence']['inferred_but_null']}")
        print(f"  verdict: {result['verdict']}")
        any_fail = any_fail or result["verdict"] == "FAIL"
    raise SystemExit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
