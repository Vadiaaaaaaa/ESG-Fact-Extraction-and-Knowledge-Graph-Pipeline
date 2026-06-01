PASS1A_RECALL_PROMPT_TEMPLATE = """
You are a recall-first fact spotter for consumer-company filings
(CPG, retail, beverage, apparel, food).

Your ONLY job is to find every concrete numeric metric-value pair
that could represent a business-relevant fact.

DO NOT type, classify, label graph types, or assess quality.
DO NOT filter aggressively. When in doubt, INCLUDE.

---

WHAT TO CAPTURE:

Scan every sentence clause by clause for any of the following numeric expressions:

  - percentages, rates, margins, growth rates, penetration, mix, share
  - basis points or percentage points
  - ratios (e.g. 0.7x, 2.3x)
  - counts: stores, SKUs, products, factories, facilities,
    suppliers, employees, users, lines, sites, markets
  - durations: hours, days, weeks, months, years, quarters,
    man-hours, training hours
  - intensities and per-unit values: kL/Ton, per employee,
    per sq ft, per serving, per tonne
  - currency amounts in any denomination:
    crore, lakh, million, billion, USD, INR, EUR, GBP, etc.
  - operational and ESG families - scan these specifically:
      safe working hours, training hours, man-hours per employee,
      water intensity (kL/Ton), recycled water %, renewable energy
      share %, supplier assessment coverage %, packaging material
      weight, plastic reduction %, waste diversion rate,
      carbon intensity, lost-time injury frequency, absenteeism rate,
      community investment amounts, energy consumption, energy
      intensity, water consumption, water intensity, freshwater
      consumption intensity, GHG emissions, CO2 emissions reduction,
      scope 1, scope 2, manufacturing productivity, throughput,
      OEE, capacity utilisation, unplanned downtime, asset reliability,
      inventory accuracy, dispatch accuracy, dispatch efficiency,
      fleet utilisation, logistics efficiency, finished goods movement,
      production planning accuracy, production lines, packaging lines
  - movement verbs paired with a number: increased by, decreased by,
    reduced by, improved to, reached, achieved, represented,
    accounted for, contributed, grew by, declined by, expanded to,
    contracted to, recovered to

NARRATIVE DECOMPOSITION RULE:
If one sentence contains multiple metric-value pairs, return one candidate
for each pair and reuse the same source_sentence. Do not stop after the
first number in a sentence.

Examples:
  "10% improvement in manufacturing productivity and 75 bps OEE increase"
    -> candidate for manufacturing productivity, value 10%
    -> candidate for OEE, value 75 bps

  "including a 15% reduction in downtime, a 12% improvement in dispatch
   efficiency, and improved production planning accuracy"
    -> candidate for unplanned downtime, value 15%
    -> candidate for dispatch efficiency, value 12%
    -> do not create a candidate for planning accuracy unless a number is given

  "rail transport increased 2.8x, contributing to 340 metric tons of CO2
   emissions reduction"
    -> candidate for rail transport volume, value 2.8x
    -> candidate for CO2 emissions reduction, value 340 metric tons

PAIRED-VALUE RULE:
If a sentence contains a movement from one value to another
("from X to Y", "improved from X to Y", "reduced from X to Y"),
capture the ENTIRE sentence as a single candidate.
  - raw_value_candidate = the "to" / current / reported value (Y)
  - prior_value         = the "from" / comparison value (X)
  - is_paired_value     = true
Do NOT split into two separate candidates.

SCOPE RULE:
Prioritise sentences about the company itself - its brands,
products, operations, workforce, supply chain, sustainability
performance, financial results, targets, or internal KPIs.
When in doubt, include the candidate and let later filtering decide.

EXCLUDE:
  - Clauses with no numeric value at all
  - Document-mechanical numbers: section numbers, annexure labels,
    page numbers, exhibit numbers, rule/regulation codes,
    certification codes - unless the number IS the reported fact

---

OUTPUT FORMAT:

Return a JSON object: {"candidates": [ ... ]}

Each candidate:
{
  "candidate_id":         string,
  "source_sentence":      string,
  "raw_name_hint":        string | null,
  "raw_value_candidate":  string,
  "prior_value":          string | null,
  "value_unit_raw":       string | null,
  "is_paired_value":      boolean,
  "extraction_note":      string | null
}

raw_name_hint should be the shortest faithful metric subject phrase near the
number, excluding the value and movement word when possible. For example:
"10% improvement in manufacturing productivity" -> "manufacturing productivity".

No prose. No markdown. Return only the JSON object.

---

Company: {company} | Period: {fiscal_period} | FY-end: {fiscal_year_end_month} | {filing_type} | {section}

SECTION TEXT:
{section_text}
"""


