import json
from pathlib import Path
from collections import Counter

P22 = Path("workspace_test_outputs/nestle_india_2022_pass2_rerun.json")
P21 = Path("workspace_test_outputs/nestle_india_2021_pass2_rerun.json")


def load(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, data.get("facts", data) if isinstance(data, dict) else data


def _raw_name(f):
    return str((f.get("raw") or {}).get("raw_name", "")).lower()


def _raw_value_str(f):
    return str((f.get("raw") or {}).get("raw_value", ""))


# â”€â”€ load â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
data22, facts22 = load(P22)
data21, facts21 = load(P21)

# â”€â”€ Fix 1: patch Terra Joules facts in 2022 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print("=== Fix 1 â€” TJ unit patch ===")
fix1_patched = []
for f in facts22:
    ru = str(f.get("raw_unit_string", "")).lower()
    if ("terra joule" in ru or "terajoule" in ru) and f.get("normalised_unit_symbol") != "GJ":
        raw_num_str = str(f.get("raw_value", "0")).replace(",", "")
        try:
            raw_num = float(raw_num_str)
        except ValueError:
            continue
        before = (f["normalised_value"], f["normalised_unit_symbol"])
        f["normalised_value"] = raw_num * 1000.0
        f["normalised_unit_symbol"] = "GJ"
        f["normalisation_confidence"] = "exact"
        fix1_patched.append((f["fact_id"], before[0], before[1], f["normalised_value"], f["raw_unit_string"]))

print(f"  Facts patched: {len(fix1_patched)}")
for fid, v_before, u_before, v_after, raw_u in fix1_patched:
    print(f"    {fid}: {v_before} {u_before} ({raw_u}) â†’ {v_after} GJ")

# â”€â”€ Fix 2: flag duplicate water_discharged_total in 2022 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print("=== Fix 2 â€” Water discharged duplicate ===")
wf = [f for f in facts22 if "water_discharged_total" in str(f.get("canonical_id", ""))
      and f.get("period_label") == "FY2022"]
# find the higher-value (secondary) one
wf_sorted = sorted(wf, key=lambda f: f.get("normalised_value") or 0, reverse=True)
if len(wf_sorted) >= 2:
    dup = wf_sorted[0]
    auth_val = wf_sorted[1].get("normalised_value", 0)
    # convert to kL for display (stored in L)
    dup_kl = int((dup.get("normalised_value") or 0) / 1000)
    auth_kl = int(auth_val / 1000)
    dup["data_quality_note"] = "duplicate_from_secondary_table"
    dup["superseded"] = True
    dup["superseded_by_value"] = auth_kl
    print(f"  Flagged: {dup['fact_id']} | {dup_kl:,} kL â†’ superseded_by_value={auth_kl:,} kL")
else:
    print(f"  Only {len(wf_sorted)} water_discharged_total FY2022 facts found â€” no duplicate flagged")

# â”€â”€ Fix 3: quarantine implausible Scope 2 drop in 2022 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print("=== Fix 3 â€” Scope 2 quarantine ===")
s2_facts = [f for f in facts22 if "scope_2" in str(f.get("canonical_id", "")).lower()]
quarantined = []
for f in s2_facts:
    if f.get("period_label") == "FY2022" and (f.get("normalised_value") or 0) < 10000:
        f["normalization_decision"] = "quarantine"
        f["normalization_status"] = "quarantine"
        f["quarantine_reason"] = "scope2_magnitude_implausible_drop"
        f["quarantine_note"] = (
            f"FY2022 Scope 2 = {f['normalised_value']:,.0f} tCO2e vs FY2021 = 112,879 tCO2e"
            " â€” 99% drop requires manual verification"
        )
        quarantined.append(f)
        print(f"  Quarantined: {f['fact_id']} | {f['normalised_value']} tCO2e FY2022")
if not quarantined:
    print("  No implausible Scope 2 facts found")

# â”€â”€ Fix 4: drop macroeconomic context facts from 2021 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print("=== Fix 4 â€” Macro context drop (2021) ===")
fix4_dropped = []
for f in facts21:
    rn = _raw_name(f)
    rv = _raw_value_str(f)
    is_macro = (
        "global economy" in rn
        or "gdp" in rn
        or ("carbon intensity" in rn and rv == "45")
    )
    if is_macro:
        f["normalization_decision"] = "drop"
        f["normalization_status"] = "drop"
        f["drop_reason"] = "macroeconomic_context_not_company_fact"
        raw_name_display = (f.get("raw") or {}).get("raw_name", "")
        fix4_dropped.append(raw_name_display)
        print(f"  Dropped: {f['fact_id']} | {raw_name_display}")
print(f"  Total dropped: {len(fix4_dropped)}")

# â”€â”€ Fix 5: reclassify over-blocked operational counts in 2022 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print("=== Fix 5 â€” Operational counts reclassified (2022) ===")
oc_targets = ["intern", "mentor", "mentee", "cities", "states"]
fix5_reclassified = []
for f in facts22:
    if f.get("normalization_status") == "out_of_scope_financial":
        rn = _raw_name(f)
        if any(t in rn for t in oc_targets):
            f["normalization_status"] = "new_metric"
            f["normalization_decision"] = "new_metric"
            f["canonical_id"] = ""
            f["data_quality_note"] = "reclassified_from_financial_overcatch"
            raw_name_display = (f.get("raw") or {}).get("raw_name", "")
            fix5_reclassified.append(raw_name_display)
            print(f"  Reclassified: {f['fact_id']} | {raw_name_display}")
print(f"  Total reclassified: {len(fix5_reclassified)}")

# â”€â”€ Write back â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if isinstance(data22, dict):
    data22["facts"] = facts22
    P22.write_text(json.dumps(data22, indent=2, ensure_ascii=False), encoding="utf-8")
else:
    P22.write_text(json.dumps(facts22, indent=2, ensure_ascii=False), encoding="utf-8")

if isinstance(data21, dict):
    data21["facts"] = facts21
    P21.write_text(json.dumps(data21, indent=2, ensure_ascii=False), encoding="utf-8")
else:
    P21.write_text(json.dumps(facts21, indent=2, ensure_ascii=False), encoding="utf-8")

# â”€â”€ Final counts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
print("=== Final pass2 counts after fixes ===")
for label, facts in [("2022", facts22), ("2021", facts21)]:
    c = Counter(f.get("normalization_decision", "") for f in facts)
    print(
        f"  {label}: normalized={c['normalized']}  partial={c['partial']}"
        f"  new_metric={c['new_metric']}  financial={c['out_of_scope_financial']}"
        f"  quarantine={c['quarantine']}  drop={c['drop']}"
    )

print()
print("Files written.")

