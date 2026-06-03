from __future__ import annotations

from pathlib import Path
import tempfile

import fitz

from extractor import _neighbor_context_text
from fast_pdf_text_ingest import build_chunks
from models import Chunk, TemporalContext
from normalizer import _semantic_tiebreaker_conflict, _try_margin_tiebreaker, _is_financial_fact
from pass1_validate import enrich_fact, infer_period_label
from provisional_dedup import ProvisionalRecord, cluster_provisionals
from unit_normaliser import infer_unit_mapping, normalise_fact_value
from audit_selected_pages import run_coverage_audit


def test_growth_rate_fact_does_not_match_retail_operations_canonical() -> None:
    fact = {
        "metric": "supplier coverage rate",
        "evidence": "Supplier coverage rate improved by 12% year on year.",
        "raw": {
            "raw_name": "supplier coverage rate",
            "metric_core": "supplier_coverage_rate",
            "raw_unit": "%",
            "raw_value": "12",
            "source_sentence": "Supplier coverage rate improved by 12% year on year.",
        },
    }
    registry_lookup = {
        "distribution_coverage_growth": {
            "canonical_id": "distribution_coverage_growth",
            "metric_subject": "distribution",
            "metric_role": "coverage",
            "unit_family": "percentage",
        }
    }
    candidate = {"canonical_id": "distribution_coverage_growth", "score": 0.84}
    conflict = _semantic_tiebreaker_conflict(candidate, fact, registry_lookup)
    assert conflict is not None
    assert "subject_mismatch" in conflict


def test_subject_mismatch_blocks_tiebreaker_accept() -> None:
    fact = {
        "metric": "scope 1+2 water intensity",
        "evidence": "Scope 1+2 water intensity improved by 4%.",
        "raw": {
            "raw_name": "scope 1+2 water intensity",
            "metric_core": "scope_1_2_water_intensity",
            "raw_unit": "%",
            "raw_value": "4",
            "source_sentence": "Scope 1+2 water intensity improved by 4%.",
        },
    }
    registry_lookup = {
        "combined_scope_1_2_emissions_intensity": {
            "canonical_id": "combined_scope_1_2_emissions_intensity",
            "metric_subject": "emissions",
            "metric_role": "intensity",
            "denominator_type": "production",
            "unit_family": "percentage",
        },
        "scope_3_emissions_intensity": {
            "canonical_id": "scope_3_emissions_intensity",
            "metric_subject": "emissions",
            "metric_role": "intensity",
            "denominator_type": "production",
            "unit_family": "percentage",
        },
    }
    top_candidates = [
        {"canonical_id": "combined_scope_1_2_emissions_intensity", "score": 0.83, "alias_score": 0.72, "metric_core_score": 0.78},
        {"canonical_id": "scope_3_emissions_intensity", "score": 0.75, "alias_score": 0.61, "metric_core_score": 0.68},
    ]
    decision, _, _, audit = _try_margin_tiebreaker(
        decision="provisional",
        reason="ambiguous match, margin too small",
        top_candidates=top_candidates,
        match_fact={"raw_name": "scope 1+2 water intensity", "metric_core": "scope_1_2_water_intensity", "source_sentence": fact["evidence"]},
        fact=fact,
        registry_lookup=registry_lookup,
    )
    assert decision == "provisional"
    assert "semantic incompatibility" in str(audit.get("tiebreaker_reason") or "")


def test_high_confidence_accepts_are_unaffected_by_tiebreaker_guard() -> None:
    fact = {
        "metric": "water consumption",
        "evidence": "Water consumption was 12 KL.",
        "raw": {"raw_name": "water consumption", "metric_core": "water_consumption", "raw_unit": "KL", "raw_value": "12"},
    }
    decision, reason, _, audit = _try_margin_tiebreaker(
        decision="accept",
        reason="score and margin passed",
        top_candidates=[{"canonical_id": "water_consumption_absolute", "score": 0.93, "alias_score": 0.91, "metric_core_score": 0.88}],
        match_fact={"raw_name": "water consumption", "metric_core": "water_consumption", "source_sentence": fact["evidence"]},
        fact=fact,
        registry_lookup={},
    )
    assert decision == "accept"
    assert reason == "score and margin passed"
    assert audit["resolution_method"] == "provisional"