PASS1B_TYPING_PROMPT_TEMPLATE = """
You receive a list of candidate facts extracted from a consumer-company
filing (CPG, retail, beverage, apparel, food).

Your job is to:
  1. Filter out non-facts using the four checks below
  2. Convert each kept candidate into one or more typed semantic fact objects
  3. Assign label types, graph fact types, dimensions, and periods
     to everything that passes

---

STEP 1 - FILTER: apply these checks in order.
Drop a candidate if ANY of the following is true:

  KPI-DEFINITION CHECK  ->  filter_reason: "kpi_definition"
  The sentence only defines, explains, names, or describes a KPI
  without stating a concrete reported value.

  MACRO / COMPANY-SCOPE CHECK  ->  filter_reason: "company_scope_miss"
  The number describes a macroeconomic, industry-wide, competitor,
  or general market statistic that is NOT explicitly tied to the
  company's own reported performance, targets, or benchmarks.

  VALUE-VALIDITY CHECK  ->  filter_reason: "invalid_value"
  The raw_value_candidate is not a real number - it is a word like
  "percentage", "days", "unknown", or punctuation junk.
  DROP these entirely.

  DOCUMENT-MECHANICAL CHECK  ->  filter_reason: "doc_mechanical"
  The number is a section reference, annexure label, page number,
  exhibit number, or regulation code, not a reported business fact.

---

STEP 2 - SEMANTIC FACT TYPING:
For each candidate that passes, output one or more semantic fact objects.
One candidate sentence may yield MULTIPLE fact objects if the sentence reports
multiple quantitative facts.

Read narrative prose clause by clause. Keep one fact per metric-value pair.
Do not collapse a coordinated list of operational outcomes into one fact.

Use these fact_class values:
  scalar_kpi  -> single absolute value or level
  change      -> delta or movement only
  transition  -> moved from X to Y
  range       -> min/max range
  ratio_change -> multiplicative change such as 2.8x, threefold, fourfold

Examples:
  "10% improvement in manufacturing productivity and 75 bps increase in OEE"
    -> one change fact for manufacturing productivity, raw_value=10, change_unit=%
    -> one change fact for OEE, raw_value=75, change_unit=bps

  "85 bps improvement in OEE to 79.4%"
    -> one fact for the 79.4% level
    -> one fact for the 85 bps improvement

  "Productivity improved by 30%, increasing from 30.31 cases/person to 40 cases/person"
    -> one transition fact with old_value=30.31 cases/person, new_value=40 cases/person,
       change_value=30%, change_unit=%

  "pack sizes ranging from 200 ml to 2L"
    -> one range fact with range_min=200 ml, range_max=2L

  "Rail-based transportation volumes increased by 2.8x ..., contributing to 340 metric tons of CO2 emissions reduction"
    -> one ratio_change fact for 2.8x
    -> one scalar or change fact for 340 metric tons reduction

  "including a 15% reduction in unplanned downtime, a 12% improvement in warehouse
   dispatch efficiency, and improved production planning accuracy"
    -> one change fact for unplanned downtime
    -> one change fact for warehouse dispatch efficiency
    -> do not create a fact for production planning accuracy unless the candidate
       contains a numeric value for it

Interpretation rules:
  - If the sentence gives both a delta and an absolute level, extract both when they are
    independently meaningful.
  - If the sentence gives a clean from-X-to-Y movement, prefer one transition fact rather than
    two disconnected scalar facts.
  - For every kept fact, fact_class and metric_core should be non-null unless the metric
    genuinely cannot be identified.
  - metric_core should be a short normalized family name, not a canonical id.
  - raw_name must remain a short faithful metric subject phrase from the source sentence,
    not an invented canonical. It should usually exclude the numeric value and movement
    words like improvement, increase, decrease, reduction, growth, or decline.

Good raw_name examples:
  "manufacturing productivity", not "10% improvement in manufacturing productivity"
  "Overall Equipment Effectiveness (OEE)", not "75 basis point increase in OEE"
  "finished goods movement", not "8 lakh metric tons of finished goods movement"
  "warehouse dispatch efficiency", not "12% improvement in warehouse dispatch efficiency"

---

STEP 3 - TYPE ASSIGNMENT: for each candidate that passes, assign:

RAW_LABEL_TYPE (pick one):
  metric_label            -> the label is a metric name
  dimension_member        -> the label is a geography, brand,
                             channel, category, or customer
  subtotal_label          -> a subtotal or total row
  narrative_metric_phrase -> number comes from narrative prose

DIMENSION (fill when the fact is scoped to a sub-unit):
  dimension_type:    geography | brand | channel | product_category |
                     customer_type | segment | none
  dimension_member:  the actual name
  parent_metric_hint: the broader metric this is a slice of
                      (use raw_name_hint from Pass 1a as a starting point)

GRAPH_FACT_TYPE (tie-break in order):
  1. share / mix / penetration ratio       -> mix_share_metric
  2. pricing / volume / FX / M&A bridge    -> contribution_metric
  3. dimension-scoped metric               -> breakdown_fact
  4. non-financial-statement KPI           -> operational_metric
  5. financial statement line              -> financial_metric
  Use specialized_note_metric for footnote / non-GAAP / supplemental facts.

FACT_TYPE - use this rule precisely:
  Look at raw_value_candidate (the value being extracted).
  - If it is a level    - an absolute figure, rate, or index
    (e.g. 47.5%, EUR 268 million, 19 hours, 7.2x)  -> fact_type = "actual"
  - If it is a change   - a delta, movement, or variance only
    (e.g. +3%, down 120 bps, declined 11 days)      -> fact_type = "delta"
  Other valid values: comparative_reference | guidance | estimate | historical_reprint

PERIOD_TYPE (pick one):
  annual | quarterly | half_year | ttm | point_in_time | unknown

---

PAIRED-VALUE HANDLING:
If is_paired_value is true:
  - raw_value   = raw_value_candidate
  - prior_value = prior_value from input
  - direction   = infer from the verb in source_sentence:
                  "improved" | "increased" | "decreased" | "unchanged"
  - fact_class should usually be:
      transition  for from-X-to-Y movements
      change      for delta-only statements
      range       for explicit ranges
      ratio_change for multiplicative changes
  - fact_type   = "actual" if the main reported value is a level; "delta" if it
                  is only the size of the change

OUTPUT FORMAT:

Return a JSON object: {"facts": [ ... ]}

For each candidate, return one record with:
{
  "candidate_id":         string,
  "source_sentence":      string,
  "raw_name":             string | null,
  "raw_value":            string | null,
  "prior_value":          string | null,
  "direction":            string | null,
  "value_unit_raw":       string | null,
  "fact_class":           string | null,
  "metric_core":          string | null,
  "old_value":            string | null,
  "new_value":            string | null,
  "change_value":         string | null,
  "change_unit":          string | null,
  "range_min":            string | null,
  "range_max":            string | null,
  "range_unit":           string | null,
  "raw_label_type":       string | null,
  "graph_fact_type":      string | null,
  "fact_type":            string | null,
  "period_type":          string | null,
  "dimension_type":       string | null,
  "dimension_member":     string | null,
  "parent_metric_hint":   string | null,
  "filter_action":        string,
  "filter_reason":        string | null
}

Set filter_action to "keep" or "drop".
If filter_action is "drop", set unavailable classification fields to null.
Use a short literal raw_name from the source sentence. Use raw_name_hint if helpful,
but do not rewrite into canonical terminology.

No prose. No markdown. Return only the JSON object.

---

Company: {company} | Period: {fiscal_period} | FY-end: {fiscal_year_end_month} | {filing_type} | {section}

CANDIDATES:
{candidates_json}
"""


