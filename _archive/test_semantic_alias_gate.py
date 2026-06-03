from __future__ import annotations

from semantic_registry import SemanticTyping, derive_flow_direction, semantic_alias_gate


def _gate(
    fact: SemanticTyping,
    canonical: SemanticTyping,
    fact_unit: str,
    canonical_unit: str,
):
    return semantic_alias_gate(
        fact_semantics=fact,
        canonical_semantics=canonical,
        fact_unit_family=fact_unit,
        canonical_unit_family=canonical_unit,
    )


def test_derive_flow_direction_from_role() -> None:
    assert derive_flow_direction("recharge") == "restoration"
    assert derive_flow_direction("withdrawal") == "input"
    assert derive_flow_direction("consumption") == "consumed"
    assert derive_flow_direction("generation") == "output"
    assert derive_flow_direction("recycling") == "recovery"
    assert derive_flow_direction("disposal") == "output"
    assert derive_flow_direction("intensity") == "ratio"
    assert derive_flow_direction("not_a_role") == "unknown"


def test_blocks_water_recharge_vs_withdrawal() -> None:
    result = _gate(
        SemanticTyping(metric_subject="water", metric_role="recharge"),
        SemanticTyping(metric_subject="water", metric_role="withdrawal"),
        "volume",
        "volume",
    )
    assert result.eligible is False
    assert "role_mismatch" in result.block_reasons


def test_blocks_waste_generated_vs_recycled() -> None:
    result = _gate(
        SemanticTyping(metric_subject="waste", metric_role="generation"),
        SemanticTyping(metric_subject="waste", metric_role="recycling"),
        "weight",
        "weight",
    )
    assert result.eligible is False
    assert "role_mismatch" in result.block_reasons


def test_blocks_energy_per_revenue_vs_energy_per_tonne() -> None:
    result = _gate(
        SemanticTyping(metric_subject="energy", metric_role="intensity", denominator_type="revenue"),
        SemanticTyping(metric_subject="energy", metric_role="intensity", denominator_type="production"),
        "ratio",
        "ratio",
    )
    assert result.eligible is False
    assert "denominator_mismatch" in result.block_reasons


def test_blocks_total_energy_consumed_vs_renewable_energy_consumed() -> None:
    result = _gate(
        SemanticTyping(metric_subject="energy", metric_role="consumption", energy_source="total"),
        SemanticTyping(metric_subject="energy", metric_role="consumption", energy_source="renewable"),
        "energy",
        "energy",
    )
    assert result.eligible is False
    assert "energy_source_mismatch" in result.block_reasons


def test_blocks_unknown_role_on_either_side() -> None:
    result = _gate(
        SemanticTyping(metric_subject="water", metric_role="withdrawal"),
        SemanticTyping(metric_subject="water", metric_role=None),
        "volume",
        "volume",
    )
    assert result.eligible is False
    assert "canonical_untyped" in result.block_reasons


def test_passes_genuine_same_role_surface_variant() -> None:
    result = _gate(
        SemanticTyping(metric_subject="water", metric_role="withdrawal"),
        SemanticTyping(metric_subject="water", metric_role="withdrawal"),
        "volume",
        "volume",
    )
    assert result.eligible is True
    assert result.block_reasons == ()


def test_passes_same_energy_intensity_denominator_variant() -> None:
    result = _gate(
        SemanticTyping(metric_subject="energy", metric_role="intensity", denominator_type="production"),
        SemanticTyping(metric_subject="energy", metric_role="intensity", denominator_type="production"),
        "ratio",
        "ratio",
    )
    assert result.eligible is True
    assert result.block_reasons == ()
