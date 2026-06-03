import json, csv
from collections import Counter


def find_val(facts, *keys):
    for f in facts:
        cid = str(f.get("canonical_metric_id") or f.get("metric") or "").lower()
        raw = f.get("raw") or {}
        raw_core = str(raw.get("metric_core", "") if isinstance(raw, dict) else "").lower()
        for k in keys:
            if k in cid or k in raw_core:
                v = f.get("value") or (raw.get("raw_value", "") if isinstance(raw, dict) else "")
                u = f.get("unit") or (raw.get("raw_unit", "") if isinstance(raw, dict) else "")
                return f"{v} {u}".strip()
    return "not found"


def summarize(year, pass1_path, pass2_path, audit_csv, chunks_path):
    p1 = json.load(open(pass1_path, encoding="utf-8"))
    p1_facts = p1.get("facts", p1) if isinstance(p1, dict) else p1

    p2 = json.load(open(pass2_path, encoding="utf-8"))
    p2_facts = p2.get("facts", p2) if isinstance(p2, dict) else p2

    with open(audit_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    pages_scanned = len(rows)
    pages_selected = sum(1 for r in rows if str(r.get("selected", "")).lower() == "true")
    high_signal = sum(1 for r in rows if str(r.get("high_signal_unselected", "")).lower() == "true")
    risk = "HIGH" if high_signal > 0 else "LOW"

    d = Counter(f.get("decision", "") for f in p1_facts)
    n = Counter(f.get("normalization_decision", "") for f in p2_facts)

    water = find_val(p2_facts, "water_discharged", "water_discharge")
    scope1 = find_val(p2_facts, "scope_1", "ghg_scope1", "direct_ghg", "scope1")
    waste = find_val(p2_facts, "waste_generated", "total_waste", "plastic_waste")
    headcount = find_val(p2_facts, "manpower", "employee_count", "headcount", "employees_permanent")

    print(f"Report: Nestle India {year}")
    print(f"Pages scanned:        {pages_scanned}")
    print(f"Pages selected:       {pages_selected}")
    print(f"Coverage risk:        {risk}")
    print()
    print("Pass 1:")
    print(f"  extracted: {len(p1_facts)}  keep: {d['keep']}  rescue: {d['rescue']}  drop: {d['drop']}")
    print()
    print("Pass 2:")
    print(f"  normalized:   {n['normalized']}")
    print(f"  partial:      {n['partial']}")
    print(f"  new_metric:   {n['new_metric']}")
    print(f"  financial:    {n['out_of_scope_financial']}")
    print()
    print("Key values found:")
    print(f"  water_discharged_total:     {water}")
    print(f"  scope_1_emissions:          {scope1}")
    print(f"  waste_generated:            {waste}")
    print(f"  employee headcount:         {headcount}")
    print()
    print("-" * 60)
    print()


summarize(
    2022,
    "workspace_test_outputs/nestle_india_2022_pass1_rerun.json",
    "workspace_test_outputs/nestle_india_2022_pass2_rerun.json",
    "workspace_test_outputs/nestle_india_2022_rerun_section_coverage_audit.csv",
    "workspace_test_outputs/nestle_india_2022_rerun_fast_chunks.json",
)

summarize(
    2021,
    "workspace_test_outputs/nestle_india_2021_pass1_rerun.json",
    "workspace_test_outputs/nestle_india_2021_pass2_rerun.json",
    "workspace_test_outputs/nestle_india_2021_rerun_section_coverage_audit.csv",
    "workspace_test_outputs/nestle_india_2021_rerun_fast_chunks.json",
)
