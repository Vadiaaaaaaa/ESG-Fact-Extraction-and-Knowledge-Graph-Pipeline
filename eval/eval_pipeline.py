"""
Eval runner — measures pipeline precision/recall against the gold set.

For each gold fact it searches Neo4j for a matching Observation on nestle_india
in the target period, then checks:
  - Value match   : within 1% relative tolerance (or exact for zero/small values)
  - Unit match    : normalised_unit_symbol matches expected (with aliases)
  - Period match  : IN_PERIOD fiscal_year contains expected period token
  - Canonical match: OF_METRIC canonical_id matches expected_canonical (if set)

Outputs a scorecard and a per-fact detail table.
"""

import sys
from pathlib import Path
from neo4j import GraphDatabase, READ_ACCESS

sys.path.insert(0, str(Path(__file__).parent))
from eval_gold_set import GOLD_FACTS, GOLD_SUMMARY

NEO4J_URI  = "neo4j://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "Watermelon@123"
COMPANY_ID = "nestle_india"

# Unit aliases: expected_unit → set of acceptable normalised_unit_symbol values
UNIT_ALIASES = {
    "L":                        {"L", "l", "litre", "liter"},
    "tCO2e":                    {"tCO2e", "tco2e", "t CO2e", "metric ton of CO2 equivalent"},
    "GJ":                       {"GJ"},
    "kL/tonne":                 {"kL/tonne", "kL/t", "kl/tonne"},
    "GJ/tonne":                 {"GJ/tonne", "GJ/t"},
    "kgCO2e/tonne":             {"kgCO2e/tonne", "kgCO2e/t", "kgco2e/tonne"},
    "%":                        {"%"},
    "count":                    {"count", ""},
    "kg":                       {"kg"},
    "days":                     {"days", "day"},
    "m3":                       {"m3", "m³"},
    "per million person hours": {"per million person hours", "per_million_hours", "per million hours", ""},
    "kL/million INR":           {"kL/million INR", ""},
    "kg/tonne":                 {"kg/tonne", "kg/t"},
}

def unit_matches(expected: str, actual: str | None) -> bool:
    if actual is None:
        return False
    acceptable = UNIT_ALIASES.get(expected, {expected})
    return actual in acceptable or actual.lower() in {a.lower() for a in acceptable}

def value_matches(expected: float, actual: float | None) -> bool:
    if actual is None:
        return False
    if expected == 0:
        return abs(actual) < 1e-6
    return abs(actual - expected) / abs(expected) <= 0.01  # 1% tolerance

def period_matches(expected_period: str, actual_fy: str | None) -> bool:
    """
    Nestle's FY2024 is a 15-month period (Jan 2023 – Mar 2024).
    Graph may store it as FY2024 or FY2023 depending on sub-period of chunk.
    Accept both as correct for FY2024 gold facts.
    """
    if actual_fy is None:
        return False
    if expected_period == "FY2024":
        return actual_fy in ("FY2024", "FY2023", "FY2023_15M")
    return expected_period in actual_fy or actual_fy in expected_period

def canonical_matches(expected: str | None, actual: str | None) -> bool:
    if expected is None:
        return True  # not testing canonical for this fact
    return expected == actual


def find_matching_observations(session, expected_value: float, expected_period: str) -> list[dict]:
    if expected_value == 0:
        lo, hi = -1.0, 1.0
    else:
        lo = expected_value * 0.98
        hi = expected_value * 1.02

    # Hard filter: only look in the FY2024 source document with matching period
    acceptable_years = ["FY2024", "FY2023", "FY2023_15M"] if expected_period == "FY2024" else [expected_period]

    cypher = """
        MATCH (o:Observation)-[:REPORTED_BY]->(c:Company {company_id: $company_id}),
              (o)-[:IN_PERIOD]->(p:Period)
        WHERE o.normalised_value >= $lo
          AND o.normalised_value <= $hi
          AND o.source_doc_id CONTAINS 'fy2024'
          AND p.fiscal_year IN $acceptable_years
        OPTIONAL MATCH (o)-[:OF_METRIC]->(m:Metric)
        RETURN
            o.obs_id                 AS obs_id,
            o.raw_name               AS raw_name,
            o.normalised_value       AS value,
            o.normalised_unit_symbol AS unit,
            o.normalization_status   AS status,
            o.canonical_id           AS canonical_id,
            o.source_doc_id          AS source_doc_id,
            o.period_label           AS period_label,
            p.fiscal_year            AS fiscal_year,
            m.display_name           AS metric_name,
            m.canonical_id           AS metric_canonical_id
        ORDER BY abs(o.normalised_value - $expected) ASC
        LIMIT 5
    """
    rows = list(session.run(cypher,
                            company_id=COMPANY_ID,
                            lo=lo, hi=hi,
                            expected=float(expected_value),
                            acceptable_years=acceptable_years))
    return [dict(r) for r in rows]


