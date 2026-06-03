"""Neo4j knowledge graph loader for Nestle India."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

# ── Config ──────────────────────────────────────────────────────────────────
NEO4J_URI  = "bolt://127.0.0.1:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "Watermelon@123"
NEO4J_DB   = "neo4j"

ROOT   = Path(__file__).resolve().parent
OUTDIR = ROOT / "workspace_test_outputs"

PASS2_PATH   = OUTDIR / "nestle_india_4dot1mini_pass2.json"
CHUNKS_PATH  = OUTDIR / "nestle_india_rerun_fast_chunks.json"
REG_V1       = ROOT / "consumer_master_registry_v1.json"
REG_APPROVED = ROOT / "registry_additions_approved.json"
REG_OVERRIDES= ROOT / "registry_semantic_overrides.json"

COMPANY_ID  = "nestle_india"
COMPANY_NAME= "Nestlé India Limited"
DOC_ID      = "nestle_india_fy2024"


# ── Helpers ──────────────────────────────────────────────────────────────────
def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_facts(path: Path) -> list[dict]:
    data = load_json(path)
    facts = data.get("facts", data) if isinstance(data, dict) else data
    return [f for f in facts if isinstance(f, dict)]


def run(session, query: str, **params) -> list:
    return list(session.run(query, **params))


# ── Step 1: Scope 3 magnitude validation ─────────────────────────────────────
def scope3_validation(facts: list[dict]) -> list[dict]:
    scope1 = next(
        (f for f in facts if f.get("canonical_id") == "scope_1_emissions_absolute"),
        None,
    )
    if scope1 is None:
        print("Step 1: No scope_1_emissions_absolute found — skipping Scope 3 check.")
        return facts

    scope1_val = scope1.get("normalised_value") or 0
    quarantined = 0
    for f in facts:
        if f.get("canonical_id") == "scope_3_emissions_absolute":
            val = f.get("normalised_value") or 0
            if scope1_val > 0 and val < 0.01 * scope1_val:
                f["normalization_decision"] = "quarantine"
                f["normalization_status"]   = "quarantine"
                f["quarantine_reason"]       = "scope3_magnitude_implausible"
                quarantined += 1
    print(f"Step 1: Scope 1 = {scope1_val:.0f} | Scope 3 quarantined: {quarantined}")
    return facts


# ── Step 2: Constraints and indexes ──────────────────────────────────────────
CONSTRAINTS = [
    "CREATE CONSTRAINT company_id IF NOT EXISTS FOR (c:Company) REQUIRE c.company_id IS UNIQUE",
    "CREATE CONSTRAINT canonical_metric_id IF NOT EXISTS FOR (m:Metric) REQUIRE m.canonical_id IS UNIQUE",
    "CREATE CONSTRAINT obs_id IF NOT EXISTS FOR (o:Observation) REQUIRE o.obs_id IS UNIQUE",
    "CREATE CONSTRAINT period_fiscal_year IF NOT EXISTS FOR (p:Period) REQUIRE p.fiscal_year IS UNIQUE",
    "CREATE CONSTRAINT unit_symbol IF NOT EXISTS FOR (u:Unit) REQUIRE u.symbol IS UNIQUE",
    "CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (ch:Chunk) REQUIRE ch.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.section_id IS UNIQUE",
    "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:Evidence) REQUIRE e.evidence_id IS UNIQUE",
]

def create_constraints(session) -> None:
    for q in CONSTRAINTS:
        session.run(q)
    print(f"Step 2: {len(CONSTRAINTS)} constraints created.")


# ── Step 3: Period nodes ──────────────────────────────────────────────────────
def seed_periods(session) -> None:
    periods = [
        {"fiscal_year": f"FY{y}", "year_start": f"{y-1}-04-01",
         "year_end": f"{y}-03-31", "calendar": "indian_fiscal"}
        for y in range(2018, 2031)
    ]
    periods.append({"fiscal_year": "CY2022", "year_start": "2022-01-01",
                    "year_end": "2022-12-31", "calendar": "calendar_year"})
    periods.append({"fiscal_year": "FY2023_15M", "year_start": "2023-01-01",
                    "year_end": "2024-03-31", "calendar": "nestle_15month"})

    session.run(
        "UNWIND $rows AS r MERGE (p:Period {fiscal_year: r.fiscal_year}) "
        "SET p.year_start = r.year_start, p.year_end = r.year_end, p.calendar = r.calendar",
        rows=periods,
    )
    # NEXT_YEAR chain for Indian fiscal years
    fy = [p for p in periods if p["calendar"] == "indian_fiscal"]
    for i in range(len(fy) - 1):
        session.run(
            "MATCH (a:Period {fiscal_year:$a}),(b:Period {fiscal_year:$b}) "
            "MERGE (a)-[:NEXT_YEAR]->(b)",
            a=fy[i]["fiscal_year"], b=fy[i + 1]["fiscal_year"],
        )
    print(f"Step 3: {len(periods)} Period nodes seeded.")


# ── Step 4: MetricCategory hierarchy ─────────────────────────────────────────
CATEGORY_TREE = {
    "Environmental": {
        "Water": ["Water Consumption","Water Withdrawal","Water Discharge","Water Recharge","Water Conservation"],
        "Energy": ["Energy Consumption","Energy Intensity","Renewable Energy","Energy Conservation"],
        "Emissions": ["Scope 1","Scope 2","Scope 3","GHG Intensity","Air Emissions"],
        "Waste": ["Waste Generation","Waste Recovery","Waste Disposal","Waste Intensity","Plastic Waste"],
        "Packaging": ["Plastic Packaging","Recyclable Packaging","EPR"],
    },
    "Social": {
        "Workforce": ["Headcount","Safety","Training","Diversity"],
        "Community": ["CSR","Complaints"],
    },
    "Governance": {
        "Compliance": ["BRSR","EPR Compliance"],
    },
}

def seed_categories(session) -> None:
    nodes, edges = [], []
    def _id(name): return name.lower().replace(" ", "_")
    for top, subs in CATEGORY_TREE.items():
        nodes.append({"id": _id(top), "name": top, "level": 0})
        if isinstance(subs, dict):
            for mid, leaves in subs.items():
                nodes.append({"id": _id(mid), "name": mid, "level": 1})
                edges.append({"child": _id(mid), "parent": _id(top)})
                for leaf in leaves:
                    nodes.append({"id": _id(leaf), "name": leaf, "level": 2})
                    edges.append({"child": _id(leaf), "parent": _id(mid)})
        else:
            for leaf in subs:
                nodes.append({"id": _id(leaf), "name": leaf, "level": 1})
                edges.append({"child": _id(leaf), "parent": _id(top)})

    session.run(
        "UNWIND $rows AS r MERGE (c:MetricCategory {category_id: r.id}) SET c.name = r.name, c.level = r.level",
        rows=nodes,
    )
    for e in edges:
        session.run(
            "MATCH (ch:MetricCategory {category_id:$c}),(pa:MetricCategory {category_id:$p}) "
            "MERGE (ch)-[:SUBCATEGORY_OF]->(pa)",
            c=e["child"], p=e["parent"],
        )
    print(f"Step 4: {len(nodes)} MetricCategory nodes, {len(edges)} SUBCATEGORY_OF edges.")


# ── Step 5: Unit nodes ────────────────────────────────────────────────────────
UNITS = [
    {"symbol":"L",            "label":"Litre",                   "unit_family":"volume"},
    {"symbol":"kL",           "label":"Kilolitre",                "unit_family":"volume"},
    {"symbol":"ML",           "label":"Megalitre",                "unit_family":"volume"},
    {"symbol":"m3",           "label":"Cubic metre",              "unit_family":"volume"},
    {"symbol":"kg",           "label":"Kilogram",                 "unit_family":"weight"},
    {"symbol":"tonne",        "label":"Metric Tonne",             "unit_family":"weight"},
    {"symbol":"GJ",           "label":"Gigajoule",                "unit_family":"energy"},
    {"symbol":"MWh",          "label":"Megawatt-hour",            "unit_family":"energy"},
    {"symbol":"kWh",          "label":"Kilowatt-hour",            "unit_family":"energy"},
    {"symbol":"tCO2e",        "label":"Tonnes CO2 equivalent",    "unit_family":"emissions"},
    {"symbol":"kgCO2e",       "label":"Kilograms CO2 equivalent", "unit_family":"emissions"},
    {"symbol":"%",            "label":"Percentage",               "unit_family":"percentage"},
    {"symbol":"count",        "label":"Count",                    "unit_family":"count"},
    {"symbol":"INR",          "label":"Indian Rupee",             "unit_family":"monetary"},
    {"symbol":"kL/tonne",     "label":"Kilolitres per tonne",     "unit_family":"intensity"},
    {"symbol":"GJ/tonne",     "label":"Gigajoules per tonne",     "unit_family":"intensity"},
    {"symbol":"tCO2e/tonne",  "label":"Tonnes CO2e per tonne",   "unit_family":"intensity"},
    {"symbol":"kg/tonne",     "label":"Kilograms per tonne",      "unit_family":"intensity"},
]
CONVERSIONS = [
    ("kL","L",1000), ("ML","L",1_000_000), ("m3","L",1000),
    ("tonne","kg",1000), ("MWh","GJ",3.6), ("kWh","GJ",0.0036),
    ("kgCO2e","tCO2e",0.001),
]

def seed_units(session) -> None:
    session.run(
        "UNWIND $rows AS r MERGE (u:Unit {symbol:r.symbol}) SET u.label=r.label, u.unit_family=r.unit_family",
        rows=UNITS,
    )
    for src, dst, factor in CONVERSIONS:
        session.run(
            "MATCH (a:Unit {symbol:$a}),(b:Unit {symbol:$b}) MERGE (a)-[:CONVERTS_TO {factor:$f}]->(b)",
            a=src, b=dst, f=factor,
        )
    print(f"Step 5: {len(UNITS)} Unit nodes, {len(CONVERSIONS)} CONVERTS_TO edges.")


# ── Step 6: Metrics from registry ─────────────────────────────────────────────
def _cat_id(name: str) -> str:
    return (name or "").lower().replace(" ", "_")

def seed_metrics(session) -> None:
    # Use the full normalizer registry (271 entries) so all matched canonicals have nodes
    from normalizer import _metric_registry_with_seed
    entries: dict[str, dict] = {}
    for item in _metric_registry_with_seed():
        cid = str(item.get("canonical_id") or "").strip()
        if cid:
            entries[cid] = item
    # Overlay the richer JSON registry entries (they have more metadata)
    for path in (REG_V1, REG_APPROVED):
        data = load_json(path)
        items = data if isinstance(data, list) else data.get("metrics", data.get("registry", []))
        for item in items:
            cid = str(item.get("canonical_id") or "").strip()
            if cid:
                entries[cid] = {**entries.get(cid, {}), **item}
    overrides = load_json(REG_OVERRIDES)
    if isinstance(overrides, list):
        for o in overrides:
            cid = str(o.get("canonical_id") or "").strip()
            if cid and cid in entries:
                entries[cid].update(o)

    rows = []
    for cid, m in entries.items():
        rows.append({
            "canonical_id":  cid,
            "display_name":  str(m.get("display_name") or m.get("canonical_name") or m.get("raw_name") or cid),
            "category":      str(m.get("category") or ""),
            "unit_family":   str(m.get("unit_family") or m.get("unit") or ""),
            "metric_subject":str(m.get("metric_subject") or ""),
            "metric_role":   str(m.get("metric_role") or ""),
            "comparable":    bool(m.get("comparable", True)),
            "external_refs": json.dumps(m.get("external_refs") or {}),
        })

    session.run(
        "UNWIND $rows AS r "
        "MERGE (m:Metric {canonical_id: r.canonical_id}) "
        "SET m:Canonical, m.display_name=r.display_name, m.category=r.category, "
        "    m.unit_family=r.unit_family, m.metric_subject=r.metric_subject, "
        "    m.metric_role=r.metric_role, m.comparable=r.comparable, "
        "    m.external_refs=r.external_refs",
        rows=rows,
    )
    # Link to MetricCategory
    session.run(
        "MATCH (m:Metric:Canonical) WHERE m.category <> '' "
        "MATCH (c:MetricCategory {category_id: toLower(replace(m.category,' ','_'))}) "
        "MERGE (m)-[:BELONGS_TO]->(c)"
    )
    print(f"Step 6: {len(rows)} Metric nodes loaded.")


# ── Step 7: Company + Document ────────────────────────────────────────────────
def seed_company_doc(session) -> None:
    session.run(
        "MERGE (c:Company {company_id:$cid}) "
        "SET c.name=$name, c.sector='FMCG', c.country='India'",
        cid=COMPANY_ID, name=COMPANY_NAME,
    )
    session.run(
        "MERGE (d:Document {doc_id:$did}) "
        "SET d.fiscal_year='FY2024', d.report_type='annual_report', "
        "    d.page_count=244, d.has_brsr=true, d.has_third_party_assurance=true, "
        "    d.assurance_provider='GTBLLP', d.assurance_level='reasonable'",
        did=DOC_ID,
    )
    session.run(
        "MATCH (c:Company {company_id:$cid}),(d:Document {doc_id:$did}) MERGE (c)-[:FILED]->(d)",
        cid=COMPANY_ID, did=DOC_ID,
    )
    print("Step 7: Company and Document nodes created.")


# ── Step 8: Sections and Chunks ───────────────────────────────────────────────
def load_chunks(session, chunks: list[dict]) -> None:
    # Sections
    sections: dict[str, dict] = {}
    for ch in chunks:
        sid = ch.get("section_id","")
        if sid and sid not in sections:
            sections[sid] = {"section_id": sid, "title": ch.get("section_title",""),
                             "doc_id": DOC_ID}
    session.run(
        "UNWIND $rows AS r MERGE (s:Section {section_id:r.section_id}) "
        "SET s.title=r.title",
        rows=list(sections.values()),
    )
    session.run(
        "UNWIND $rows AS r "
        "MATCH (s:Section {section_id:r.section_id}),(d:Document {doc_id:$did}) "
        "MERGE (s)-[:IN_DOCUMENT]->(d)",
        rows=list(sections.values()), did=DOC_ID,
    )
    # Chunks
    rows = [{
        "chunk_id":    ch["chunk_id"],
        "section_id":  ch.get("section_id",""),
        "page":        ch.get("page_start", ch.get("page",0)),
        "text":        ch.get("content",""),
        "char_count":  ch.get("char_count",0),
        "token_count": ch.get("token_estimate",0),
        "prev_chunk_id": ch.get("prev_chunk_id"),
        "next_chunk_id": ch.get("next_chunk_id"),
    } for ch in chunks]
    session.run(
        "UNWIND $rows AS r MERGE (ch:Chunk {chunk_id:r.chunk_id}) "
        "SET ch.page=r.page, ch.text=r.text, ch.char_count=r.char_count, ch.token_count=r.token_count",
        rows=rows,
    )
    session.run(
        "UNWIND $rows AS r MATCH (ch:Chunk {chunk_id:r.chunk_id}),(s:Section {section_id:r.section_id}) "
        "MERGE (ch)-[:IN_SECTION]->(s)",
        rows=[r for r in rows if r["section_id"]],
    )
    # NEXT chain
    nexts = [{"a": r["chunk_id"], "b": r["next_chunk_id"]}
             for r in rows if r["next_chunk_id"]]
    if nexts:
        session.run(
            "UNWIND $rows AS r MATCH (a:Chunk {chunk_id:r.a}),(b:Chunk {chunk_id:r.b}) MERGE (a)-[:NEXT]->(b)",
            rows=nexts,
        )
    print(f"Step 8: {len(sections)} Section nodes, {len(chunks)} Chunk nodes, {len(nexts)} NEXT edges.")


# ── Step 9: Observations ─────────────────────────────────────────────────────
LOAD_STATUSES = {"normalized", "partial", "new_metric"}
PROVISIONAL_COUNTER = 0

def _period_label(fact: dict) -> str:
    pl = str(fact.get("period_label") or fact.get("period") or "").strip()
    if not pl or pl.lower() in ("", "unknown", "none"):
        return "FY2024"
    return pl

def load_observations(session, facts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {"normalized": 0, "partial": 0, "new_metric": 0,
                               "skipped": 0, "evidence": 0, "confidence": 0}
    provisional_ids: dict[str, str] = {}  # raw_name -> provisional_id
    prov_counter = [0]

    for fact in facts:
        status = str(fact.get("normalization_decision") or fact.get("normalization_status") or "").lower()
        if status not in LOAD_STATUSES:
            counts["skipped"] += 1
            continue

        fid   = str(fact.get("fact_id") or "")
        obs_id = fid or f"obs_{fact.get('chunk_id','')}_{fact.get('metric','')}"

        period_lbl = _period_label(fact)
        raw = fact.get("raw") or {}
        ev_text = str(fact.get("evidence") or raw.get("source_sentence") or "").strip()
        evidence_id = f"ev_{obs_id}"

        obs_props = {
            "obs_id":                 obs_id,
            "raw_name":               str(fact.get("metric") or raw.get("raw_name") or ""),
            "raw_value":              str(fact.get("raw_value") or raw.get("raw_value") or ""),
            "raw_unit_string":        str(fact.get("raw_unit_string") or fact.get("raw_unit") or raw.get("raw_unit") or ""),
            "normalised_value":       fact.get("normalised_value"),
            "normalised_unit_symbol": str(fact.get("normalised_unit_symbol") or ""),
            "normalisation_confidence": str(fact.get("normalisation_confidence") or ""),
            "period_label":           period_lbl,
            "period_start":           str(fact.get("period_start") or ""),
            "period_end":             str(fact.get("period_end") or ""),
            "period_type":            str(fact.get("period_type") or ""),
            "period_confidence":      str(fact.get("period_confidence") or ""),
            "fact_type":              str(fact.get("fact_type") or ""),
            "normalization_status":   status,
            "page":                   fact.get("page_start", fact.get("page")),
            "chunk_id":               str(fact.get("chunk_id") or ""),
            "canonical_id":           str(fact.get("canonical_id") or ""),
        }

        # Create Observation
        session.run(
            "MERGE (o:Observation {obs_id:$p.obs_id}) SET o += $p",
            p=obs_props,
        )

        # REPORTED_BY Company
        session.run(
            "MATCH (o:Observation {obs_id:$oid}),(c:Company {company_id:$cid}) "
            "MERGE (o)-[:REPORTED_BY]->(c)",
            oid=obs_id, cid=COMPANY_ID,
        )

        # IN_PERIOD — skip edge for open-ended commitments (no fixed period node)
        if period_lbl != "open_ended":
            session.run(
                "MATCH (o:Observation {obs_id:$oid}) "
                "MATCH (p:Period {fiscal_year:$fy}) "
                "MERGE (o)-[:IN_PERIOD]->(p)",
                oid=obs_id, fy=period_lbl,
            )

        # EXTRACTED_FROM Chunk
        cid = str(fact.get("chunk_id") or "")
        if cid:
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(ch:Chunk {chunk_id:$cid}) "
                "MERGE (o)-[:EXTRACTED_FROM]->(ch)",
                oid=obs_id, cid=cid,
            )

        # MEASURED_IN Unit
        unit_sym = str(fact.get("normalised_unit_symbol") or "").strip()
        if unit_sym:
            session.run(
                "MATCH (o:Observation {obs_id:$oid}) "
                "MATCH (u:Unit {symbol:$sym}) "
                "MERGE (o)-[:MEASURED_IN]->(u)",
                oid=obs_id, sym=unit_sym,
            )

        # OF_METRIC
        canonical_id = str(fact.get("canonical_id") or "").strip()
        if status in ("normalized", "partial") and canonical_id:
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(m:Metric {canonical_id:$cid}) "
                "MERGE (o)-[:OF_METRIC]->(m)",
                oid=obs_id, cid=canonical_id,
            )
        elif status == "new_metric":
            raw_name = str(fact.get("metric") or raw.get("raw_name") or "")
            prov_key = raw_name.lower().strip()
            if prov_key not in provisional_ids:
                prov_counter[0] += 1
                prov_id = f"prov_{COMPANY_ID}_{prov_counter[0]:04d}"
                provisional_ids[prov_key] = prov_id
                session.run(
                    "MERGE (m:Metric:Provisional {provisional_id:$pid}) "
                    "SET m.raw_name=$rn, m.owner_company=$co",
                    pid=prov_id, rn=raw_name, co=COMPANY_ID,
                )
            prov_id = provisional_ids[prov_key]
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(m:Metric {provisional_id:$pid}) "
                "MERGE (o)-[:OF_METRIC]->(m)",
                oid=obs_id, pid=prov_id,
            )

        # ConfidenceRecord
        conf_id = f"conf_{obs_id}"
        session.run(
            "MERGE (cr:ConfidenceRecord {conf_id:$cid}) "
            "SET cr.normalization_status=$ns, cr.normalisation_confidence=$nc, cr.final_confidence=$fc",
            cid=conf_id,
            ns=status,
            nc=str(fact.get("normalisation_confidence") or ""),
            fc=float(fact.get("final_confidence") or 0.0),
        )
        session.run(
            "MATCH (o:Observation {obs_id:$oid}),(cr:ConfidenceRecord {conf_id:$cid}) "
            "MERGE (o)-[:HAS_CONFIDENCE]->(cr)",
            oid=obs_id, cid=conf_id,
        )
        counts["confidence"] += 1

        # Evidence
        if ev_text:
            session.run(
                "MERGE (e:Evidence {evidence_id:$eid}) SET e.text=$txt",
                eid=evidence_id, txt=ev_text,
            )
            session.run(
                "MATCH (o:Observation {obs_id:$oid}),(e:Evidence {evidence_id:$eid}) "
                "MERGE (o)-[:SUPPORTED_BY]->(e)",
                oid=obs_id, eid=evidence_id,
            )
            if cid:
                session.run(
                    "MATCH (e:Evidence {evidence_id:$eid}),(ch:Chunk {chunk_id:$cid}) "
                    "MERGE (e)-[:FOUND_IN]->(ch)",
                    eid=evidence_id, cid=cid,
                )
            counts["evidence"] += 1

        counts[status] = counts.get(status, 0) + 1

    print(
        f"Step 9: normalized={counts['normalized']} partial={counts['partial']} "
        f"new_metric={counts['new_metric']} skipped={counts['skipped']} "
        f"evidence={counts['evidence']} confidence={counts['confidence']}"
    )
    return counts


# ── Step 10: Post-load indexes ────────────────────────────────────────────────
def create_fulltext_indexes(session) -> None:
    session.run(
        "CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS "
        "FOR (c:Chunk) ON EACH [c.text]"
    )
    session.run(
        "CREATE FULLTEXT INDEX evidence_text_index IF NOT EXISTS "
        "FOR (e:Evidence) ON EACH [e.text]"
    )
    print("Step 10: Fulltext indexes created.")


# ── Step 11: Verify ───────────────────────────────────────────────────────────
def verify(session) -> None:
    print("\n-- Verification ------------------------------------------------")

    print("\n[1] Node counts:")
    rows = run(session, "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC")
    for r in rows:
        print(f"  {r['label']:<25} {r['count']}")

    print("\n[2] Observation breakdown:")
    rows = run(session, "MATCH (o:Observation) RETURN o.normalization_status AS status, count(o) AS n ORDER BY n DESC")
    for r in rows:
        print(f"  {r['status']:<20} {r['n']}")

    print("\n[3] Nestle ESG facts (first 20):")
    rows = run(session,
        "MATCH (c:Company {company_id:'nestle_india'})<-[:REPORTED_BY]-(o:Observation)"
        "-[:OF_METRIC]->(m:Metric:Canonical),(o)-[:IN_PERIOD]->(p:Period) "
        "WHERE o.normalization_status IN ['normalized','partial'] "
        "RETURN m.category AS cat, m.display_name AS metric, o.normalised_value AS val, "
        "       o.normalised_unit_symbol AS unit, p.fiscal_year AS period "
        "ORDER BY m.category, m.display_name LIMIT 20"
    )
    for r in rows:
        print(f"  {str(r['cat']):<20} {str(r['metric']):<40} {str(r['val']):<20} {str(r['unit']):<15} {r['period']}")

    print("\n[4] Provenance (5 facts with source text):")
    rows = run(session,
        "MATCH (o:Observation)-[:SUPPORTED_BY]->(e:Evidence)-[:FOUND_IN]->(ch:Chunk) "
        "WHERE o.normalization_status = 'normalized' "
        "RETURN o.raw_name AS name, o.normalised_value AS val, e.text AS evidence, ch.page AS page "
        "LIMIT 5"
    )
    for r in rows:
        ev = (r['evidence'] or "")[:80].replace("\n"," ")
        print(f"  p{r['page']} | {r['name']}: {r['val']} | evidence: {ev}…")
    print("----------------------------------------------------------------")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("Loading data files…")
    facts  = load_facts(PASS2_PATH)
    chunks = load_json(CHUNKS_PATH)
    print(f"  facts: {len(facts)}  chunks: {len(chunks)}")

    facts = scope3_validation(facts)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    with driver.session(database=NEO4J_DB) as session:
        create_constraints(session)
        seed_periods(session)
        seed_categories(session)
        seed_units(session)
        seed_metrics(session)
        seed_company_doc(session)
        load_chunks(session, chunks)
        load_observations(session, facts)
        create_fulltext_indexes(session)
        verify(session)
    driver.close()
    print("\nDone.")


def scope3_raw_name_quarantine(facts: list[dict]) -> tuple[list[dict], int]:
    """Quarantine scope 3 facts with implausibly small values based on raw_name scan."""
    quarantined = 0
    for f in facts:
        raw_name = str(f.get("metric") or f.get("raw", {}).get("raw_name") or "").lower()
        nv = f.get("normalised_value")
        if "scope 3" in raw_name and nv is not None and nv < 1000:
            f["normalization_decision"] = "quarantine"
            f["normalization_status"]   = "quarantine"
            f["quarantine_reason"]       = "scope3_magnitude_implausible"
            quarantined += 1
    return facts, quarantined


def clear_nestle_data(session) -> dict[str, int]:
    """Delete all Nestle-specific nodes without touching shared infrastructure."""
    r1 = session.run(
        "MATCH (c:Company {company_id:'nestle_india'})<-[:REPORTED_BY]-(o:Observation) "
        "DETACH DELETE o RETURN count(o) AS n"
    ).single()
    r2 = session.run(
        "MATCH (d:Document {doc_id:'nestle_india_fy2024'}) DETACH DELETE d RETURN count(d) AS n"
    ).single()
    r3 = session.run(
        "MATCH (m:Metric:Provisional {owner_company:'nestle_india'}) DETACH DELETE m RETURN count(m) AS n"
    ).single()
    # Also clean up orphaned Evidence and ConfidenceRecord nodes
    session.run("MATCH (e:Evidence) WHERE NOT (e)<-[:SUPPORTED_BY]-() DETACH DELETE e")
    session.run("MATCH (cr:ConfidenceRecord) WHERE NOT (cr)<-[:HAS_CONFIDENCE]-() DETACH DELETE cr")
    # Clean up orphaned Sections and Chunks from previous Nestle load
    session.run(
        "MATCH (s:Section)-[:IN_DOCUMENT]->(d:Document {doc_id:'nestle_india_fy2024'}) "
        "DETACH DELETE s"
    )
    session.run(
        "MATCH (ch:Chunk) WHERE ch.chunk_id STARTS WITH 'nestle_india_' "
        "AND NOT (ch)<-[:EXTRACTED_FROM]-() DETACH DELETE ch"
    )
    return {
        "observations": r1["n"] if r1 else 0,
        "documents":    r2["n"] if r2 else 0,
        "provisionals": r3["n"] if r3 else 0,
    }


def reload_main() -> None:
    """Reload Nestle FY2024 using fresh gpt-4.1-mini outputs."""
    from dotenv import load_dotenv
    load_dotenv()

    print("Loading data files…")
    facts  = load_facts(PASS2_PATH)
    chunks = load_json(CHUNKS_PATH)
    print(f"  facts: {len(facts)}  chunks: {len(chunks)}")

    # Step 2 — Scope 3 quarantine
    facts, q_count = scope3_raw_name_quarantine(facts)
    print(f"Step 2: Scope 3 raw-name quarantine: {q_count} facts quarantined")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    with driver.session(database=NEO4J_DB) as session:

        # Step 1 — Clear previous Nestle data
        deleted = clear_nestle_data(session)
        print(f"Step 1: Deleted — observations={deleted['observations']} "
              f"documents={deleted['documents']} provisionals={deleted['provisionals']}")

        # Upsert Metric nodes with full registry (includes seed entries not in JSON files)
        seed_metrics(session)
        seed_company_doc(session)
        load_chunks(session, chunks)
        load_observations(session, facts)

        # Step 4 — Verify
        verify(session)

    driver.close()
    print("\nDone.")


if __name__ == "__main__":
    reload_main()
