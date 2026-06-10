"""Unified pipeline runner: PDF -> chunks -> Pass 1 -> Pass 2 -> Neo4j KG."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Ensure pipeline/ and registry/ siblings are importable
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT / "registry"), str(_ROOT / "audit")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

ROOT = _ROOT
CONFIG_PATH = ROOT / "pipeline_config.json"

LOAD_STATUSES = {"normalized", "partial", "new_metric"}
SKIP_STATUSES = {"quarantine", "drop", "out_of_scope_financial"}


# ---------------------------------------------------------------------------
# Config + naming helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def make_prefix(company_id: str, year: int, calendar_type: str) -> str:
    prefix = "cy" if calendar_type == "calendar_year" else "fy"
    return f"{company_id}_{prefix}{year}"


def get_fiscal_year_label(year: int, calendar_type: str) -> str:
    return f"CY{year}" if calendar_type == "calendar_year" else f"FY{year}"


def get_doc_id(company_id: str, year: int, calendar_type: str) -> str:
    prefix = "cy" if calendar_type == "calendar_year" else "fy"
    return f"{company_id}_{prefix}{year}"


def get_period_dates(year: int, calendar_type: str) -> tuple[str, str]:
    if calendar_type == "calendar_year":
        return f"{year}-01-01", f"{year}-12-31"
    return f"{year - 1}-04-01", f"{year}-03-31"


def normalise_period_label(raw_label: str, report_year: int, calendar_type: str) -> str:
    if not raw_label or raw_label.lower() in ("unknown", "none", "", "open_ended"):
        return get_fiscal_year_label(report_year, calendar_type)
    match = re.search(r"20(\d{2})[-/](\d{2})", raw_label)
    if match:
        return f"FY20{match.group(2)}"
    years = re.findall(r"\b(20\d{2})\b", raw_label)
    if not years:
        return get_fiscal_year_label(report_year, calendar_type)
    year = int(years[-1])
    return f"CY{year}" if calendar_type == "calendar_year" else f"FY{year}"


def load_facts(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    facts = data.get("facts", data) if isinstance(data, dict) else data
    return [f for f in facts if isinstance(f, dict)]


def run_subprocess(cmd: list[str]) -> None:
    import subprocess
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"ERROR: command exited with code {result.returncode}")
        sys.exit(result.returncode)


def scope3_magnitude_guard(facts: list[dict]) -> list[dict]:
    scope1 = next((f for f in facts if f.get("canonical_id") == "scope_1_emissions_absolute"), None)
    if scope1 is None:
        return facts
    scope1_val = scope1.get("normalised_value") or 0
    quarantined = 0
    for f in facts:
        if f.get("canonical_id") == "scope_3_emissions_absolute":
            val = f.get("normalised_value") or 0
            if scope1_val > 0 and val < 0.01 * scope1_val:
                f["normalization_decision"] = "quarantine"
                f["normalization_status"] = "quarantine"
                f["quarantine_reason"] = "scope3_magnitude_implausible"
                quarantined += 1
    if quarantined:
        print(f"  Scope 3 guard: {quarantined} facts quarantined (implausibly small vs Scope 1 = {scope1_val:.0f})")
    return facts


# ---------------------------------------------------------------------------
# Stage functions
# ---------------------------------------------------------------------------

def _skip_if_exists(path: Path, stage_label: str, force: bool) -> bool:
    if not force and path.exists():
        print(f"  skipping — output already exists at {path}")
        return True
    return False


def run_ingest(args: argparse.Namespace, prefix: str, outdir: Path) -> None:
    chunks_path = outdir / f"{prefix}_fast_chunks.json"
    if _skip_if_exists(chunks_path, "Stage 1", args.force):
        return
    page_report_path = outdir / f"{prefix}_selected_pages.json"
    cmd = [
        sys.executable, str(_HERE / "fast_pdf_text_ingest.py"),
        str(args.pdf),
        "--output", str(chunks_path),
        "--company-name", args.company_name,
        "--doc-id", get_doc_id(args.company, args.year, args.calendar_type),
        "--filing-type", "annual_report",
        "--filing-year", str(args.year),
        "--fiscal-year-end", args.fiscal_year_end,
        "--currency", args.currency,
        "--page-report", str(page_report_path),
    ]
    if args.force_continue:
        cmd.append("--force-continue")
    run_subprocess(cmd)


def run_coverage_audit(args: argparse.Namespace, prefix: str, outdir: Path) -> str:
    page_report_path = outdir / f"{prefix}_selected_pages.json"
    audit_csv_path = outdir / f"{prefix}_section_coverage_audit.csv"
    if not _skip_if_exists(audit_csv_path, "Stage 2", args.force):
        run_subprocess([
            sys.executable, str(_HERE / "audit_selected_pages.py"),
            str(args.pdf),
            "--page-report", str(page_report_path),
            "--output", str(audit_csv_path),
        ])
    try:
        import csv
        with open(audit_csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        high_signal_unselected = sum(
            1 for r in rows if str(r.get("high_signal_unselected", "")).lower() == "true"
        )
        if high_signal_unselected > 0:
            print(f"  WARNING: {high_signal_unselected} high-signal pages unselected -- coverage risk HIGH")
            return "HIGH"
    except Exception:
        pass
    return "OK"


def run_pass1(args: argparse.Namespace, prefix: str, outdir: Path) -> None:
    chunks_path = outdir / f"{prefix}_fast_chunks.json"
    pass1_path = outdir / f"{prefix}_pass1.json"
    if _skip_if_exists(pass1_path, "Stage 3", args.force):
        # Print cost summary if it already exists
        cost_path = outdir / f"{prefix}_cost_summary.json"
        if cost_path.exists():
            try:
                import json as _json
                cs = _json.load(open(cost_path, encoding="utf-8"))
                c = cs.get("cost_usd", {})
                print(f"  API cost (cached): ${c.get('total', 0):.2f} "
                      f"({cs.get('prompt_tokens', 0)//1000}K prompt + "
                      f"{cs.get('completion_tokens', 0)//1000}K completion tokens)")
            except Exception:
                pass
        return
    run_subprocess([
        sys.executable, str(_HERE / "extractor.py"),
        "--input", str(chunks_path),
        "--output", str(pass1_path),
    ])


def run_pass2(args: argparse.Namespace, prefix: str, outdir: Path) -> None:
    pass1_path = outdir / f"{prefix}_pass1.json"
    pass2_path = outdir / f"{prefix}_pass2.json"
    if _skip_if_exists(pass2_path, "Stage 4", args.force):
        return
    run_subprocess([
        sys.executable, str(_HERE / "normalizer.py"),
        "--input", str(pass1_path),
        "--output", str(pass2_path),
    ])


def run_distance_audit(args: argparse.Namespace, prefix: str, outdir: Path) -> None:
    pass2_path = outdir / f"{prefix}_pass2.json"
    audit_path = outdir / f"{prefix}_new_metric_distance_audit.csv"
    import subprocess
    result = subprocess.run([
        sys.executable, str(_ROOT / "audit" / "new_metric_distance_audit.py"),
        "--pass2", str(pass2_path),
        "--output", str(audit_path),
    ], cwd=ROOT)
    if result.returncode != 0:
        print(f"WARNING: distance audit failed (exit {result.returncode}) — continuing to KG load")


# ---------------------------------------------------------------------------
# KG load
# ---------------------------------------------------------------------------

def ensure_period_node(session: Any, year: int, calendar_type: str) -> str:
    fiscal_year = get_fiscal_year_label(year, calendar_type)
    year_start, year_end = get_period_dates(year, calendar_type)
    session.run(
        "MERGE (p:Period {fiscal_year: $fy}) "
        "SET p.year_start = $ys, p.year_end = $ye, p.calendar = $cal",
        fy=fiscal_year, ys=year_start, ye=year_end, cal=calendar_type,
    )
    prev_label = get_fiscal_year_label(year - 1, calendar_type)
    session.run(
        "MATCH (prev:Period {fiscal_year: $prev}) "
        "MATCH (curr:Period {fiscal_year: $curr}) "
        "MERGE (prev)-[:NEXT_YEAR]->(curr)",
        prev=prev_label, curr=fiscal_year,
    )
    return fiscal_year


def load_chunks_to_graph(session: Any, chunks: list[dict], doc_id: str) -> None:
    sections: dict[str, dict] = {}
    for ch in chunks:
        sid = ch.get("section_id", "")
        if sid and sid not in sections:
            sections[sid] = {"section_id": sid, "title": ch.get("section_title", ""), "doc_id": doc_id}

    if sections:
        session.run(
            "UNWIND $rows AS r MERGE (s:Section {section_id: r.section_id}) SET s.title = r.title",
            rows=list(sections.values()),
        )
        session.run(
            "UNWIND $rows AS r "
            "MATCH (s:Section {section_id: r.section_id}), (d:Document {doc_id: $did}) "
            "MERGE (s)-[:IN_DOCUMENT]->(d)",
            rows=list(sections.values()), did=doc_id,
        )

    chunk_rows = [{
        "chunk_id":      ch["chunk_id"],
        "section_id":    ch.get("section_id", ""),
        "page":          ch.get("page_start", ch.get("page", 0)),
        "text":          ch.get("content", ""),
        "char_count":    ch.get("char_count", 0),
        "token_count":   ch.get("token_estimate", 0),
        "next_chunk_id": ch.get("next_chunk_id"),
    } for ch in chunks]

    session.run(
        "UNWIND $rows AS r MERGE (ch:Chunk {chunk_id: r.chunk_id}) "
        "SET ch.page = r.page, ch.text = r.text, "
        "    ch.char_count = r.char_count, ch.token_count = r.token_count",
        rows=chunk_rows,
    )
    session.run(
        "UNWIND $rows AS r "
        "MATCH (ch:Chunk {chunk_id: r.chunk_id}), (s:Section {section_id: r.section_id}) "
        "MERGE (ch)-[:IN_SECTION]->(s)",
        rows=[r for r in chunk_rows if r["section_id"]],
    )
    nexts = [{"a": r["chunk_id"], "b": r["next_chunk_id"]} for r in chunk_rows if r["next_chunk_id"]]
    if nexts:
        session.run(
            "UNWIND $rows AS r "
            "MATCH (a:Chunk {chunk_id: r.a}), (b:Chunk {chunk_id: r.b}) MERGE (a)-[:NEXT]->(b)",
            rows=nexts,
        )
    print(f"  Chunks: {len(sections)} sections, {len(chunks)} chunks, {len(nexts)} NEXT edges")


def _doc_year(doc_id: str) -> int:
    """Extract the year integer from a doc_id like 'nestle_india_fy2024'. Returns 0 if not found."""
    m = re.search(r"fy(\d{4})", str(doc_id).lower())
    return int(m.group(1)) if m else 0


def deduplicate_cross_document(
    session: Any,
    facts: list[dict],
    company_id: str,
    doc_id: str,
) -> list[dict]:
    """
    For each fact about to be loaded, check if a canonical Observation already
    exists in the graph for the same company + canonical_id + fiscal_year with
    a value within 1% tolerance.

    Keep the observation from the document whose year best matches the reported
    period year — i.e. prefer the FY2024 document for FY2024 facts over the
    FY2025 document's comparative table row.

    Returns the filtered list of facts to actually load.
    """
    incoming_doc_year = _doc_year(doc_id)
    to_load: list[dict] = []
    skipped = 0

    for fact in facts:
        canonical_id = str(fact.get("canonical_id") or "").strip()
        normalised_value = fact.get("normalised_value")
        period_label = str(fact.get("period_label") or fact.get("period") or "").strip()
        status = str(fact.get("normalization_decision") or fact.get("normalization_status") or "").lower()

        # Only deduplicate canonical (normalized/partial) facts with a value and period
        if not canonical_id or normalised_value is None or not period_label or status not in ("normalized", "partial"):
            to_load.append(fact)
            continue

        # Derive period year from label (e.g. "FY2024" -> 2024)
        period_year_m = re.search(r"(\d{4})", period_label)
        period_year = int(period_year_m.group(1)) if period_year_m else 0

        try:
            val = float(normalised_value)
        except (TypeError, ValueError):
            to_load.append(fact)
            continue

        lo = val * 0.99 if val >= 0 else val * 1.01
        hi = val * 1.01 if val >= 0 else val * 0.99

        result = session.run(
            """
            MATCH (o:Observation)-[:OF_METRIC]->(m:Metric {canonical_id: $cid}),
                  (o)-[:REPORTED_BY]->(c:Company {company_id: $company}),
                  (o)-[:IN_PERIOD]->(p:Period {fiscal_year: $fy})
            WHERE o.normalised_value >= $lo AND o.normalised_value <= $hi
            RETURN o.source_doc_id AS existing_doc_id, o.obs_id AS obs_id
            LIMIT 1
            """,
            cid=canonical_id, company=company_id, fy=period_label, lo=lo, hi=hi,
        ).single()

        if result is None:
            # No duplicate — load it
            to_load.append(fact)
            continue

        existing_doc_id = result["existing_doc_id"] or ""
        existing_doc_year = _doc_year(existing_doc_id)

        # Prefer doc whose year matches the period year
        incoming_distance = abs(incoming_doc_year - period_year)
        existing_distance = abs(existing_doc_year - period_year)

        if incoming_distance < existing_distance:
            # Incoming doc is a better match — delete existing, load new
            session.run("MATCH (o:Observation {obs_id: $oid}) DETACH DELETE o", oid=result["obs_id"])
            to_load.append(fact)
        else:
            # Existing doc is equal or better match — skip incoming
            skipped += 1

    if skipped:
        print(f"  Cross-doc dedup: skipped {skipped} duplicate comparative facts", flush=True)
    return to_load


def load_observations_to_graph(
    session: Any,
    facts: list[dict],
    company_id: str,
    year: int,
    calendar_type: str,
    doc_id: str,
) -> dict[str, int]:
    counts: dict[str, int] = {
        "normalized": 0, "partial": 0, "new_metric": 0,
        "quarantine": 0, "skipped": 0, "evidence": 0,
    }
    provisional_ids: dict[str, str] = {}
    prov_counter = [0]

    result = session.run(
        "MATCH (m:Metric:Provisional {owner_company: $co}) RETURN count(m) as n",
        co=company_id,
    ).single()
    prov_counter[0] = result["n"] if result else 0

    for fact in facts:
        status = str(fact.get("normalization_decision") or fact.get("normalization_status") or "").lower()
        if status in SKIP_STATUSES:
            counts["quarantine" if status == "quarantine" else "skipped"] += 1
            continue
        if status not in LOAD_STATUSES:
            counts["skipped"] += 1
            continue

        raw = fact.get("raw") or {}
        fid = str(fact.get("fact_id") or "")
        obs_id = fid or f"obs_{fact.get('chunk_id', '')}_{fact.get('metric', '')}"
        chunk_id = str(fact.get("chunk_id") or "")

        raw_period = str(fact.get("period_label") or fact.get("period") or "").strip()
        period_lbl = normalise_period_label(raw_period, year, calendar_type)

        obs_props = {
            "obs_id":                   obs_id,
            "raw_name":                 str(fact.get("metric") or raw.get("raw_name") or ""),
            "raw_value":                str(fact.get("raw_value") or raw.get("raw_value") or ""),
            "raw_unit_string":          str(fact.get("raw_unit_string") or fact.get("raw_unit") or raw.get("raw_unit") or ""),
            "normalised_value":         fact.get("normalised_value"),
            "normalised_unit_symbol":   str(fact.get("normalised_unit_symbol") or ""),
            "normalisation_confidence": str(fact.get("normalisation_confidence") or ""),
            "period_label":             period_lbl,
            "period_start":             str(fact.get("period_start") or ""),
            "period_end":               str(fact.get("period_end") or ""),
            "period_type":              str(fact.get("period_type") or ""),
            "period_confidence":        str(fact.get("period_confidence") or ""),
            "fact_type":                str(fact.get("fact_type") or ""),
            "normalization_status":     status,
            "page":                     fact.get("page_start", fact.get("page")),
            "chunk_id":                 chunk_id,
            "canonical_id":             str(fact.get("canonical_id") or ""),
            "source_doc_id":            doc_id,
        }

        session.run("MERGE (o:Observation {obs_id: $p.obs_id}) SET o += $p", p=obs_props)

        session.run(
            "MATCH (o:Observation {obs_id: $oid}), (c:Company {company_id: $cid}) "
            "MERGE (o)-[:REPORTED_BY]->(c)",
            oid=obs_id, cid=company_id,
        )

        if period_lbl and period_lbl.lower() != "open_ended":
            session.run(
                "MATCH (o:Observation {obs_id: $oid}) "
                "MATCH (p:Period {fiscal_year: $fy}) "
                "MERGE (o)-[:IN_PERIOD]->(p)",
                oid=obs_id, fy=period_lbl,
            )

        if chunk_id:
            session.run(
                "MATCH (o:Observation {obs_id: $oid}), (ch:Chunk {chunk_id: $cid}) "
                "MERGE (o)-[:EXTRACTED_FROM]->(ch)",
                oid=obs_id, cid=chunk_id,
            )

        unit_sym = str(fact.get("normalised_unit_symbol") or "").strip()
        if unit_sym:
            session.run(
                "MATCH (o:Observation {obs_id: $oid}) "
                "MATCH (u:Unit {symbol: $sym}) "
                "MERGE (o)-[:MEASURED_IN]->(u)",
                oid=obs_id, sym=unit_sym,
            )

        canonical_id = str(fact.get("canonical_id") or "").strip()
        if status in ("normalized", "partial") and canonical_id:
            session.run(
                "MATCH (o:Observation {obs_id: $oid}), (m:Metric {canonical_id: $cid}) "
                "MERGE (o)-[:OF_METRIC]->(m)",
                oid=obs_id, cid=canonical_id,
            )
        elif status == "new_metric":
            raw_name = str(fact.get("metric") or raw.get("raw_name") or "")
            prov_key = raw_name.lower().strip()
            if prov_key not in provisional_ids:
                prov_counter[0] += 1
                prov_id = f"prov_{company_id}_{prov_counter[0]:04d}"
                provisional_ids[prov_key] = prov_id
                session.run(
                    "MERGE (m:Metric:Provisional {provisional_id: $pid}) "
                    "SET m.raw_name = $rn, m.owner_company = $co",
                    pid=prov_id, rn=raw_name, co=company_id,
                )
            session.run(
                "MATCH (o:Observation {obs_id: $oid}), (m:Metric {provisional_id: $pid}) "
                "MERGE (o)-[:OF_METRIC]->(m)",
                oid=obs_id, pid=provisional_ids[prov_key],
            )

        conf_id = f"conf_{obs_id}"
        session.run(
            "MERGE (cr:ConfidenceRecord {conf_id: $cid}) "
            "SET cr.normalization_status = $ns, "
            "    cr.normalisation_confidence = $nc, "
            "    cr.final_confidence = $fc",
            cid=conf_id,
            ns=status,
            nc=str(fact.get("normalisation_confidence") or ""),
            fc=float(fact.get("final_confidence") or 0.0),
        )
        session.run(
            "MATCH (o:Observation {obs_id: $oid}), (cr:ConfidenceRecord {conf_id: $cid}) "
            "MERGE (o)-[:HAS_CONFIDENCE]->(cr)",
            oid=obs_id, cid=conf_id,
        )

        ev_text = str(fact.get("evidence") or raw.get("source_sentence") or "").strip()
        if ev_text:
            ev_id = f"ev_{obs_id}"
            session.run("MERGE (e:Evidence {evidence_id: $eid}) SET e.text = $txt", eid=ev_id, txt=ev_text)
            session.run(
                "MATCH (o:Observation {obs_id: $oid}), (e:Evidence {evidence_id: $eid}) "
                "MERGE (o)-[:SUPPORTED_BY]->(e)",
                oid=obs_id, eid=ev_id,
            )
            if chunk_id:
                session.run(
                    "MATCH (e:Evidence {evidence_id: $eid}), (ch:Chunk {chunk_id: $cid}) "
                    "MERGE (e)-[:FOUND_IN]->(ch)",
                    eid=ev_id, cid=chunk_id,
                )
            counts["evidence"] += 1

        counts[status] = counts.get(status, 0) + 1

    return counts


_CATEGORY_TREE = {
    "environmental": {
        "water": ["water_consumption", "water_withdrawal", "water_discharge", "water_recharge", "water_conservation"],
        "energy": ["energy_consumption", "energy_intensity", "renewable_energy", "energy_conservation"],
        "emissions": ["scope_1", "scope_2", "scope_3", "ghg_intensity", "air_emissions"],
        "waste": ["waste_generation", "waste_recovery", "waste_disposal", "waste_intensity", "plastic_waste"],
        "packaging": ["plastic_packaging", "recyclable_packaging", "epr"],
    },
    "social": {
        "workforce": ["headcount", "safety", "training", "diversity"],
        "community": ["csr", "complaints"],
    },
    "governance": {
        "compliance": ["brsr", "epr_compliance"],
    },
    "operational_seed": {
        "financial": ["revenue", "profitability", "market_share"],
        "supply_chain": ["distribution", "logistics"],
    },
    "financial_backbone": {},
}

_CATEGORY_DISPLAY = {
    "environmental": "Environmental", "water": "Water", "energy": "Energy",
    "emissions": "Emissions", "waste": "Waste", "packaging": "Packaging",
    "social": "Social", "workforce": "Workforce", "community": "Community",
    "governance": "Governance", "compliance": "Compliance",
    "water_consumption": "Water Consumption", "water_withdrawal": "Water Withdrawal",
    "water_discharge": "Water Discharge", "water_recharge": "Water Recharge",
    "water_conservation": "Water Conservation", "energy_consumption": "Energy Consumption",
    "energy_intensity": "Energy Intensity", "renewable_energy": "Renewable Energy",
    "energy_conservation": "Energy Conservation", "scope_1": "Scope 1",
    "scope_2": "Scope 2", "scope_3": "Scope 3", "ghg_intensity": "GHG Intensity",
    "air_emissions": "Air Emissions", "waste_generation": "Waste Generation",
    "waste_recovery": "Waste Recovery", "waste_disposal": "Waste Disposal",
    "waste_intensity": "Waste Intensity", "plastic_waste": "Plastic Waste",
    "plastic_packaging": "Plastic Packaging", "recyclable_packaging": "Recyclable Packaging",
    "epr": "EPR", "headcount": "Headcount", "safety": "Safety", "training": "Training",
    "diversity": "Diversity", "csr": "CSR", "complaints": "Complaints",
    "brsr": "BRSR", "epr_compliance": "EPR Compliance",
    "operational_seed": "Operational", "financial": "Financial",
    "supply_chain": "Supply Chain", "distribution": "Distribution",
    "logistics": "Logistics", "revenue": "Revenue",
    "profitability": "Profitability", "market_share": "Market Share",
    "financial_backbone": "Financial Backbone",
}


def seed_metric_categories(session: Any) -> None:
    nodes, edges = [], []
    for top, subs in _CATEGORY_TREE.items():
        nodes.append({"id": top, "name": _CATEGORY_DISPLAY.get(top, top), "level": 0})
        for mid, leaves in subs.items():
            nodes.append({"id": mid, "name": _CATEGORY_DISPLAY.get(mid, mid), "level": 1})
            edges.append({"child": mid, "parent": top})
            for leaf in leaves:
                nodes.append({"id": leaf, "name": _CATEGORY_DISPLAY.get(leaf, leaf), "level": 2})
                edges.append({"child": leaf, "parent": mid})

    session.run(
        "UNWIND $rows AS r MERGE (c:MetricCategory {category_id: r.id}) "
        "SET c.name = r.name, c.level = r.level",
        rows=nodes,
    )
    for e in edges:
        session.run(
            "MATCH (ch:MetricCategory {category_id: $c}), (pa:MetricCategory {category_id: $p}) "
            "MERGE (ch)-[:SUBCATEGORY_OF]->(pa)",
            c=e["child"], p=e["parent"],
        )
    print(f"  Seeded {len(nodes)} MetricCategory nodes, {len(edges)} SUBCATEGORY_OF edges.", flush=True)


def run_upsert_canonicals(args: argparse.Namespace) -> None:
    """Upsert Metric:Canonical nodes for every entry in the combined registry.

    Reads consumer_master_registry_v1.json, the seed's OPERATIONAL_CANONICALS,
    and registry_additions_approved.json as a single source of truth.  Uses
    MERGE so the call is idempotent — running it on an already-current graph
    creates no duplicates and raises no errors.
    """
    from neo4j import GraphDatabase
    import sys as _sys
    _sys.path.insert(0, str(_ROOT / "registry"))
    from metric_registry_seed import REGISTRY as _SEED_REGISTRY

    # Build combined row list from the full merged REGISTRY.
    rows: list[dict] = []
    seen: set[str] = set()
    for entry in _SEED_REGISTRY:
        cid = str(entry.get("canonical_id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        rows.append({
            "canonical_id":   cid,
            "display_name":   str(entry.get("display_name") or entry.get("canonical_name") or cid),
            "category":       str(entry.get("category") or ""),
            "unit_family":    str(entry.get("unit_family") or ""),
            "metric_subject": str(entry.get("metric_subject") or ""),
            "metric_role":    str(entry.get("metric_role") or ""),
            "comparable":     bool(entry.get("comparable", True)),
            "external_refs":  json.dumps(entry.get("external_refs") or {}),
        })

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_pass))
    try:
        with driver.session(database="neo4j") as session:
            seed_metric_categories(session)
            session.run(
                "UNWIND $rows AS r "
                "MERGE (m:Metric {canonical_id: r.canonical_id}) "
                "SET m:Canonical, "
                "    m.display_name  = r.display_name, "
                "    m.category      = r.category, "
                "    m.unit_family   = r.unit_family, "
                "    m.metric_subject= r.metric_subject, "
                "    m.metric_role   = r.metric_role, "
                "    m.comparable    = r.comparable, "
                "    m.external_refs = r.external_refs",
                rows=rows,
            )
            session.run(
                "MATCH (m:Metric:Canonical) WHERE m.category <> '' "
                "MATCH (c:MetricCategory {category_id: toLower(replace(m.category,' ','_'))}) "
                "MERGE (m)-[:BELONGS_TO]->(c)"
            )
            count = session.run(
                "MATCH (m:Metric:Canonical) RETURN count(m) as n"
            ).single()["n"]
        print(f"  Upserted {len(rows)} canonical entries  |  Total Metric:Canonical nodes: {count}")
    finally:
        driver.close()


def run_kg_load(args: argparse.Namespace, prefix: str, outdir: Path) -> None:
    from neo4j import GraphDatabase

    pass2_path = outdir / f"{prefix}_pass2.json"
    chunks_path = outdir / f"{prefix}_fast_chunks.json"

    facts = load_facts(pass2_path)
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    print(f"  Facts: {len(facts)}  Chunks: {len(chunks)}")

    facts = scope3_magnitude_guard(facts)

    doc_id = get_doc_id(args.company, args.year, args.calendar_type)

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_pass))
    with driver.session(database="neo4j") as session:
        fiscal_year = ensure_period_node(session, args.year, args.calendar_type)
        print(f"  Period node: {fiscal_year}")

        session.run(
            "MERGE (c:Company {company_id: $cid}) "
            "SET c.name = $name, c.sector = $sector, c.country = $country",
            cid=args.company, name=args.company_name,
            sector=args.sector, country=args.country,
        )
        session.run(
            "MERGE (d:Document {doc_id: $did}) "
            "SET d.fiscal_year = $fy, d.report_type = 'annual_report', "
            "    d.filing_year = $year, d.calendar_type = $cal",
            did=doc_id, fy=fiscal_year, year=args.year, cal=args.calendar_type,
        )
        session.run(
            "MATCH (c:Company {company_id: $cid}), (d:Document {doc_id: $did}) "
            "MERGE (c)-[:FILED]->(d)",
            cid=args.company, did=doc_id,
        )

        load_chunks_to_graph(session, chunks, doc_id)
        facts = deduplicate_cross_document(session, facts, args.company, doc_id)
        counts = load_observations_to_graph(
            session, facts, args.company, args.year, args.calendar_type, doc_id
        )

        session.run("CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS FOR (c:Chunk) ON EACH [c.text]")
        session.run("CREATE FULLTEXT INDEX evidence_text_index IF NOT EXISTS FOR (e:Evidence) ON EACH [e.text]")

    driver.close()

    print(f"\n  Load complete: {args.company_name} {args.year}")
    print(f"    normalized:  {counts['normalized']}")
    print(f"    partial:     {counts['partial']}")
    print(f"    new_metric:  {counts['new_metric']}")
    print(f"    quarantined: {counts['quarantine']}")
    print(f"    skipped:     {counts['skipped']}")


def verify_load(args: argparse.Namespace, doc_id: str) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_pass))
    with driver.session(database="neo4j") as session:
        result = session.run(
            "MATCH (d:Document {doc_id: $did})"
            "<-[:IN_DOCUMENT]-(s:Section)"
            "<-[:IN_SECTION]-(ch:Chunk)"
            "<-[:EXTRACTED_FROM]-(o:Observation) "
            "RETURN count(DISTINCT o) as observations, "
            "       count(DISTINCT ch) as chunks, "
            "       count(DISTINCT s) as sections",
            did=doc_id,
        ).single()
        print(f"\n  Graph verification:")
        print(f"    Document:     {doc_id}")
        print(f"    Sections:     {result['sections']}")
        print(f"    Chunks:       {result['chunks']}")
        print(f"    Observations: {result['observations']}")

        print(f"\n  Total graph:")
        for r in session.run(
            "MATCH (n) RETURN labels(n)[0] as label, count(n) as count ORDER BY count DESC"
        ):
            print(f"    {r['label']:<25} {r['count']}")
    driver.close()


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def run_dry_run(args: argparse.Namespace) -> None:
    prefix = make_prefix(args.company, args.year, args.calendar_type)
    outdir = Path(args.output_dir)
    doc_id = get_doc_id(args.company, args.year, args.calendar_type)
    fy_label = get_fiscal_year_label(args.year, args.calendar_type)

    print(f"\nDry run: {args.company} {fy_label}")

    pdf = Path(args.pdf)
    pdf_status = "found [ok]" if pdf.exists() else "NOT FOUND [!!]"
    print(f"  PDF:           {pdf_status}  ({args.pdf})")
    print(f"  Output prefix: {prefix}")

    for label, path in [
        ("Pass 1 output", outdir / f"{prefix}_pass1.json"),
        ("Pass 2 output", outdir / f"{prefix}_pass2.json"),
        ("Chunks file",   outdir / f"{prefix}_fast_chunks.json"),
    ]:
        status = "exists [ok]" if path.exists() else "(will be created)"
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = path
        print(f"  {label:<14} {rel}  {status}")

    if not args.no_kg:
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_pass))
            with driver.session(database="neo4j") as session:
                result = session.run(
                    "MATCH (p:Period {fiscal_year: $fy}) RETURN p.fiscal_year as fy",
                    fy=fy_label,
                ).single()
                period_exists = result is not None
            driver.close()
            print(f"  Neo4j:         connected [ok]")
            period_status = "exists [ok]" if period_exists else "(will be created)"
            print(f"  Period node:   {fy_label}  {period_status}")
        except Exception as e:
            print(f"  Neo4j:         connection failed -- {e}")

    print(f"  Would load:    doc_id={doc_id}")

    stages = []
    if not args.pass2_only:
        stages += ["ingest", "coverage_audit", "pass1"]
    if not args.pass1_only:
        stages += ["pass2", "distance_audit"]
        if not args.no_kg:
            stages += ["upsert_canonicals", "kg_load", "verify"]
    print(f"\n  Stages:        {' -> '.join(stages)}")
    print(f"\nReady. Remove --dry-run to execute.")


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def run_full_pipeline(args: argparse.Namespace) -> None:
    prefix = make_prefix(args.company, args.year, args.calendar_type)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    fy_label = get_fiscal_year_label(args.year, args.calendar_type)
    doc_id = get_doc_id(args.company, args.year, args.calendar_type)

    print(f"\n{'='*60}")
    print(f"Pipeline: {args.company_name} {fy_label}")
    print(f"PDF:      {args.pdf}")
    print(f"Prefix:   {prefix}")
    print(f"{'='*60}\n")

    if not args.pass2_only:
        print("Stage 1: Page selection and chunking...")
        run_ingest(args, prefix, outdir)

        print("\nStage 2: Coverage audit...")
        risk = run_coverage_audit(args, prefix, outdir)
        if risk == "HIGH" and not args.force_continue:
            print(f"\nHALTED -- Coverage audit returned HIGH risk.")
            print(f"Review: {outdir / f'{prefix}_section_coverage_audit.csv'}")
            print(f"Rerun with --force-continue to override.")
            sys.exit(1)

        print("\nStage 3: Pass 1 extraction...")
        run_pass1(args, prefix, outdir)

    if not args.pass1_only:
        print("\nStage 4: Pass 2 normalization...")
        run_pass2(args, prefix, outdir)

        print("\nStage 5: Distance audit...")
        run_distance_audit(args, prefix, outdir)

        if not args.no_kg:
            print("\nStage 6: Upserting canonical Metric nodes...")
            run_upsert_canonicals(args)

            print("\nStage 7: Loading into Neo4j...")
            run_kg_load(args, prefix, outdir)

            print("\nStage 8: Verification...")
            verify_load(args, doc_id)

    print(f"\n{'='*60}")
    print(f"Pipeline complete: {args.company_name} {fy_label}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser(config: dict) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified ESG pipeline runner: PDF -> Pass 1 -> Pass 2 -> Neo4j KG",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--pdf",             required=True, help="Path to annual report PDF")
    parser.add_argument("--company",         required=True, help="Company ID e.g. nestle_india")
    parser.add_argument("--company-name",    required=True, help='Display name e.g. "Nestle India Limited"')
    parser.add_argument("--year",            required=True, type=int, help="Reporting year e.g. 2024")
    parser.add_argument("--calendar-type",   default="indian_fiscal",
                        choices=["indian_fiscal", "calendar_year"], help="Period type")
    parser.add_argument("--fiscal-year-end", default="March",
                        help="Month of fiscal year end e.g. March, December")
    parser.add_argument("--sector",          default=config.get("default_sector", "FMCG"))
    parser.add_argument("--country",         default=config.get("default_country", "India"))
    parser.add_argument("--currency",        default=config.get("default_currency", "INR"))
    parser.add_argument("--pass1-only",      action="store_true", help="Stop after Pass 1")
    parser.add_argument("--pass2-only",      action="store_true", help="Run Pass 2 using existing Pass 1 output")
    parser.add_argument("--no-kg",           action="store_true", help="Skip Neo4j load")
    parser.add_argument("--force-continue",  action="store_true", help="Override HIGH coverage risk gate")
    parser.add_argument("--force",           action="store_true", help="Rerun all stages even if output files exist")
    parser.add_argument("--dry-run",         action="store_true", help="Show what would run without executing")
    parser.add_argument("--output-dir",      default=config.get("output_dir", "workspace_test_outputs"))
    parser.add_argument("--neo4j-uri",       default=config.get("neo4j_uri",  "neo4j://127.0.0.1:7687"))
    parser.add_argument("--neo4j-user",      default=config.get("neo4j_user", "neo4j"))
    parser.add_argument("--neo4j-pass",      default=config.get("neo4j_pass", "Watermelon@123"))
    return parser


def main() -> None:
    config = load_config()
    parser = build_parser(config)
    args = parser.parse_args()

    if args.pass1_only and args.pass2_only:
        parser.error("--pass1-only and --pass2-only are mutually exclusive")

    if args.dry_run:
        run_dry_run(args)
    else:
        run_full_pipeline(args)


if __name__ == "__main__":
    main()
