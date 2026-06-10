from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_ROOT / 'pipeline'), str(_ROOT), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

"""
Registry gap analysis: queries Neo4j for new_metric observations,
clusters by semantic similarity, and suggests registry additions.
"""

import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NEO4J_URI  = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "Watermelon@123"

SIMILARITY_THRESHOLD = 0.85   # cosine threshold for same cluster
ALIAS_SCORE_MIN      = 0.75   # suggest as alias
REVIEW_SCORE_MIN     = 0.50   # flag for manual review

OUT_DIR = _ROOT / "workspace_test_outputs"
OUT_CSV   = OUT_DIR / "registry_gap_report.csv"
OUT_JSON  = OUT_DIR / "registry_gap_aliases.json"

# ---------------------------------------------------------------------------
# Step 1 — Query Neo4j
# ---------------------------------------------------------------------------

CYPHER = """
MATCH (o:Observation)-[:REPORTED_BY]->(c:Company),
      (o)-[:IN_PERIOD]->(p:Period)
WHERE o.normalization_status = 'new_metric'
RETURN o.raw_name          AS raw_name,
       o.normalised_value   AS normalised_value,
       o.normalised_unit_symbol AS unit,
       c.company_id         AS company_id,
       p.fiscal_year        AS fiscal_year,
       count(*)             AS frequency
ORDER BY frequency DESC
"""


