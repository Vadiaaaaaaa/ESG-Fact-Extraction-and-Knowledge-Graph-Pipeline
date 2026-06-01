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
  fact_type   = actual | comparative_reference | guidance | estimate | delta | ratio | historical_reprint
  period_type = annual | quarterly | half_year | ttm | point_in_time | unknown
Label only. Do not compute dates.

RAW LABEL RULE:
raw_name is always the literal text as written. Never snake_case or rewrite it.

Return {"facts": [ ... ]} matching the provided schema exactly. No prose, no markdown.

SECTION TEXT:
{section_text}
"""