PASS1A_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "pass1a_candidates",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["candidates"],
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "candidate_id",
                            "source_sentence",
                            "raw_name_hint",
                            "raw_value_candidate",
                            "prior_value",
                            "value_unit_raw",
                            "is_paired_value",
                            "extraction_note",
                        ],
                        "properties": {
                            "candidate_id": {"type": "string"},
                            "source_sentence": {"type": "string"},
                            "raw_name_hint": {"type": ["string", "null"]},
                            "raw_value_candidate": {"type": "string"},
                            "prior_value": {"type": ["string", "null"]},
                            "value_unit_raw": {"type": ["string", "null"]},
                            "is_paired_value": {"type": "boolean"},
                            "extraction_note": {"type": ["string", "null"]},
                        },
                    },
                }
            },
        },
    },
}


PASS1B_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "pass1b_typed_facts",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["facts"],
            "properties": {
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "candidate_id",
                            "source_sentence",
                            "raw_name",
                            "raw_value",
                            "prior_value",
                            "direction",
                            "value_unit_raw",
                            "fact_class",
                            "metric_core",
                            "old_value",
                            "new_value",
                            "change_value",
                            "change_unit",
                            "range_min",
                            "range_max",
                            "range_unit",
                            "raw_label_type",
                            "graph_fact_type",
                            "fact_type",
                            "period_type",
                            "dimension_type",
                            "dimension_member",
                            "parent_metric_hint",
                            "filter_action",
                            "filter_reason",
                        ],
                        "properties": {
                            "candidate_id": {"type": "string"},
                            "source_sentence": {"type": "string"},
                            "raw_name": {"type": ["string", "null"]},
                            "raw_value": {"type": ["string", "null"]},
                            "prior_value": {"type": ["string", "null"]},
                            "direction": {
                                "type": ["string", "null"],
                                "enum": ["improved", "increased", "decreased", "unchanged", None],
                            },
                            "value_unit_raw": {"type": ["string", "null"]},
                            "fact_class": {
                                "type": ["string", "null"],
                                "enum": ["scalar_kpi", "change", "transition", "range", "ratio_change", None],
                            },
                            "metric_core": {"type": ["string", "null"]},
                            "old_value": {"type": ["string", "null"]},
                            "new_value": {"type": ["string", "null"]},
                            "change_value": {"type": ["string", "null"]},
                            "change_unit": {"type": ["string", "null"]},
                            "range_min": {"type": ["string", "null"]},
                            "range_max": {"type": ["string", "null"]},
                            "range_unit": {"type": ["string", "null"]},
                            "raw_label_type": {
                                "type": ["string", "null"],
                                "enum": ["metric_label", "dimension_member", "subtotal_label", "narrative_metric_phrase", None],
                            },
                            "graph_fact_type": {
                                "type": ["string", "null"],
                                "enum": [
                                    "financial_metric",
                                    "operational_metric",
                                    "breakdown_fact",
                                    "mix_share_metric",
                                    "contribution_metric",
                                    "specialized_note_metric",
                                    None,
                                ],
                            },
                            "fact_type": {
                                "type": ["string", "null"],
                                "enum": [
                                    "actual",
                                    "comparative_reference",
                                    "guidance",
                                    "estimate",
                                    "delta",
                                    "ratio",
                                    "historical_reprint",
                                    None,
                                ],
                            },
                            "period_type": {
                                "type": ["string", "null"],
                                "enum": ["annual", "quarterly", "half_year", "ttm", "point_in_time", "unknown", None],
                            },
                            "dimension_type": {
                                "type": ["string", "null"],
                                "enum": [
                                    "geography",
                                    "segment",
                                    "brand",
                                    "channel",
                                    "product_category",
                                    "customer_type",
                                    "none",
                                    None,
                                ],
                            },
                            "dimension_member": {"type": ["string", "null"]},
                            "parent_metric_hint": {"type": ["string", "null"]},
                            "filter_action": {"type": "string", "enum": ["keep", "drop"]},
                            "filter_reason": {
                                "type": ["string", "null"],
                                "enum": ["kpi_definition", "company_scope_miss", "invalid_value", "doc_mechanical", None],
                            },
                        },
                    },
                }
            },
        },
    },
}
