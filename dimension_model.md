# Dimension Model

This document defines the dimensional breakdown model that sits alongside canonical metrics. It is intentionally separate from canonical IDs so we do not bloat the registry with one canonical per breakdown variant.

## Goal

Use one canonical metric for the total concept and attach structured dimensions to observations when the reported fact is a breakdown:

- `waste_generated` + `waste_type=biomedical`
- `waste_recovered_total` + `recovery_method=recycled`
- `water_withdrawal` + `water_source=groundwater`
- `water_discharged_total` + `water_destination=surface`
- `absolute_energy_consumption` + `energy_source=solar`
- `combined_scope_1_2_emissions` + `emission_source=stationary_combustion`

This keeps the metric registry stable while preserving drill-down detail.

## Graph Schema

### Nodes

```cypher
(:Dimension {
  dimension_id:   string,
  label:          string,
  applies_to:     list<string>,
  allowed_values: list<string>
})

(:DimensionValue {
  value_id:       string,
  dimension_id:   string,
  value:          string,
  label:          string,
  aliases:        list<string>
})
```

### Relationships

```cypher
(m:Metric)-[:HAS_DIMENSION]->(d:Dimension)
(o:Observation)-[:WITH_DIMENSION_VALUE]->(dv:DimensionValue)
(dv:DimensionValue)-[:BELONGS_TO]->(d:Dimension)
```

`BELONGS_TO` is optional but recommended for graph traversal and integrity checks.

## Loader Rules

1. Load all `Dimension` nodes first.
2. Load all `DimensionValue` nodes next.
3. Link canonical metrics to their supported dimensions with `HAS_DIMENSION`.
4. During observation load:
   - if the fact is not dimensional, create no `WITH_DIMENSION_VALUE` edge
   - if the fact is dimensional and unambiguous, link to exactly one `DimensionValue`
   - if the fact names multiple values inside the same dimension, create multiple `WITH_DIMENSION_VALUE` edges and set `dimension_assignment_mode = "multi_value"`
   - if the fact is ambiguous, do not guess; store `dimension_assignment_status = "ambiguous"`

## How Pass 1 marks dimensional facts

Use these fields from Pass 1 output:

- `dimension_type`
- `dimension_member`
- `breakdown_flag`
- `parent_metric_hint`
- `raw_name`
- `source_sentence`

### Primary identification rule

A fact is a dimensional variant when:

1. `dimension_type` is not `none`, and
2. `dimension_member` is non-empty

### Secondary recovery rule

If `dimension_type == "none"` but the text clearly expresses a breakdown, derive the dimension during load-time enrichment from:

- `parent_metric_hint`
- `raw_name`
- `source_sentence`

Examples:

- `"waste recycled"` -> `dimension_type = recovery_method`, `dimension_member = recycled`
- `"hazardous waste generated"` -> `dimension_type = waste_type`, `dimension_member = hazardous`
- `"groundwater withdrawn"` -> `dimension_type = water_source`, `dimension_member = groundwater`
- `"solar power consumed"` -> `dimension_type = energy_source`, `dimension_member = solar`

### Total-vs-breakdown rule

If the fact label is a total concept and does not name a dimension member, do not attach a dimension value.

Examples:

- `Total waste generated` -> no dimension
- `Total water withdrawal` -> no dimension
- `Total energy consumed` -> no dimension

## Ambiguity Handling

### Multiple values in the same fact

If one fact truly combines multiple values inside one dimension:

Example:
- `"waste recycled and reused: 450 MT"`

Then:

- keep one observation if the source reports only one combined number
- attach two `WITH_DIMENSION_VALUE` edges:
  - `recovery_method_recycled`
  - `recovery_method_reused`
- set:
  - `dimension_assignment_mode = "multi_value"`
  - `dimension_assignment_status = "combined_reported_value"`

Do **not** split the value equally or invent sub-values.

### Ambiguous value

If the text is not specific enough to map confidently:

Example:
- `"waste diverted"` with no method named

Then:

- keep the observation
- do not attach a `DimensionValue`
- set `dimension_assignment_status = "ambiguous"`

## Dimensions

## 1. `waste_type`

### Node

