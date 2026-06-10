import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

PASS1_BALANCED_PROMPT_TEMPLATE = """
You extract business-relevant quantitative facts from consumer-company filings
(CPG, retail, beverage, apparel, food) as JSON. The output schema is enforced, so focus
your effort on semantic accuracy: pick the right label type, dimension, and graph type.

Maximize recall of business-relevant quantitative facts. Missing a real quantitative fact
is worse than extracting a borderline candidate fact, so bias toward recall in Pass 1.

QUANTITATIVE RECALL RULES:
Scan for every business-relevant quantitative expression, including:
  - percentages, rates, margins, penetration, mix, share
  - basis points / percentage points
  - ratios like 0.7x
  - counts of stores, products, factories, facilities, suppliers, users, lines, sites
  - durations and time values such as hours, days, years, quarters, man-hours
  - intensities and per-unit expressions such as kL/Ton, per employee, per sq ft, per serving
  - currency amounts including crore / lakh / million / billion
  - phrasing such as increased by, decreased by, reduced by, improved to, reached,
    achieved, represented, accounted for, contributed, grew by, declined by

COMPANY-SCOPE RULE:
Prioritize quantitative facts that describe the company, its brands, products, operations,
workforce, supply chain, sustainability performance, financial results, targets, or internal KPIs.
Do NOT extract macroeconomic, industry-wide, or general market statistics unless they are
explicitly reported as a company benchmark or a direct driver of the company’s reported performance.

ANTI-NOISE RULE:
Do NOT extract document-mechanical or legal-reference numbers such as section numbers,
annexure labels, page numbers, exhibit numbers, rule numbers, or certification codes,
unless the number itself is the business fact being reported.
Do NOT extract numerical references from biographical or legal text — years of experience,
tenure in years, award counts, committee membership seat counts. These are not operational metrics.

ABSOLUTE VALUE vs RELATIVE CHANGE:
When a sentence contains both an absolute figure and a relative change (e.g.
"4 million outlets — a remarkable two-fold increase since 2020"), extract the ABSOLUTE
figure (4 million, unit=count) as the primary fact. Extract the relative change (2x) only
as a secondary fact with fact_class=ratio_change. Never extract a multiplier or
fold-increase number as the raw_value of an absolute count or volume metric.

SUSTAINABILITY TARGETS:
Extract sustainability targets and commitments as facts with fact_type=target.
A target is any statement where the company commits to a specific measurable value by a future date.
Examples:
- "35% renewable energy by FY2026" -> raw_value=35, raw_unit=%, fact_type=target, period_end=2026-03-31
- "100% recyclable packaging by 2025" -> raw_value=100, raw_unit=%, fact_type=target, period_end=2025-12-31
Do NOT drop targets because they lack a current measured value.
The period for a target is the TARGET YEAR, not the report year.

Company: {company} | Period: {fiscal_period} | FY-end: {fiscal_year_end_month} | {filing_type} | {section}

RAW_LABEL_TYPE:
  metric_label            -> the label is a metric ("Net sales", "Comparable sales growth")
  dimension_member        -> the label is a place/brand/channel/category ("North America", "Hill's")
  subtotal_label          -> a subtotal or total row
  narrative_metric_phrase -> the number comes from prose ("grew 1.4%", "61st consecutive year")

Use dimension_member when a row/phrase is a geography, brand, channel, category, or customer label.
Do not default everything to metric_label.

DIMENSION:
If a fact is about a sub-unit, capture it and do not fold it into the metric name.
Example:
  "North America comparable sales growth 7.1%"
  -> raw_name may be the literal label text, dimension_type=geography,
     dimension_member="North America", parent_metric_hint="comparable sales growth".

PAIRED-VALUE RULE:
When a sentence reports movement from one value to another ("from X to Y", "improved from X to Y",
"reduced from X to Y"), extract the reported/current value as the primary raw_value when possible.
Preserve the comparison context in source_sentence and parent_metric_hint when helpful.
Do not skip paired-value facts just because two numbers appear in the sentence.

KPI-DEFINITION RULE:
If a sentence only defines, explains, or names a KPI without reporting a concrete quantitative value,
do NOT extract it as a fact. Every extracted fact must be grounded in a real number, threshold,
percentage, amount, ratio, count, duration, or intensity stated in the source sentence.

GRAPH_FACT_TYPE - tie-break in order:
  1. share / mix / penetration ratio              -> mix_share_metric
  2. pricing / volume / FX / M&A bridge component -> contribution_metric
  3. dimension-scoped metric                      -> breakdown_fact
  4. non-financial-statement KPI                  -> operational_metric
  5. else                                         -> financial_metric
Use specialized_note_metric for supplemental / footnote / non-GAAP note style facts.

FACT TYPE / PERIOD TYPE:
  fact_type   = measurement | target | baseline | ratio | boolean | count
  period_type = full_year | partial | point_in_time | cumulative | target | baseline | unknown
Extract labels and normalized dates when possible.

PERIOD EXTRACTION RULE:
- Extract the period the fact refers to, not merely the document period.
- Comparative columns matter: in a FY2023 report, a fact under an FY2022 column is an FY2022 fact.
- If the text or table explicitly references FY2022, FY 2021-22, CY2023, 2022-23, "as of March 2022",
  or similar, preserve that in raw_period.
- Do not leave raw_period blank when the source gives a detectable period label.
- Also populate period_start and period_end in ISO format when the range can be inferred.
- FY2024 means 2023-04-01 to 2024-03-31 for Indian fiscal-year reports.
- CY2024 means 2024-01-01 to 2024-12-31.
- "by 2030" -> fact_type=target, period_type=target, period_end=2030-12-31.
- "FY2019 baseline" -> fact_type=baseline, period_type=baseline.
- Unknown period is allowed: period_start=null, period_end=null, period_type=unknown.

UNIT EXTRACTION RULE:
- If the unit is present implicitly in the sentence, extract it explicitly in raw_unit.
- "302 million litres of water withdrawn" must produce raw_unit="million litres", not blank.

RAW LABEL RULE:
raw_name is always the literal text as written. Never snake_case or rewrite it.

Return {"facts": [ ... ]} matching the provided schema exactly. No prose, no markdown.

SECTION TEXT:
{section_text}
"""