def test_comparative_column_period_stamps_prior_year() -> None:
    fact = {
        "raw_name": "net sales",
        "raw_value": "120",
        "raw_unit": "crore",
        "raw_period": "FY2022",
        "source_sentence": "Net sales FY2022 120 crore",
        "period_type": "full_year",
        "fact_type": "measurement",
    }
    context = {"primary_period": "FY2023", "fiscal_period": "FY2023", "fiscal_year_end_month": "March", "filing_year": 2023}
    enriched = enrich_fact(fact, context)
    assert enriched["period"] == "FY2022"
    assert enriched["period_type"] == "full_year"
    assert enriched["period_start"] == "2021-04-01"
    assert enriched["period_end"] == "2022-03-31"


def test_missing_period_defaults_to_report_year_as_inferred() -> None:
    fact = {
        "raw_name": "water consumption",
        "raw_value": "12",
        "raw_unit": "KL",
        "raw_period": "",
        "source_sentence": "Water consumption was 12 KL.",
        "period_type": "unknown",
        "fact_type": "measurement",
    }
    context = {"primary_period": "FY2023", "fiscal_period": "FY2023", "fiscal_year_end_month": "March", "filing_year": 2023}
    enriched = enrich_fact(fact, context)
    assert enriched["period"] == "FY2023"
    assert enriched["period_confidence"] == "inferred"
    assert enriched["period_start"] is None
    assert enriched["period_end"] is None
    assert enriched["period_type"] == "unknown"


def test_evidence_year_is_used_when_raw_period_missing() -> None:
    fact = {
        "raw_name": "emissions",
        "raw_value": "10",
        "raw_unit": "tCO2e",
        "raw_period": "",
        "source_sentence": "For FY2021, emissions were 10 tCO2e.",
        "period_type": "full_year",
        "fact_type": "measurement",
    }
    period, confidence = infer_period_label(fact, {"primary_period": "FY2023", "fiscal_period": "FY2023", "filing_year": 2023})
    assert period == "FY2021"
    assert confidence == "extracted"


def test_fy2024_gets_full_year_date_bounds() -> None:
    enriched = enrich_fact(
        {
            "raw_name": "water withdrawal",
            "raw_value": "4.2",
            "raw_unit": "Mn KL",
            "raw_period": "FY2024",
            "source_sentence": "Water withdrawal was 4.2 Mn KL in FY2024.",
            "fact_type": "measurement",
            "period_type": "full_year",
        },
        {"primary_period": "FY2024", "fiscal_period": "FY2024", "fiscal_year_end_month": "March", "filing_year": 2024},
    )
    assert enriched["period_start"] == "2023-04-01"
    assert enriched["period_end"] == "2024-03-31"
    assert enriched["period_type"] == "full_year"


def test_target_period_type_detected() -> None:
    enriched = enrich_fact(
        {
            "raw_name": "water intensity reduction target",
            "raw_value": "30",
            "raw_unit": "%",
            "raw_period": "by 2030",
            "source_sentence": "We aim to reduce water intensity by 30% by 2030.",
            "fact_type": "target",
            "period_type": "target",
        },
        {"primary_period": "FY2024", "fiscal_period": "FY2024", "fiscal_year_end_month": "March", "filing_year": 2024},
    )
    assert enriched["fact_type"] == "target"
    assert enriched["period_type"] == "target"
    assert enriched["period_end"] == "2030-12-31"


def test_baseline_period_type_detected() -> None:
    enriched = enrich_fact(
        {
            "raw_name": "water intensity baseline",
            "raw_value": "5.2",
            "raw_unit": "kL/tonne",
            "raw_period": "FY2019 baseline",
            "source_sentence": "Our FY2019 baseline was 5.2 kL/tonne.",
        },
        {"primary_period": "FY2024", "fiscal_period": "FY2024", "fiscal_year_end_month": "March", "filing_year": 2024},
    )
    assert enriched["fact_type"] == "baseline"
    assert enriched["period_type"] == "baseline"
    assert enriched["period_start"] == "2018-04-01"
    assert enriched["period_end"] == "2019-03-31"


def test_no_period_information_can_stay_unknown() -> None:
    enriched = enrich_fact(
        {
            "raw_name": "zero waste to landfill achieved",
            "raw_value": "yes",
            "raw_unit": "",
            "raw_period": "",
            "source_sentence": "Zero waste to landfill achieved.",
            "period_type": "",
        },
        {"primary_period": "", "fiscal_period": "", "fiscal_year_end_month": "March", "filing_year": None},
    )
    assert enriched["period_start"] is None
    assert enriched["period_end"] is None
    assert enriched["period_type"] == "unknown"
    assert enriched["period_confidence"] == "inferred"


