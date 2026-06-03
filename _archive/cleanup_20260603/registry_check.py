import json

# Read approved additions
reg = json.load(open('registry_additions_approved.json', encoding='utf-8'))
existing_ids = {r.get('canonical_id') for r in reg}
print(f"Current entries in registry_additions_approved.json: {len(reg)}")
print("Existing canonical_ids:")
for r in reg:
    print(f"  {r.get('canonical_id')}")

# Read master registry v1
from normalizer import _metric_registry_with_seed
all_master = {str(r.get('canonical_id') or '') for r in _metric_registry_with_seed()}

# Check the 5 specific IDs
check_ids = [
    "nox_emissions_absolute",
    "sox_emissions_absolute",
    "scope_1_2_combined_absolute",
    "epr_target_assigned",
    "energy_intensity_physical_output",
]
print()
print("Pre-existence check:")
for cid in check_ids:
    in_approved = cid in existing_ids
    in_master = cid in all_master
    status = "EXISTS in approved" if in_approved else ("EXISTS in master" if in_master else "NOT FOUND - safe to add")
    print(f"  {cid}: {status}")

# Also check all 18 new IDs against master
new_ids = [
    "battery_waste_generated", "biomedical_waste_generated", "other_hazardous_waste_generated",
    "plastic_waste_generated", "waste_recycled_absolute", "waste_reused_absolute",
    "wastewater_generated_absolute", "complaint_count_filed", "complaint_count_pending",
    "ghg_intensity_physical_output", "scope_2_emissions_net", "ghg_reduction_vs_baseline",
    "return_to_work_rate", "health_safety_assessment_coverage", "energy_reduction_vs_baseline",
    "wastewater_intensity_physical_output", "nox_emissions_absolute", "sox_emissions_absolute",
]
print()
print("All 18 new IDs — master registry check:")
for cid in new_ids:
    in_approved = cid in existing_ids
    in_master = cid in all_master
    if in_approved or in_master:
        print(f"  SKIP {cid} (already exists)")
    else:
        print(f"  OK   {cid}")
