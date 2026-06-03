import json

NEW_ENTRIES = [
  {
    "canonical_id": "battery_waste_generated",
    "display_name": "Battery Waste Generated",
    "category": "waste",
    "unit_family": "weight",
    "metric_subject": "waste",
    "metric_role": "generation",
    "flow_direction": "output",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"gri": "306-3"},
    "aliases": [
      "battery waste", "battery waste generated", "batteries waste",
      "waste batteries", "battery waste disposal"
    ]
  },
  {
    "canonical_id": "biomedical_waste_generated",
    "display_name": "Bio-Medical Waste Generated",
    "category": "waste",
    "unit_family": "weight",
    "metric_subject": "waste",
    "metric_role": "generation",
    "flow_direction": "output",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"gri": "306-3"},
    "aliases": [
      "bio-medical waste", "biomedical waste", "bio medical waste",
      "clinical waste", "medical waste generated"
    ]
  },
  {
    "canonical_id": "other_hazardous_waste_generated",
    "display_name": "Other Hazardous Waste Generated",
    "category": "waste",
    "unit_family": "weight",
    "metric_subject": "waste",
    "metric_role": "generation",
    "flow_direction": "output",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"gri": "306-3"},
    "aliases": [
      "other hazardous waste", "other hazardous waste generated",
      "hazardous waste other", "other hazardous",
      "hazardous waste excluding e-waste"
    ]
  },
  {
    "canonical_id": "waste_recycled_absolute",
    "display_name": "Waste Recycled (Absolute)",
    "category": "waste",
    "unit_family": "weight",
    "metric_subject": "waste",
    "metric_role": "recovery",
    "flow_direction": "restoration",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"gri": "306-4"},
    "aliases": [
      "waste recycled", "recycled waste", "total waste recycled",
      "waste sent for recycling", "amount recycled", "recycling"
    ]
  },
  {
    "canonical_id": "waste_reused_absolute",
    "display_name": "Waste Reused (Absolute)",
    "category": "waste",
    "unit_family": "weight",
    "metric_subject": "waste",
    "metric_role": "recovery",
    "flow_direction": "restoration",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"gri": "306-4"},
    "aliases": [
      "waste reused", "reused waste", "total waste reused",
      "re-used waste", "waste sent for reuse", "amount reused"
    ]
  },
  {
    "canonical_id": "wastewater_generated_absolute",
    "display_name": "Wastewater Generated (Absolute)",
    "category": "water",
    "unit_family": "volume",
    "metric_subject": "water",
    "metric_role": "generation",
    "flow_direction": "output",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"gri": "303-4"},
    "aliases": [
      "waste water generation", "wastewater generation",
      "total wastewater generated", "effluent generated",
      "wastewater produced", "waste water generated"
    ]
  },
  {
    "canonical_id": "complaint_count_filed",
    "display_name": "Complaints Filed",
    "category": "governance",
    "unit_family": "count",
    "metric_subject": "complaints",
    "metric_role": "count",
    "flow_direction": "output",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"brsr": "P1-E-3"},
    "aliases": [
      "complaints filed", "number of complaints filed",
      "complaints filed during the year",
      "number of complaints filed during the year",
      "complaints received", "grievances filed",
      "complaints filed during the year from employees and workers",
      "complaints filed during the year from customers",
      "complaints filed during the year from shareholders",
      "complaints filed during the year from value chain partners",
      "complaints filed during the year from communities",
      "complaints filed during the year from investors"
    ]
  },
  {
    "canonical_id": "complaint_count_pending",
    "display_name": "Complaints Pending Resolution",
    "category": "governance",
    "unit_family": "count",
    "metric_subject": "complaints",
    "metric_role": "count",
    "flow_direction": "output",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"brsr": "P1-E-3"},
    "aliases": [
      "complaints pending", "complaints pending resolution",
      "number of complaints pending", "pending complaints",
      "grievances pending", "complaints pending at close of year",
      "complaints pending resolution at close of the year from employees and workers",
      "complaints pending resolution at close of the year from customers",
      "complaints pending resolution at close of the year from shareholders",
      "complaints pending resolution at close of the year from value chain partners",
      "complaints pending resolution at close of the year from communities",
      "complaints pending resolution at close of the year from investors"
    ]
  },
  {
    "canonical_id": "ghg_intensity_physical_output",
    "display_name": "GHG Intensity per Physical Output",
    "category": "emissions",
    "unit_family": "intensity",
    "metric_subject": "emissions",
    "metric_role": "intensity",
    "flow_direction": "output",
    "denominator_type": "physical_output",
    "comparable": True,
    "external_refs": {"gri": "305-4", "brsr": "P6-E-6"},
    "aliases": [
      "specific ghg emission", "ghg intensity",
      "ghg intensity per tonne of production",
      "specific greenhouse gas emission", "ghg emissions per tonne",
      "ghg intensity physical output",
      "total scope 1 and scope 2 emission intensity",
      "scope 1 and scope 2 emission intensity",
      "combined ghg intensity", "kgco2e per tonne"
    ]
  },
  {
    "canonical_id": "scope_2_emissions_net",
    "display_name": "Scope 2 Emissions Net (IREC-Adjusted)",
    "category": "emissions",
    "unit_family": "emissions",
    "metric_subject": "emissions",
    "metric_role": "generation",
    "flow_direction": "output",
    "denominator_type": "none",
    "comparable": False,
    "external_refs": {"gri": "305-2"},
    "aliases": [
      "scope 2 emissions net", "scope 2 net emissions",
      "total scope 2 emissions gross including irecs net",
      "scope 2 emissions including irecs net", "scope 2 net",
      "market based scope 2", "scope 2 market based"
    ]
  },
  {
    "canonical_id": "return_to_work_rate",
    "display_name": "Return to Work Rate",
    "category": "social",
    "unit_family": "percentage",
    "metric_subject": "workforce",
    "metric_role": "coverage",
    "flow_direction": "unknown",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"gri": "401-3", "brsr": "P3-E-11"},
    "aliases": [
      "return to work rate",
      "return to work rate male permanent employees",
      "return to work rate female permanent employees",
      "return to work percentage",
      "employees returned to work after parental leave"
    ]
  },
  {
    "canonical_id": "health_safety_assessment_coverage",
    "display_name": "Health and Safety Practices Assessment Coverage",
    "category": "social",
    "unit_family": "percentage",
    "metric_subject": "workforce",
    "metric_role": "coverage",
    "flow_direction": "unknown",
    "denominator_type": "none",
    "comparable": True,
    "external_refs": {"brsr": "P3-E-13"},
    "aliases": [
      "health and safety practices assessed",
      "health and safety assessment coverage",
      "percentage assessed for health and safety",
      "health and safety practices assessed percentage",
      "workers assessed for health and safety"
    ]
  },
  {
    "canonical_id": "wastewater_intensity_physical_output",
    "display_name": "Wastewater Intensity per Physical Output",
    "category": "water",
    "unit_family": "intensity",
    "metric_subject": "water",
    "metric_role": "intensity",
    "flow_direction": "output",
    "denominator_type": "physical_output",
    "comparable": True,
    "external_refs": {"gri": "303-4"},
    "aliases": [
      "waste water generation per ton of production",
      "wastewater intensity", "specific wastewater generation",
      "wastewater generation per tonne",
      "waste water generation for every ton of production"
    ]
  },
]

SKIP_IDS = {
    "plastic_waste_generated", "ghg_reduction_vs_baseline",
    "energy_reduction_vs_baseline", "nox_emissions_absolute", "sox_emissions_absolute",
}

reg = json.load(open('registry_additions_approved.json', encoding='utf-8'))
existing_ids = {r.get('canonical_id') for r in reg}

added = []
skipped = []
for entry in NEW_ENTRIES:
    cid = entry['canonical_id']
    if cid in existing_ids or cid in SKIP_IDS:
        skipped.append(cid)
    else:
        reg.append(entry)
        added.append(cid)

with open('registry_additions_approved.json', 'w', encoding='utf-8') as f:
    json.dump(reg, f, indent=2, ensure_ascii=False)

print(f"Entries before: {len(reg) - len(added)}")
print(f"Entries added:  {len(added)}")
print(f"Entries after:  {len(reg)}")
print(f"Skipped (already exist): {skipped}")
print(f"Added:")
for cid in added:
    print(f"  {cid}")