def test_fact_type_measurement() -> None:
    enriched = enrich_fact(
        {
            "raw_name": "Water withdrawal",
            "raw_value": "4.2",
            "raw_unit": "Mn KL",
            "raw_period": "FY2024",
            "source_sentence": "Water withdrawal was 4.2 Mn KL in FY2024.",
        },
        {"primary_period": "FY2024", "fiscal_period": "FY2024", "fiscal_year_end_month": "March", "filing_year": 2024},
    )
    assert enriched["fact_type"] == "measurement"


def test_fact_type_boolean() -> None:
    enriched = enrich_fact(
        {
            "raw_name": "Zero liquid discharge achieved",
            "raw_value": "9",
            "raw_unit": "units",
            "source_sentence": "Zero liquid discharge achieved at 9 units.",
        },
        {"primary_period": "FY2024", "fiscal_period": "FY2024", "fiscal_year_end_month": "March", "filing_year": 2024},
    )
    assert enriched["fact_type"] == "boolean"


def test_fact_type_count() -> None:
    enriched = enrich_fact(
        {
            "raw_name": "Number of manufacturing facilities",
            "raw_value": "28",
            "raw_unit": "",
            "source_sentence": "Number of manufacturing facilities: 28.",
        },
        {"primary_period": "FY2024", "fiscal_period": "FY2024", "fiscal_year_end_month": "March", "filing_year": 2024},
    )
    assert enriched["fact_type"] == "count"


def test_compound_unit_kgco2e_per_tonne_normalises() -> None:
    symbol, factor, confidence = infer_unit_mapping("kgCO2e/t", "GHG emissions intensity", "")
    assert symbol == "tCO2e/tonne"
    assert factor == 0.001
    assert confidence in {"exact", "inferred"}


def test_compound_unit_gj_per_crore_inr_normalises() -> None:
    symbol, factor, confidence = infer_unit_mapping("GJ/Crore INR", "energy intensity", "")
    assert symbol == "GJ/MINR"
    assert factor == 0.1
    assert confidence in {"exact", "inferred"}


def test_blank_unit_needs_context() -> None:
    result = normalise_fact_value(
        {
            "value": "4",
            "unit": "",
            "raw": {
                "raw_value": "4",
                "raw_unit": "",
                "raw_name": "energy savings",
                "source_sentence": "Energy savings improved to 4.",
            },
        }
    )
    assert result["normalisation_confidence"] == "needs_context"
    assert result["normalised_value"] is None


def test_failed_unit_mapping_keeps_normalised_value_null() -> None:
    result = normalise_fact_value(
        {
            "value": "12",
            "unit": "blorps/sprockets",
            "raw": {
                "raw_value": "12",
                "raw_unit": "blorps/sprockets",
                "raw_name": "some metric",
                "source_sentence": "Some metric was 12 blorps/sprockets.",
            },
        }
    )
    assert result["normalisation_confidence"] == "failed"
    assert result["normalised_value"] is None


def test_build_chunks_populates_prev_and_next_ids() -> None:
    chunks = build_chunks(
        [
            {"page": 1, "text": "alpha beta gamma delta epsilon " * 60, "include_score": 10, "exclude_score": 0, "has_numeric_metric": True},
        ],
        doc_id="demo",
        company_name="Demo Co",
        filing_year=2024,
        fiscal_year_end="March",
        max_words=40,
        overlap_words=5,
    )
    assert len(chunks) >= 2
    assert chunks[0]["prev_chunk_id"] is None
    assert chunks[0]["next_chunk_id"] == chunks[1]["chunk_id"]
    assert chunks[-1]["next_chunk_id"] is None
    assert chunks[-1]["prev_chunk_id"] == chunks[-2]["chunk_id"]


def test_neighbor_context_text_uses_available_neighbors() -> None:
    temporal_context = TemporalContext()
    prev_chunk = Chunk("doc", "sec", "c1", None, "c2", "Section", "Parent", 1, 1, "text", "prev", 4, 1, temporal_context)
    current_chunk = Chunk("doc", "sec", "c2", "c1", "c3", "Section", "Parent", 1, 1, "text", "current", 7, 1, temporal_context)
    next_chunk = Chunk("doc", "sec", "c3", "c2", None, "Section", "Parent", 1, 1, "text", "next", 4, 1, temporal_context)
    context = _neighbor_context_text(current_chunk, {chunk.chunk_id: chunk for chunk in [prev_chunk, current_chunk, next_chunk]})
    assert context == "prev\n---\ncurrent\n---\nnext"


