import json
from collections import defaultdict

data = json.load(open("workspace_test_outputs/prompt_sanity_check_out.json"))
facts = data["facts"] if isinstance(data, dict) else data

by_page = defaultdict(list)
for f in facts:
    cid = f.get("chunk_id", "")
    page = cid.replace("nestle_india_p", "") if "nestle_india_p" in cid else "unknown"
    by_page[page].append(f)

print("=== FACTS PER PAGE ===")
for p in ["206", "207", "208", "209", "210", "211"]:
    print(f"  p{p}: {len(by_page[p])} facts")

def row(f):
    raw = f.get("raw") or {}
    rn = raw.get("raw_name") or f.get("metric", "")
    rv = raw.get("raw_value") or str(f.get("value", ""))
    ru = raw.get("raw_unit") or f.get("unit", "")
    rp = (raw.get("raw_period") or f.get("period") or "")[:50]
    return f"  {rn} | {rv} {ru} | {rp}"

print()
print("=== PAGE 208 - ENERGY SUB-ROWS ===")
for f in by_page["208"]:
    print(row(f))

print()
print("=== PAGE 209 - WATER SUB-ROWS ===")
for f in by_page["209"]:
    print(row(f))