```json
{
  "dimension_id": "waste_type",
  "label": "Waste type",
  "applies_to": [
    "waste_generated",
    "waste_disposed_total",
    "waste_diverted_from_landfill",
    "waste_recovered_total",
    "waste_to_landfill",
    "e_waste_generated",
    "construction_demolition_waste",
    "plastic_packaging_consumed",
    "plastic_recycled_total"
  ],
  "allowed_values": [
    "hazardous",
    "non_hazardous",
    "plastic",
    "biomedical",
    "battery",
    "e_waste",
    "construction_demolition",
    "other"
  ]
}
```

### Values

- `waste_type_hazardous`
  - aliases: `hazardous waste`, `haz waste`, `regulated waste`
- `waste_type_non_hazardous`
  - aliases: `non hazardous waste`, `non-hazardous waste`, `general waste`
- `waste_type_plastic`
  - aliases: `plastic waste`, `plastic packaging waste`, `plastic packaging`
- `waste_type_biomedical`
  - aliases: `biomedical waste`, `bio-medical waste`, `medical waste`
- `waste_type_battery`
  - aliases: `battery waste`, `used batteries`
- `waste_type_e_waste`
  - aliases: `e-waste`, `electronic waste`, `ewaste`
- `waste_type_construction_demolition`
  - aliases: `construction and demolition waste`, `c&d waste`, `construction demolition waste`
- `waste_type_other`
  - aliases: `other waste`, `miscellaneous waste`

## 2. `recovery_method`

### Node

```json
{
  "dimension_id": "recovery_method",
  "label": "Recovery method",
  "applies_to": [
    "waste_recovered_total",
    "waste_diverted_from_landfill",
    "plastic_recycled_total",
    "pre_consumer_plastic_recycling_rate"
  ],
  "allowed_values": [
    "recycled",
    "reused",
    "composted",
    "other_recovery"
  ]
}
```

### Values

- `recovery_method_recycled`
  - aliases: `recycled`, `recycling`, `sent for recycling`
- `recovery_method_reused`
  - aliases: `reused`, `reuse`, `re-use`
- `recovery_method_composted`
  - aliases: `composted`, `composting`, `organic recovery`
- `recovery_method_other_recovery`
  - aliases: `other recovery`, `other diverted`, `co-processed`, `co processed`

## 3. `disposal_method`

### Node

```json
{
  "dimension_id": "disposal_method",
  "label": "Disposal method",
  "applies_to": [
    "waste_disposed_total",
    "waste_to_landfill"
  ],
  "allowed_values": [
    "landfill",
    "incineration",
    "other_disposal"
  ]
}
```

### Values

- `disposal_method_landfill`
  - aliases: `landfill`, `sent to landfill`, `landfilled`
- `disposal_method_incineration`
  - aliases: `incineration`, `incinerated`, `burned for disposal`
- `disposal_method_other_disposal`
  - aliases: `other disposal`, `deep burial`, `other treatment`

## 4. `water_source`

### Node

```json
{
  "dimension_id": "water_source",
  "label": "Water source",
  "applies_to": [
    "water_withdrawal",
    "water_withdrawal_high_stress",
    "rainwater_harvested",
    "water_consumption_absolute"
  ],
  "allowed_values": [
    "surface",
    "groundwater",
    "seawater",
    "rainwater",
    "municipal",
    "other"
  ]
}
```

### Values

- `water_source_surface`
  - aliases: `surface water`, `river water`, `lake water`, `reservoir water`
- `water_source_groundwater`
  - aliases: `groundwater`, `borewell water`, `well water`
- `water_source_seawater`
  - aliases: `seawater`, `sea water`
- `water_source_rainwater`
  - aliases: `rainwater`, `harvested rainwater`
- `water_source_municipal`
  - aliases: `municipal water`, `third-party water`, `town supply`, `purchased water`
- `water_source_other`
  - aliases: `other water source`, `other sources`

## 5. `water_destination`

### Node

```json
{
  "dimension_id": "water_destination",
  "label": "Water destination",
  "applies_to": [
    "water_discharged_total",
    "water_discharged_surface_treated"
  ],
  "allowed_values": [
    "surface",
    "groundwater",
    "seawater",
    "municipal",
    "third_party",
    "other"
  ]
}
```

### Values

- `water_destination_surface`
  - aliases: `surface water`, `rivers`, `lakes`, `ponds`
- `water_destination_groundwater`
  - aliases: `groundwater`, `subsurface discharge`