def test_run_coverage_audit_returns_result_object() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "audit_test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Water withdrawal 4.2 Mn KL and energy intensity 3.8 GJ per tonne")
        doc.save(pdf_path)
        doc.close()

        result = run_coverage_audit(pdf_path, selected_pages=[])
        assert result.risk_level in {"HIGH", "MEDIUM", "LOW"}
        assert isinstance(result.flagged_pages, list)


def test_identical_metric_core_clusters_across_companies() -> None:
    report_rows, recurrence_counts = cluster_provisionals(
        [
            ProvisionalRecord("a", "water harvesting", "water_harvesting", "GCPL", "count", "water", "count", "gcpl.csv"),
            ProvisionalRecord("b", "water harvesting", "water_harvesting", "ITC", "count", "water", "count", "itc.csv"),
        ],
        threshold=0.82,
    )
    assert len(report_rows) == 1
    assert recurrence_counts["a"] == 2
    assert recurrence_counts["b"] == 2


def test_different_unit_family_does_not_cluster() -> None:
    report_rows, recurrence_counts = cluster_provisionals(
        [
            ProvisionalRecord("a", "water harvesting", "water_harvesting", "GCPL", "count", "water", "count", "gcpl.csv"),
            ProvisionalRecord("b", "water harvesting", "water_harvesting", "ITC", "volume", "water", "count", "itc.csv"),
        ],
        threshold=0.82,
    )
    assert len(report_rows) == 2
    assert recurrence_counts["a"] == 1
    assert recurrence_counts["b"] == 1


def test_same_company_records_do_not_cluster() -> None:
    report_rows, recurrence_counts = cluster_provisionals(
        [
            ProvisionalRecord("a", "water harvesting", "water_harvesting", "GCPL", "count", "water", "count", "gcpl.csv"),
            ProvisionalRecord("b", "water harvest", "water_harvesting", "GCPL", "count", "water", "count", "gcpl.csv"),
        ],
        threshold=0.82,
    )
    assert len(report_rows) == 2
    assert recurrence_counts["a"] == 1
    assert recurrence_counts["b"] == 1


# ---------------------------------------------------------------------------
# Fix 1 — financial classifier regression tests
# ---------------------------------------------------------------------------

def _fact(metric: str, graph_fact_type: str = "operational_metric") -> dict:
    return {"metric": metric, "raw": {"raw_name": metric, "graph_fact_type": graph_fact_type}}


def test_ebitda_is_financial() -> None:
    assert _is_financial_fact(_fact("EBITDA")) is True


def test_ebitda_margin_is_financial() -> None:
    assert _is_financial_fact(_fact("EBITDA margin")) is True


def test_revenue_growth_is_financial() -> None:
    assert _is_financial_fact(_fact("revenue growth")) is True


def test_cash_and_cash_equivalents_is_financial() -> None:
    assert _is_financial_fact(_fact("cash and cash equivalents")) is True


def test_operating_cash_flow_is_financial() -> None:
    assert _is_financial_fact(_fact("operating cash flow")) is True


def test_eps_is_financial() -> None:
    assert _is_financial_fact(_fact("earnings per share")) is True


def test_cagr_is_financial() -> None:
    assert _is_financial_fact(_fact("revenue CAGR")) is True


def test_graph_fact_type_financial_metric_is_financial() -> None:
    assert _is_financial_fact(_fact("Sales", graph_fact_type="financial_metric")) is True


def test_water_intensity_is_not_financial() -> None:
    assert _is_financial_fact(_fact("water intensity")) is False


def test_ghg_emissions_is_not_financial() -> None:
    assert _is_financial_fact(_fact("GHG emissions intensity")) is False


def test_outlet_count_is_not_financial() -> None:
    assert _is_financial_fact(_fact("outlet count")) is False


def test_match_fact_revenue_catches_financial() -> None:
    match_fact = {"raw_name": "total revenue", "metric_core": "total_revenue"}
    assert _is_financial_fact(_fact("Sales"), match_fact) is True


# ---------------------------------------------------------------------------
# Fix 1 extended — alias-bypass regression tests
# ---------------------------------------------------------------------------

def test_sales_is_financial() -> None:
    assert _is_financial_fact(_fact("Sales")) is True


