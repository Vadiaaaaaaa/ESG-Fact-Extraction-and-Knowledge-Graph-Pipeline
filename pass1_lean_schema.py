RAW_LABEL_TYPE = [
    "metric_label",
    "dimension_member",
    "subtotal_label",
    "narrative_metric_phrase",
]

PERIOD_TYPE = ["annual", "quarterly", "half_year", "ttm", "point_in_time", "unknown"]

FACT_TYPE = [
    "actual",
    "comparative_reference",
    "guidance",
    "estimate",
    "delta",
    "ratio",
]

SCOPE = ["consolidated", "sub_entity", "unknown"]

DIMENSION_TYPE = [
    "geography",
    "segment",
    "brand",
    "channel",
    "product_category",
    "customer_type",
    "time_comparison",
    "none",
]

GRAPH_FACT_TYPE = [
    "financial_metric",
    "operational_metric",
    "breakdown_fact",
    "mix_share_metric",
    "contribution_metric",
    "specialized_note_metric",
    "table_scaffold",
]

FACT_CLASS = ["scalar_kpi", "change", "transition", "range", "ratio_change"]
DIRECTION = ["increased", "decreased", "unchanged", "reached"]

FACT_PROPERTIES = {
    "raw_name": {
        "type": "string",
        "description": "The label exactly as written in the text. Do not snake_case, normalize, or rewrite.",
    },
    "metric_core": {
        "type": "string",
        "description": "Stable snake_case metric-family slug derived from the fact's own subject, with no values, periods, or entity names.",
    },
    "fact_class": {
        "type": "string",
        "enum": FACT_CLASS,
        "description": "The fact expression type: scalar KPI, change, transition, range, or ratio_change.",
    },
    "direction": {
        "type": "string",
        "enum": DIRECTION,
        "description": "Movement polarity or level verb. Use decreased for reduced/lower/lesser, increased for improved/higher/growth, reached for absolute levels.",
    },
    "raw_label_type": {"type": "string", "enum": RAW_LABEL_TYPE},
    "raw_value": {
        "type": "string",
        "description": "Numeric value exactly as written, including %, commas, and sign. Must contain the reported number; do not use an empty string.",
    },
    "raw_unit": {
        "type": "string",
        "description": "Unit as written, e.g. %, $M, stores, bps.",
    },
    "raw_period": {"type": "string"},
    "baseline_year": {
        "type": ["string", "null"],
        "description": "Historical baseline/reference year for baseline-indexed facts, e.g. 2019 in 'vs 2019 baseline'. Null when not applicable.",
    },
    "source_sentence": {"type": "string"},
    "period_type": {"type": "string", "enum": PERIOD_TYPE},
    "fact_type": {"type": "string", "enum": FACT_TYPE},
    "scope": {"type": "string", "enum": SCOPE},
    "dimension_type": {"type": "string", "enum": DIMENSION_TYPE},
    "dimension_member": {"type": ["string", "null"]},
    "graph_fact_type": {
        "type": "string",
        "enum": GRAPH_FACT_TYPE,
        "description": "The fact's business role in the graph. Never a primitive like percentage, count, or currency.",
    },
    "parent_metric_hint": {"type": ["string", "null"]},
    "driver_phrase": {"type": ["string", "null"]},
}

PASS1_LEAN_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "pass1_lean_facts",
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
                        "required": list(FACT_PROPERTIES.keys()),
                        "properties": FACT_PROPERTIES,
                    },
                }
            },
        },
    },
}