- `water_destination_seawater`
  - aliases: `seawater`, `marine discharge`
- `water_destination_municipal`
  - aliases: `municipal drain`, `municipal sewer`
- `water_destination_third_party`
  - aliases: `third party`, `third-party treatment`, `external treatment`
- `water_destination_other`
  - aliases: `other destination`, `other receiving body`

## 6. `energy_source`

### Node

```json
{
  "dimension_id": "energy_source",
  "label": "Energy source",
  "applies_to": [
    "absolute_energy_consumption",
    "renewable_energy_consumption_absolute",
    "renewable_energy_mix",
    "energy_saved_absolute",
    "energy_conservation_investment"
  ],
  "allowed_values": [
    "grid",
    "solar",
    "wind",
    "biomass",
    "natural_gas",
    "coal",
    "other"
  ]
}
```

### Values

- `energy_source_grid`
  - aliases: `grid electricity`, `purchased electricity`, `grid power`
- `energy_source_solar`
  - aliases: `solar`, `solar power`, `solar energy`
- `energy_source_wind`
  - aliases: `wind`, `wind power`, `wind energy`
- `energy_source_biomass`
  - aliases: `biomass`, `biofuel`, `bagasse`, `agri residue`
- `energy_source_natural_gas`
  - aliases: `natural gas`, `lng`, `png`, `gas fired`
- `energy_source_coal`
  - aliases: `coal`, `coal fired`
- `energy_source_other`
  - aliases: `other fuel`, `other source`

## 7. `emission_source`

### Node

```json
{
  "dimension_id": "emission_source",
  "label": "Emission source",
  "applies_to": [
    "combined_scope_1_2_emissions",
    "scope_2_emissions",
    "scope_3_emissions_absolute",
    "nox_emissions_absolute",
    "sox_emissions_absolute"
  ],
  "allowed_values": [
    "stationary_combustion",
    "mobile_combustion",
    "fugitive",
    "process"
  ]
}
```

### Values

- `emission_source_stationary_combustion`
  - aliases: `stationary combustion`, `boilers`, `furnaces`, `dg sets`
- `emission_source_mobile_combustion`
  - aliases: `mobile combustion`, `fleet`, `transport fuel`, `vehicles`
- `emission_source_fugitive`
  - aliases: `fugitive`, `refrigerant leakage`, `leakage`
- `emission_source_process`
  - aliases: `process emissions`, `process source`

## Mapping logic at load time

### Step 1

Take the canonical metric chosen by Pass 2.

### Step 2

Check whether the metric supports dimensions:

- if the canonical is not in `applies_to`, stop
- if it is, inspect `dimension_type` and `dimension_member`

### Step 3

Map `dimension_member` to a controlled `DimensionValue` by alias matching:

1. exact lowercase alias match
2. normalized punctuation-stripped alias match
3. longest-alias-wins if multiple aliases match

### Step 4

If still unresolved, use `raw_name + source_sentence + parent_metric_hint` to try a deterministic alias match.

### Step 5

If unresolved after deterministic matching:

- create no dimension edge
- set `dimension_assignment_status = "unresolved"`

## Rules to avoid over-tagging

- Do not infer `energy_source=renewable` as a value. Renewable is a family concept, not one of the controlled source values here.
- Do not convert every `scope_2` fact into an `emission_source` dimension automatically. Scope is separate from source.
- Do not attach `waste_type=plastic` to packaging share percentages unless the fact is actually about waste/material flow rather than recyclability design share.
- Do not attach a dimension if the fact is the overall total and the dimension is merely implied by section context.

## Recommended loader properties on Observation

These are not separate nodes, but they make auditing easier:

```json
{
  "dimension_assignment_status": "assigned | unresolved | ambiguous | combined_reported_value",
  "dimension_assignment_mode": "single_value | multi_value | none",
  "dimension_source": "pass1_structured | deterministic_alias_match | manual_review"
}
```

## Implementation notes

- Canonical metrics stay canonical totals or stable concepts.
- Dimensional detail belongs on observations, not on canonical IDs.
- A dimensional alias should never cause a new canonical to be minted if the parent canonical already exists and the difference is only method/source/type.
- If human review later decides a repeated dimensional variant deserves its own canonical, that should be an explicit exception, not the default path.
