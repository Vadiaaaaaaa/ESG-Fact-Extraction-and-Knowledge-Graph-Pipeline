import json

data = json.load(open('workspace_test_outputs/nestle_india_2022_pass2_rerun.json', encoding='utf-8'))
facts = data.get('facts', data) if isinstance(data, dict) else data

# Fix1: TJ facts
tj = [f for f in facts if 'tj' in str(f.get('raw_unit_string', '')).lower() or 'terra' in str(f.get('raw_unit_string', '')).lower()]
print('=== Fix1: TJ facts ===')
for f in tj:
    print(f"  {f['fact_id']} | raw_unit={f['raw_unit_string']} | raw_value={f['raw_value']} | norm={f['normalised_value']} {f['normalised_unit_symbol']}")

# Fix2: water_discharged_total FY2022
print()
print('=== Fix2: water_discharged FY2022 ===')
wf = [f for f in facts if 'water_discharg' in str(f.get('canonical_id', '')).lower() and f.get('period_label') == 'FY2022']
for f in wf:
    print(f"  {f['fact_id']} | canonical_id={f['canonical_id']} | normalised={f['normalised_value']} {f['normalised_unit_symbol']}")

# Fix3: scope_2
print()
print('=== Fix3: scope_2 facts ===')
s2 = [f for f in facts if 'scope_2' in str(f.get('canonical_id', '')).lower()]
for f in s2:
    print(f"  {f['fact_id']} | canonical_id={f['canonical_id']} | normalised={f['normalised_value']} {f['normalised_unit_symbol']} | period={f['period_label']}")

# Fix5: out_of_scope_financial with operational names
print()
print('=== Fix5: overcaught operational counts ===')
targets = ['intern', 'mentor', 'mentee', 'cities', 'states']
oc = [f for f in facts if f.get('normalization_status') == 'out_of_scope_financial'
      and any(t in str((f.get('raw') or {}).get('raw_name', '')).lower() for t in targets)]
for f in oc:
    raw_name = (f.get('raw') or {}).get('raw_name', '')
    print(f"  {f['fact_id']} | raw_name={raw_name}")

# Fix4: 2021 macro facts
print()
print('=== Fix4: 2021 macro context facts ===')
data21 = json.load(open('workspace_test_outputs/nestle_india_2021_pass2_rerun.json', encoding='utf-8'))
facts21 = data21.get('facts', data21) if isinstance(data21, dict) else data21
macro_targets = []
for f in facts21:
    raw_name = str((f.get('raw') or {}).get('raw_name', '')).lower()
    raw_val = str((f.get('raw') or {}).get('raw_value', ''))
    if 'global economy' in raw_name or 'gdp' in raw_name or ('carbon intensity' in raw_name and raw_val == '45'):
        macro_targets.append(f)
        print(f"  {f['fact_id']} | raw_name={(f.get('raw') or {}).get('raw_name')} | raw_value={raw_val}")
