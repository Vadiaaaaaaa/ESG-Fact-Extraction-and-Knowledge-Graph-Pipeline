from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_ROOT / 'pipeline'), str(_ROOT / 'registry'), str(_HERE)]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import re

from definitions import text_vector


@dataclass
class ProvisionalRecord:
    provisional_id: str
    raw_name: str
    metric_core: str
    owner_company: str
    unit_family: str
    metric_subject: str
    metric_role: str
    source_file: str
    low_confidence: bool = False


TOKEN_RE = re.compile(r"[a-z0-9]+")
GENERIC_TOKENS = {
    "count",
    "rate",
    "share",
    "total",
    "value",
    "metric",
    "amount",
    "number",
    "coverage",
    "intensity",
    "growth",
    "business",
}


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        parent = self.parent.setdefault(item, item)
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _default_input_paths(workdir: Path) -> list[Path]:
    candidates = [
        workdir / "workspace_test_outputs" / "tata_consumer_new_metric_distance_audit_applied.csv",
        workdir / "workspace_test_outputs" / "gcpl_new_metric_distance_audit_v2.csv",
        workdir / "workspace_test_outputs" / "nestle_india_new_metric_distance_audit_v2.csv",
        workdir / "workspace_test_outputs" / "itc_new_metric_distance_audit_applied.csv",
    ]
    return [path for path in candidates if path.exists()]


def _company_from_filename(path: Path) -> str:
    name = path.name.lower()
    if name.startswith("tata_consumer"):
        return "Tata Consumer"
    if name.startswith("gcpl"):
        return "GCPL"
    if name.startswith("nestle_india"):
        return "Nestle India"
    if name.startswith("itc"):
        return "ITC"
    return path.stem


def load_provisionals(paths: list[Path]) -> list[ProvisionalRecord]:
    records: list[ProvisionalRecord] = []
    for path in paths:
        company = _company_from_filename(path)
        with open(path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader, start=1):
                provisional_id = str(row.get("fact_id") or "").strip()
                if not provisional_id:
                    provisional_id = f"{company}:{path.stem}:{index}"
                records.append(
                    ProvisionalRecord(
                        provisional_id=provisional_id,
                        raw_name=str(row.get("raw_name") or ""),
                        metric_core=str(row.get("metric_core") or ""),
                        owner_company=company,
                        unit_family=str(row.get("fact_unit_family") or row.get("unit_family") or ""),
                        metric_subject=str(row.get("fact_metric_subject_draft") or row.get("metric_subject") or ""),
                        metric_role=str(row.get("fact_metric_role_draft") or row.get("metric_role") or ""),
                        source_file=str(path),
                        low_confidence=not (
                            str(row.get("fact_metric_subject_draft") or row.get("metric_subject") or "").strip()
                            and str(row.get("fact_metric_role_draft") or row.get("metric_role") or "").strip()
                        ),
                    )
                )
    return records


def _pair_similarity(left: ProvisionalRecord, right: ProvisionalRecord) -> float:
    core_similarity = _vector_similarity(left.metric_core, right.metric_core)
    name_similarity = _vector_similarity(left.raw_name, right.raw_name)
    return max(core_similarity, name_similarity)


_VECTOR_CACHE: dict[str, np.ndarray] = {}


def _vector_similarity(left: str, right: str) -> float:
    left_vector = _VECTOR_CACHE.setdefault(left, text_vector(left))
    right_vector = _VECTOR_CACHE.setdefault(right, text_vector(right))
    if not np.any(left_vector) or not np.any(right_vector):
        return 0.0
    score = float(np.dot(left_vector, right_vector))
    return max(0.0, min(1.0, score))