def evaluate():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    results = []
    with driver.session(database="neo4j", default_access_mode=READ_ACCESS) as session:
        for fact in GOLD_FACTS:
            fid          = fact["fact_id"]
            exp_val      = fact["expected_value"]
            exp_unit     = fact["expected_unit"]
            exp_period   = fact["expected_period"]
            exp_canon    = fact.get("expected_canonical")
            exp_status   = fact.get("expected_status")
            difficulty   = fact["difficulty"]

            candidates = find_matching_observations(session, exp_val, exp_period)

            # Filter to period-matching candidates
            period_candidates = [r for r in candidates if period_matches(exp_period, r.get("fiscal_year")) or period_matches(exp_period, r.get("period_label") or "")]

            # If no period match, fall back to all candidates (count as period fail)
            best = period_candidates[0] if period_candidates else (candidates[0] if candidates else None)

            if best is None:
                results.append({
                    "fact_id":    fid,
                    "difficulty": difficulty,
                    "found":      False,
                    "value_ok":   False,
                    "unit_ok":    False,
                    "period_ok":  False,
                    "canon_ok":   False,
                    "fully_correct": False,
                    "best":       None,
                    "note":       "NOT FOUND in graph",
                })
                continue

            v_ok = value_matches(exp_val,  best.get("value"))
            u_ok = unit_matches(exp_unit,  best.get("unit"))
            p_ok = period_matches(exp_period, best.get("fiscal_year")) or \
                   period_matches(exp_period, best.get("period_label") or "")
            c_ok = canonical_matches(exp_canon, best.get("canonical_id") or best.get("metric_canonical_id"))

            # "fully correct" = value + unit + period all match (canonical only if specified)
            fully = v_ok and u_ok and p_ok and c_ok

            results.append({
                "fact_id":       fid,
                "difficulty":    difficulty,
                "found":         True,
                "value_ok":      v_ok,
                "unit_ok":       u_ok,
                "period_ok":     p_ok,
                "canon_ok":      c_ok,
                "fully_correct": fully,
                "best":          best,
                "note":          "",
            })

    driver.close()
    return results


def print_report(results: list[dict]) -> None:
    total = len(results)
    found          = sum(1 for r in results if r["found"])
    value_correct  = sum(1 for r in results if r["value_ok"])
    unit_correct   = sum(1 for r in results if r["unit_ok"])
    period_correct = sum(1 for r in results if r["period_ok"])
    canon_correct  = sum(1 for r in results if r["canon_ok"])
    fully_correct  = sum(1 for r in results if r["fully_correct"])

    # By difficulty
    by_diff: dict[str, dict] = {}
    for r in results:
        d = r["difficulty"]
        if d not in by_diff:
            by_diff[d] = {"total": 0, "fully": 0}
        by_diff[d]["total"] += 1
        if r["fully_correct"]:
            by_diff[d]["fully"] += 1

    print("=" * 60)
    print("  ESG PIPELINE EVAL — Nestlé India FY2024 Gold Set")
    print("=" * 60)
    print(f"  Total facts in gold set : {total}")
    print(f"  Facts found in graph    : {found}  ({found/total*100:.1f}%)")
    print()
    print("  Accuracy (among found facts):")
    print(f"    Value correct  : {value_correct}/{total}  ({value_correct/total*100:.1f}%)")
    print(f"    Unit correct   : {unit_correct}/{total}  ({unit_correct/total*100:.1f}%)")
    print(f"    Period correct : {period_correct}/{total}  ({period_correct/total*100:.1f}%)")
    print(f"    Canonical ok   : {canon_correct}/{total}  ({canon_correct/total*100:.1f}%)")
    print()
    print(f"  FULLY CORRECT           : {fully_correct}/{total}  ({fully_correct/total*100:.1f}%)")
    print()
    print("  By difficulty:")
    for d in ("easy", "medium", "hard"):
        s = by_diff.get(d, {"total": 0, "fully": 0})
        pct = s["fully"] / s["total"] * 100 if s["total"] else 0
        print(f"    {d:6s} : {s['fully']}/{s['total']}  ({pct:.1f}%)")

    # Missed facts
    missed = [r for r in results if not r["found"]]
    if missed:
        print()
        print(f"  MISSED ({len(missed)} facts not in graph):")
        for r in missed:
            print(f"    {r['fact_id']}  [{r['difficulty']}]  {r['note']}")

    # Wrong facts (found but not fully correct)
    wrong = [r for r in results if r["found"] and not r["fully_correct"]]
    if wrong:
        print()
        print(f"  WRONG / PARTIAL ({len(wrong)} facts found but not fully correct):")
        for r in wrong:
            b = r["best"]
            flags = []
            if not r["value_ok"]:  flags.append(f"value={b.get('value')} (expected ~{_get_expected(r['fact_id'])})")
            if not r["unit_ok"]:   flags.append(f"unit={b.get('unit')!r}")
            if not r["period_ok"]: flags.append(f"period={b.get('fiscal_year')!r}")
            if not r["canon_ok"]:  flags.append(f"canon={b.get('canonical_id')!r}")
            print(f"    {r['fact_id']}  [{r['difficulty']}]  raw_name={b.get('raw_name')!r}")
            print(f"      Issues: {'; '.join(flags)}")

    print("=" * 60)


def _get_expected(fact_id: str) -> float | None:
    for f in GOLD_FACTS:
        if f["fact_id"] == fact_id:
            return f["expected_value"]
    return None


if __name__ == "__main__":
    print("Running eval against Neo4j...")
    results = evaluate()
    print_report(results)