def query_new_metrics(driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(CYPHER)
        rows = []
        for rec in result:
            rows.append({
                "raw_name":   str(rec["raw_name"] or "").strip().lower(),
                "company_id": rec["company_id"],
                "fiscal_year": rec["fiscal_year"],
                "frequency":  int(rec["frequency"]),
            })
    return rows


# ---------------------------------------------------------------------------
# Step 2 — Cluster by semantic similarity
# ---------------------------------------------------------------------------

def _embed(names: list[str]):
    try:
        from sentence_transformers import SentenceTransformer
        import torch
        model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        return model.encode(names, normalize_embeddings=True)
    except Exception:
        # Fall back to difflib-based similarity
        return None


def _difflib_sim(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def cluster_names(
    name_data: list[dict],
) -> list[dict]:
    """
    Each item in name_data: {raw_name, companies: set, frequency: int}
    Returns list of cluster dicts: {representative, members, companies, frequency}
    """
    unique: dict[str, dict] = {}
    for row in name_data:
        n = row["raw_name"]
        if not n:
            continue
        if n not in unique:
            unique[n] = {"raw_name": n, "companies": set(), "frequency": 0}
        unique[n]["companies"].add(row["company_id"])
        unique[n]["frequency"] += row["frequency"]

    names = list(unique.keys())
    if not names:
        return []

    embeddings = _embed(names)

    # Greedy clustering
    assigned = {}  # name -> cluster_id
    clusters: list[dict] = []

    for i, name in enumerate(names):
        if name in assigned:
            continue
        cluster_members = [name]
        for j, other in enumerate(names):
            if i == j or other in assigned:
                continue
            if embeddings is not None:
                import numpy as np
                sim = float(np.dot(embeddings[i], embeddings[j]))
            else:
                sim = _difflib_sim(name, other)
            if sim >= SIMILARITY_THRESHOLD:
                cluster_members.append(other)
        # Pick representative = highest frequency member
        rep = max(cluster_members, key=lambda n: unique[n]["frequency"])
        cluster_companies: set[str] = set()
        cluster_freq = 0
        for m in cluster_members:
            assigned[m] = len(clusters)
            cluster_companies |= unique[m]["companies"]
            cluster_freq += unique[m]["frequency"]
        clusters.append({
            "cluster_id": f"c{len(clusters):04d}",
            "representative": rep,
            "members": cluster_members,
            "companies": cluster_companies,
            "frequency": cluster_freq,
        })

    return clusters


# ---------------------------------------------------------------------------
# Step 3+4 — Match against existing canonicals
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict]:
    from metric_registry_seed import REGISTRY as SEED_REGISTRY
    registry = list(SEED_REGISTRY)
    additions_path = _ROOT / "registry" / "registry_additions_approved.json"
    if additions_path.exists():
        additions = json.loads(additions_path.read_text(encoding="utf-8"))
        if isinstance(additions, list):
            registry.extend(additions)
    return registry


def _load_existing_aliases() -> dict[str, str]:
    aliases_path = _ROOT / "registry" / "registry_aliases.json"
    if aliases_path.exists():
        return json.loads(aliases_path.read_text(encoding="utf-8"))
    return {}


def _score_against_registry(raw_name: str, registry: list[dict]) -> tuple[str, float]:
    """Return (best_canonical_id, best_score)."""
    try:
        from gold_set import compute_match_score
        fact_proxy = {"raw_name": raw_name, "metric_core": raw_name,
                      "metric_definition": "", "raw_unit": "", "fact_class": ""}
        best_id, best_score = "", 0.0
        for canonical in registry:
            score = compute_match_score(fact_proxy, canonical)
            if score > best_score:
                best_score = score
                best_id = canonical.get("canonical_id", "")
        return best_id, best_score
    except Exception:
        # Fallback: simple difflib against canonical_id tokens
        from difflib import SequenceMatcher
        best_id, best_score = "", 0.0
        for canonical in registry:
            cid = str(canonical.get("canonical_id", "")).replace("_", " ")
            score = SequenceMatcher(None, raw_name, cid).ratio()
            if score > best_score:
                best_score = score
                best_id = canonical.get("canonical_id", "")
        return best_id, best_score


def _action(score: float) -> str:
    if score >= ALIAS_SCORE_MIN:
        return "add_alias"
    if score >= REVIEW_SCORE_MIN:
        return "review"
    return "add_new_canonical"


# ---------------------------------------------------------------------------
# Step 5 — Build outputs
# ---------------------------------------------------------------------------

def build_outputs(clusters: list[dict], registry: list[dict], existing_aliases: dict) -> tuple[list[dict], dict]:
    rows = []
    alias_suggestions: dict[str, str] = {}

    for cluster in clusters:
        rep = cluster["representative"]
        canonical_id, score = _score_against_registry(rep, registry)
        action = _action(score)
        cross_company = len(cluster["companies"]) > 1

        rows.append({
            "cluster_id":         cluster["cluster_id"],
            "representative_name": rep,
            "member_count":       len(cluster["members"]),
            "companies":          "|".join(sorted(cluster["companies"])),
            "frequency":          cluster["frequency"],
            "cross_company":      cross_company,
            "suggested_canonical": canonical_id,
            "match_score":        round(score, 4),
            "action":             action,
        })

        if action == "add_alias":
            for member in cluster["members"]:
                if member not in existing_aliases:
                    alias_suggestions[member] = canonical_id

    # Sort: cross-company first, then by frequency desc
    rows.sort(key=lambda r: (0 if r["cross_company"] else 1, -r["frequency"]))
    return rows, alias_suggestions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Connecting to Neo4j...", flush=True)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    print("Step 1: Querying new_metric observations...", flush=True)
    rows = query_new_metrics(driver)
    driver.close()

    total_obs = sum(r["frequency"] for r in rows)
    unique_names = len({r["raw_name"] for r in rows})
    print(f"  Found {total_obs} new_metric observations, {unique_names} unique raw_names", flush=True)

    if not rows:
        print("No new_metric observations found. Exiting.")
        return

    print("Step 2: Clustering by semantic similarity...", flush=True)
    clusters = cluster_names(rows)
    cross_company_clusters = [c for c in clusters if len(c["companies"]) > 1]
    print(f"  {len(clusters)} clusters, {len(cross_company_clusters)} cross-company", flush=True)

    print("Step 3+4: Loading registry and scoring clusters...", flush=True)
    registry = _load_registry()
    existing_aliases = _load_existing_aliases()
    print(f"  Registry: {len(registry)} canonicals, {len(existing_aliases)} existing aliases", flush=True)

    report_rows, alias_suggestions = build_outputs(clusters, registry, existing_aliases)

    # Counts by action
    action_counts = defaultdict(int)
    for r in report_rows:
        action_counts[r["action"]] += 1

    print("Step 5: Writing output files...", flush=True)

    # CSV report
    csv_fields = [
        "cluster_id", "representative_name", "member_count", "companies",
        "frequency", "cross_company", "suggested_canonical", "match_score", "action",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(report_rows)
    print(f"  Wrote {OUT_CSV}", flush=True)

    # Alias JSON
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(alias_suggestions, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {OUT_JSON}", flush=True)

    # Step 6 — Summary
    print("\n" + "=" * 60)
    print("REGISTRY GAP ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"  Total new_metric observations : {total_obs}")
    print(f"  Unique raw_names              : {unique_names}")
    print(f"  Clusters found                : {len(clusters)}")
    print(f"  Cross-company clusters        : {len(cross_company_clusters)}")
    print(f"  High confidence aliases       : {action_counts['add_alias']} (score > {ALIAS_SCORE_MIN})")
    print(f"  Manual review needed          : {action_counts['review']} (score {REVIEW_SCORE_MIN}-{ALIAS_SCORE_MIN})")
    print(f"  Genuinely new metrics         : {action_counts['add_new_canonical']} (score < {REVIEW_SCORE_MIN})")
    print()
    print(f"  Top 20 clusters by frequency:")
    print(f"  {'Representative':<45} {'Companies':<30} {'Freq':>5}  {'Suggested Canonical':<35} {'Score':>6}  {'Action'}")
    print(f"  {'-'*45} {'-'*30} {'-'*5}  {'-'*35} {'-'*6}  {'-'*18}")
    for r in report_rows[:20]:
        print(
            f"  {r['representative_name']:<45} "
            f"{r['companies']:<30} "
            f"{r['frequency']:>5}  "
            f"{r['suggested_canonical']:<35} "
            f"{r['match_score']:>6.3f}  "
            f"{r['action']}"
        )
    print("=" * 60)


if __name__ == "__main__":
    main()