def test_operating_cash_flow_is_financial() -> None:
    assert _is_financial_fact(_fact("Operating Cash Flow")) is True


def test_capital_expenditure_is_financial() -> None:
    assert _is_financial_fact(_fact("Capital Expenditure")) is True


def test_earnings_per_share_is_financial() -> None:
    assert _is_financial_fact(_fact("Earnings per share")) is True


def test_cash_and_cash_equivalents_is_financial() -> None:
    assert _is_financial_fact(_fact("cash and cash equivalents")) is True


def test_return_on_capital_employed_is_financial() -> None:
    assert _is_financial_fact(_fact("Return on Capital Employed")) is True


def test_number_of_employees_is_not_financial() -> None:
    assert _is_financial_fact(_fact("Number of employees")) is False


def test_water_intensity_kl_tonne_is_not_financial() -> None:
    assert _is_financial_fact(_fact("water intensity")) is False


# ---------------------------------------------------------------------------
# Fix 7+8 regression tests — period resolver and unit normaliser
# ---------------------------------------------------------------------------

def test_period_current_resolves_to_report_year() -> None:
    fact = {"raw_period": "current", "source_sentence": "committed to 100% EPR compliance as per PWM Rules 2016", "fact_type": "boolean"}
    label, confidence = infer_period_label(fact, {"primary_period": "FY2024", "fiscal_period": "FY2024", "filing_year": 2024})
    assert label == "FY2024"
    assert confidence == "inferred"


def test_period_ongoing_resolves_to_report_year() -> None:
    fact = {"raw_period": "ongoing", "source_sentence": "ongoing initiative", "fact_type": "target"}
    label, confidence = infer_period_label(fact, {"primary_period": "FY2024", "fiscal_period": "FY2024", "filing_year": 2024})
    assert label == "FY2024"
    assert confidence == "inferred"


def test_period_open_ended_target_returns_open_ended() -> None:
    fact = {"raw_period": "open-ended", "source_sentence": "permanent commitment", "fact_type": "target"}
    label, confidence = infer_period_label(fact, {"primary_period": "FY2024", "fiscal_period": "FY2024", "filing_year": 2024})
    assert label == "open_ended"
    assert confidence == "inferred"


def test_period_fy2024_still_extracted() -> None:
    fact = {"raw_period": "FY2024", "source_sentence": "Water withdrawal in FY2024 was 3.2 Mn kL.", "fact_type": "measurement"}
    label, confidence = infer_period_label(fact, {"primary_period": "FY2024", "fiscal_period": "FY2024", "filing_year": 2024})
    assert label == "FY2024"
    assert confidence == "extracted"


def test_period_fy2022_in_comparative_extracted() -> None:
    fact = {"raw_period": "FY2022", "source_sentence": "FY2022 water withdrawal was 2.8 Mn kL.", "fact_type": "measurement"}
    label, confidence = infer_period_label(fact, {"primary_period": "FY2024", "fiscal_period": "FY2024", "filing_year": 2024})
    assert label == "FY2022"
    assert confidence == "extracted"


def test_kl_tonne_intensity_not_converted() -> None:
    from unit_normaliser import normalise_fact_value
    fact = {"value": "4.69", "unit": "kL/tonne", "raw": {"raw_value": "4.69", "raw_unit": "kL/tonne", "raw_name": "water intensity", "source_sentence": ""}}
    result = normalise_fact_value(fact)
    assert result["normalised_unit_symbol"] == "kL/tonne"
    assert abs(result["normalised_value"] - 4.69) < 0.001


def test_joules_or_multiples_maps_to_gj() -> None:
    from unit_normaliser import normalise_fact_value
    fact = {"value": "1680843", "unit": "Joules or multiples", "raw": {"raw_value": "1680843", "raw_unit": "Joules or multiples", "raw_name": "energy consumed", "source_sentence": ""}}
    result = normalise_fact_value(fact)
    assert result["normalised_unit_symbol"] == "GJ"
    assert result["normalised_value"] == 1680843.0


def test_tons_co2_maps_to_tco2e() -> None:
    from unit_normaliser import normalise_fact_value
    fact = {"value": "120000", "unit": "tons CO2", "raw": {"raw_value": "120000", "raw_unit": "tons CO2", "raw_name": "CO2 reduction", "source_sentence": ""}}
    result = normalise_fact_value(fact)
    assert result["normalised_unit_symbol"] == "tCO2e"
    assert result["normalised_value"] == 120000.0