def cluster_provisionals(records: list[ProvisionalRecord], threshold: float) -> tuple[list[dict[str, Any]], dict[str, int]]:
    uf = UnionFind()
    for record in records:
        uf.add(record.provisional_id)

    pair_scores: dict[tuple[str, str], float] = {}
    token_cache = {
        record.provisional_id: _tokens_for_record(record)
        for record in records
    }
    by_id = {record.provisional_id: record for record in records}
    candidate_pairs: set[tuple[str, str]] = set()

    exact_core_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    token_index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record in records:
        exact_core_groups[(record.unit_family or "unknown", record.metric_core)].append(record.provisional_id)
        for token in token_cache[record.provisional_id] - GENERIC_TOKENS:
            token_index[(record.unit_family or "unknown", token)].append(record.provisional_id)

    for ids in exact_core_groups.values():
        if len(ids) < 2:
            continue
        for left_id, right_id in combinations(sorted(set(ids)), 2):
            candidate_pairs.add((left_id, right_id))

    for ids in token_index.values():
        unique_ids = sorted(set(ids))
        if len(unique_ids) < 2:
            continue
        for left_id, right_id in combinations(unique_ids, 2):
            candidate_pairs.add((left_id, right_id))

    for left_id, right_id in sorted(candidate_pairs):
        left = by_id[left_id]
        right = by_id[right_id]
        if left.owner_company == right.owner_company:
            continue
        if left.unit_family and right.unit_family and left.unit_family != right.unit_family:
            continue
        typed_match = bool(left.metric_subject and right.metric_subject and left.metric_role and right.metric_role)
        if typed_match and left.metric_subject != right.metric_subject:
            continue
        if typed_match and left.metric_role != right.metric_role:
            continue
        if left.metric_core == right.metric_core and left.metric_core:
            similarity = 1.0
        else:
            overlap = token_cache[left.provisional_id] & token_cache[right.provisional_id]
            meaningful_overlap = overlap - GENERIC_TOKENS
            if not meaningful_overlap:
                continue
            jaccard = _token_jaccard(token_cache[left.provisional_id], token_cache[right.provisional_id])
            if typed_match and jaccard < 0.2:
                continue
            if not typed_match and (len(meaningful_overlap) < 2 or jaccard < 0.5):
                continue
            similarity = _pair_similarity(left, right)
            if not typed_match and similarity < max(threshold, 0.90):
                continue
        if similarity < threshold:
            continue
        pair_scores[(left.provisional_id, right.provisional_id)] = similarity
        uf.union(left.provisional_id, right.provisional_id)

    grouped: dict[str, list[ProvisionalRecord]] = defaultdict(list)
    for record in records:
        grouped[uf.find(record.provisional_id)].append(record)

    recurrence_counts: dict[str, int] = {}
    report_rows: list[dict[str, Any]] = []

    for cluster_index, members in enumerate(grouped.values(), start=1):
        companies = sorted({member.owner_company for member in members})
        recurrence_count = len(companies)
        canonical_record = _pick_canonical_provisional(members)
        cluster_id = f"cluster_{cluster_index:03d}"
        for member in members:
            recurrence_counts[member.provisional_id] = recurrence_count

        similarity_values = []
        member_ids = {member.provisional_id for member in members}
        for (left_id, right_id), score in pair_scores.items():
            if left_id in member_ids and right_id in member_ids:
                similarity_values.append(f"{left_id}<->{right_id}:{score:.3f}")

        report_rows.append(
            {
                "cluster_id": cluster_id,
                "metric_cores": " | ".join(sorted({member.metric_core for member in members if member.metric_core})),
                "companies": " | ".join(companies),
                "recurrence_count": recurrence_count,
                "similarity_scores": " | ".join(similarity_values),
                "unit_family": canonical_record.unit_family,
                "recommended_action": (
                    "promote" if recurrence_count >= 3 else "watch" if recurrence_count == 2 else "keep_provisional"
                ),
                "canonical_provisional_id": canonical_record.provisional_id,
                "canonical_metric_core": canonical_record.metric_core,
                "low_confidence": any(member.low_confidence for member in members),
            }
        )

    return report_rows, recurrence_counts


def _tokens_for_record(record: ProvisionalRecord) -> set[str]:
    text = f"{record.metric_core} {record.raw_name}".lower()
    return {_normalize_token(token) for token in TOKEN_RE.findall(text)}


def _normalize_token(token: str) -> str:
    token = token.strip().lower()
    if len(token) > 4 and token.endswith("s"):
        token = token[:-1]
    return token


def _token_jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    union = len(left | right)
    if union == 0:
        return 0.0
    return intersection / union


def _pick_canonical_provisional(records: list[ProvisionalRecord]) -> ProvisionalRecord:
    core_counts = Counter(record.metric_core for record in records if record.metric_core)
    if core_counts:
        most_common_core = core_counts.most_common(1)[0][0]
        same_core = [record for record in records if record.metric_core == most_common_core]
        return max(same_core, key=lambda record: (len(record.metric_core), len(record.raw_name)))
    return max(records, key=lambda record: (len(record.metric_core), len(record.raw_name)))


def write_report(report_rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "cluster_id",
        "metric_cores",
        "companies",
        "recurrence_count",
        "similarity_scores",
        "unit_family",
        "recommended_action",
        "canonical_provisional_id",
        "canonical_metric_core",
        "low_confidence",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in report_rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster provisional metrics across companies.")
    parser.add_argument("--inputs", nargs="*", help="CSV audit files to cluster.")
    parser.add_argument("--threshold", type=float, default=0.82, help="Cosine similarity threshold.")
    parser.add_argument(
        "--output",
        default="provisional_recurrence_report.csv",
        help="CSV output path for the recurrence report.",
    )
    args = parser.parse_args()

    workdir = Path.cwd()
    inputs = [Path(path) for path in args.inputs] if args.inputs else _default_input_paths(workdir)
    if not inputs:
        raise SystemExit("No provisional audit CSVs found.")

    records = load_provisionals(inputs)
    report_rows, recurrence_counts = cluster_provisionals(records, args.threshold)
    write_report(report_rows, Path(args.output))

    print(f"provisional records loaded: {len(records)}")
    print(f"provisional clusters: {len(report_rows)}")
    print(f"recurrence threshold: {args.threshold:.2f}")
    print(f"records with recurrence_count > 1: {sum(1 for count in recurrence_counts.values() if count > 1)}")


if __name__ == "__main__":
    main()
